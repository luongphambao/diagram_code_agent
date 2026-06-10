#!/usr/bin/env node
/**
 * Diagram Agent MCP Server — Component 4
 *
 * Exposes two interfaces in parallel:
 *   1. stdio MCP server  — interactive tools for Claude Desktop / Cursor
 *   2. HTTP REST API     — stateless endpoints for Python backend
 *        GET  /api/rest/health
 *        POST /api/rest/validate       {xml}                → validation result
 *        POST /api/rest/render         {xml}                → {png: "<base64>"}
 *        POST /api/rest/resolve-stencil {provider, keyword} → StencilMatch | null
 *        POST /api/rest/search-stencils {query, provider?, limit?} → StencilMatch[]
 *
 * MCP tools (interactive, require start_session):
 *   start_session, create_new_diagram, edit_diagram, get_diagram, export_diagram
 *   validate_drawio, render_drawio_png, resolve_stencil, search_stencils
 */

// DOM polyfill for Node.js (required for XML operations)
import { DOMParser } from "linkedom"
;(globalThis as any).DOMParser = DOMParser

class XMLSerializerPolyfill {
    serializeToString(node: any): string {
        if (node.outerHTML !== undefined) return node.outerHTML
        if (node.documentElement) return node.documentElement.outerHTML
        return ""
    }
}
;(globalThis as any).XMLSerializer = XMLSerializerPolyfill

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js"
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js"
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js"
import open from "open"
import { z } from "zod"
import http from "node:http"
import {
    applyDiagramOperations,
    type DiagramOperation,
} from "./diagram-operations.js"
import { addHistory } from "./history.js"
import {
    getState,
    registerRawHandler,
    registerRestHandler,
    requestSync,
    setState,
    shutdown,
    startHttpServer,
    waitForSync,
} from "./http-server.js"
import { log } from "./logger.js"
import { renderToPng } from "./render.js"
import { resolveStencil, searchStencils } from "./stencil-resolver.js"
import { validateAndFixXml, validateMxCellStructure } from "./xml-validation.js"

const config = {
    port: parseInt(process.env.PORT || "6002", 10),
}

// ── Headless MCP server (4 stateless tools for HTTP transport) ────────────────
// Separate instance from the stdio server: McpServer only supports one transport
// at a time, so we create a dedicated server for the Streamable HTTP endpoint.

function makeHeadlessMcpServer(): McpServer {
    const s = new McpServer({ name: "diagram-agent-mcp", version: "0.1.0" })

    s.registerTool(
        "validate_drawio",
        {
            description:
                "Validate draw.io XML and auto-fix common issues. " +
                "Returns validation result, fixed XML if applicable, and list of fixes applied.",
            inputSchema: {
                xml: z.string().describe("mxGraphModel XML to validate"),
                check_icon_broken: z
                    .boolean()
                    .optional()
                    .describe("If true, also count raster-PNG nodes that have a native stencil available"),
            },
        },
        async ({ xml, check_icon_broken }) => {
            const result = validateAndFixXml(xml)
            const rasterCount = check_icon_broken
                ? (xml.match(/shape=image;image=data:image\/png/g) || []).length
                : 0
            const lines: string[] = []
            lines.push(`valid: ${result.valid}`)
            if (result.error) lines.push(`error: ${result.error}`)
            if (result.fixes.length > 0) lines.push(`fixes applied: ${result.fixes.join(", ")}`)
            if (result.fixed) lines.push(`\nFixed XML:\n${result.fixed}`)
            if (rasterCount > 0)
                lines.push(`\nicon_broken: ${rasterCount} node(s) use raster PNG — check resolve_stencil for native vector alternatives.`)
            return { content: [{ type: "text", text: lines.join("\n").trim() }] }
        },
    )

    s.registerTool(
        "render_drawio_png",
        {
            description:
                "Headless-render mxGraph XML to PNG (returns base64). " +
                "Uses drawio desktop CLI if available, else Playwright headless browser.",
            inputSchema: {
                xml: z.string().describe("mxGraphModel or mxfile XML to render"),
            },
        },
        async ({ xml }) => {
            try {
                const buf = await renderToPng(xml)
                const b64 = buf.toString("base64")
                return {
                    content: [
                        {
                            type: "text",
                            text: `Rendered successfully. PNG size: ${buf.length} bytes\nbase64: data:image/png;base64,${b64}`,
                        },
                    ],
                }
            } catch (error) {
                const message = error instanceof Error ? error.message : String(error)
                return { content: [{ type: "text", text: `Error: ${message}` }], isError: true }
            }
        },
    )

    s.registerTool(
        "resolve_stencil",
        {
            description:
                "Look up a native draw.io stencil style string for a given cloud provider icon. " +
                "Always call this instead of hand-writing stencil names.",
            inputSchema: {
                provider: z
                    .string()
                    .describe("Cloud provider: aws, azure, gcp, k8s, alibabacloud, ibm, network, cisco …"),
                keyword: z
                    .string()
                    .describe("Icon name or keyword, e.g. 'ec2', 'virtual machine', 'load balancer'"),
            },
        },
        async ({ provider, keyword }) => {
            try {
                const match = await resolveStencil(provider, keyword)
                if (!match) {
                    return {
                        content: [
                            {
                                type: "text",
                                text: `No stencil found for provider="${provider}" keyword="${keyword}". Try search_stencils for fuzzy results.`,
                            },
                        ],
                    }
                }
                return {
                    content: [
                        {
                            type: "text",
                            text: [
                                `provider: ${match.provider}`,
                                `library:  ${match.library}`,
                                `shape:    ${match.shape}`,
                                match.category ? `category: ${match.category}` : null,
                                `style:    ${match.style}`,
                            ]
                                .filter(Boolean)
                                .join("\n"),
                        },
                    ],
                }
            } catch (error) {
                const message = error instanceof Error ? error.message : String(error)
                return { content: [{ type: "text", text: `Error: ${message}` }], isError: true }
            }
        },
    )

    s.registerTool(
        "search_stencils",
        {
            description:
                "Search the stencil catalog by keyword (all-terms match). " +
                "Use when resolve_stencil returns no result and you need to explore available shapes.",
            inputSchema: {
                query: z.string().describe("Search query, e.g. 'load balancer' or 'storage'"),
                provider: z
                    .string()
                    .optional()
                    .describe("Optional: limit to one provider (aws, azure, gcp, k8s …)"),
                limit: z.number().optional().describe("Max results (default 10)"),
            },
        },
        async ({ query, provider, limit }) => {
            try {
                const results = await searchStencils(query, provider, limit ?? 10)
                if (!results.length) {
                    return {
                        content: [{ type: "text", text: `No stencils found for query="${query}".` }],
                    }
                }
                const lines = results.map((r, i) =>
                    [
                        `${i + 1}. ${r.provider}/${r.library} → ${r.shape}${r.category ? ` (${r.category})` : ""}`,
                        `   style: ${r.style}`,
                    ].join("\n"),
                )
                return { content: [{ type: "text", text: lines.join("\n\n") }] }
            } catch (error) {
                const message = error instanceof Error ? error.message : String(error)
                return { content: [{ type: "text", text: `Error: ${message}` }], isError: true }
            }
        },
    )

    return s
}

let currentSession: {
    id: string
    xml: string
    version: number
    lastGetDiagramTime: number
} | null = null

// ── MCP Server ────────────────────────────────────────────────────────────────

const server = new McpServer({
    name: "diagram-agent-mcp",
    version: "0.1.0",
})

server.prompt(
    "diagram-workflow",
    "Guidelines for creating and editing draw.io diagrams",
    () => ({
        messages: [
            {
                role: "user",
                content: {
                    type: "text",
                    text: `# Diagram Agent MCP Workflow

## Creating a New Diagram
1. Call start_session to open browser preview
2. Use create_new_diagram with complete mxGraphModel XML

## Adding Elements to Existing Diagram
1. Use edit_diagram with "add" operation — server fetches latest state automatically

## Modifying or Deleting Elements
1. FIRST call get_diagram to see current cell IDs
2. THEN call edit_diagram with "update" or "delete" operations

## Native Stencil Icons
- Call resolve_stencil(provider, keyword) to get a verified draw.io style string
- Never hand-write stencil names — always use resolve_stencil
- Providers: aws, azure, gcp, k8s, alibabacloud, ibm, network, cisco …
- Example: resolve_stencil("aws", "ec2") → style=shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.ec2;…

## Validation
- validate_drawio(xml) checks and auto-fixes common XML issues before using`,
                },
            },
        ],
    }),
)

// ── Tool: start_session ───────────────────────────────────────────────────────

server.registerTool(
    "start_session",
    {
        description:
            "Start a new diagram session and open the browser for real-time preview.",
        inputSchema: {},
    },
    async () => {
        try {
            const port = await startHttpServer(config.port)

            const sessionId = `mcp-${Date.now().toString(36)}-${Math.random().toString(36).substring(2, 8)}`
            currentSession = {
                id: sessionId,
                xml: "",
                version: 0,
                lastGetDiagramTime: 0,
            }

            const browserUrl = `http://localhost:${port}?mcp=${sessionId}`
            await open(browserUrl)

            log.info(`Started session ${sessionId}, browser at ${browserUrl}`)

            return {
                content: [
                    {
                        type: "text",
                        text: `Session started!\n\nSession ID: ${sessionId}\nBrowser URL: ${browserUrl}`,
                    },
                ],
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            log.error("start_session failed:", message)
            return { content: [{ type: "text", text: `Error: ${message}` }], isError: true }
        }
    },
)

// ── Tool: create_new_diagram ──────────────────────────────────────────────────

server.registerTool(
    "create_new_diagram",
    {
        description:
            "Create a NEW diagram from mxGraphModel XML. ONLY use when creating from scratch — it REPLACES all existing content. Use edit_diagram for any modifications.",
        inputSchema: {
            xml: z.string().describe("REQUIRED: Complete mxGraphModel XML."),
        },
    },
    async ({ xml: inputXml }) => {
        try {
            if (!currentSession) {
                return {
                    content: [{ type: "text", text: "Error: No active session. Call start_session first." }],
                    isError: true,
                }
            }

            let xml = inputXml
            const { valid, error, fixed, fixes } = validateAndFixXml(xml)
            if (fixed) {
                xml = fixed
                log.info(`XML auto-fixed: ${fixes.join(", ")}`)
            }
            if (!valid && error) {
                return {
                    content: [{ type: "text", text: `Error: XML validation failed — ${error}` }],
                    isError: true,
                }
            }

            const browserState = getState(currentSession.id)
            if (browserState?.xml) currentSession.xml = browserState.xml

            if (currentSession.xml) {
                addHistory(currentSession.id, currentSession.xml, browserState?.svg || "")
            }

            currentSession.xml = xml
            currentSession.version++
            currentSession.lastGetDiagramTime = Date.now()
            setState(currentSession.id, xml)
            addHistory(currentSession.id, xml, "")

            return {
                content: [
                    { type: "text", text: `Diagram created. XML length: ${xml.length} chars` },
                ],
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            return { content: [{ type: "text", text: `Error: ${message}` }], isError: true }
        }
    },
)

// ── Tool: edit_diagram ────────────────────────────────────────────────────────

server.registerTool(
    "edit_diagram",
    {
        description:
            "Edit the current diagram by ID-based operations (add/update/delete cells). " +
            "Call get_diagram BEFORE this tool to see current cell IDs.",
        inputSchema: {
            operations: z
                .array(
                    z.object({
                        operation: z.enum(["update", "add", "delete"]),
                        cell_id: z.string(),
                        new_xml: z.string().optional(),
                    }),
                )
                .describe("Array of operations to apply"),
        },
    },
    async ({ operations }) => {
        try {
            if (!currentSession) {
                return {
                    content: [{ type: "text", text: "Error: No active session. Call start_session first." }],
                    isError: true,
                }
            }

            const timeSinceGet = Date.now() - currentSession.lastGetDiagramTime
            if (timeSinceGet > 30000) {
                return {
                    content: [
                        {
                            type: "text",
                            text: "Error: Call get_diagram first before edit_diagram to avoid data loss.",
                        },
                    ],
                    isError: true,
                }
            }

            const browserState = getState(currentSession.id)
            if (browserState?.xml) currentSession.xml = browserState.xml

            if (!currentSession.xml) {
                return {
                    content: [{ type: "text", text: "Error: No diagram to edit. Create one first." }],
                    isError: true,
                }
            }

            addHistory(currentSession.id, currentSession.xml, browserState?.svg || "")

            const validatedOps = operations.map((op) => {
                if (op.new_xml) {
                    const { fixed, fixes } = validateAndFixXml(op.new_xml)
                    if (fixed) {
                        log.info(`op ${op.operation} ${op.cell_id}: fixed: ${fixes.join(", ")}`)
                        return { ...op, new_xml: fixed }
                    }
                }
                return op
            })

            const { result, errors } = applyDiagramOperations(
                currentSession.xml,
                validatedOps as DiagramOperation[],
            )

            currentSession.xml = result
            currentSession.version++
            setState(currentSession.id, result)
            addHistory(currentSession.id, result, "")

            const successMsg = `Diagram edited — ${operations.length} operation(s) applied.`
            const errorMsg =
                errors.length > 0
                    ? `\n\nWarnings:\n${errors.map((e) => `- ${e.type} ${e.cellId}: ${e.message}`).join("\n")}`
                    : ""

            return { content: [{ type: "text", text: successMsg + errorMsg }] }
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            return { content: [{ type: "text", text: `Error: ${message}` }], isError: true }
        }
    },
)

// ── Tool: get_diagram ─────────────────────────────────────────────────────────

server.registerTool(
    "get_diagram",
    {
        description:
            "Get the current diagram XML (fetches latest from browser, including user manual edits). " +
            "Call this BEFORE edit_diagram.",
    },
    async () => {
        try {
            if (!currentSession) {
                return {
                    content: [{ type: "text", text: "Error: No active session. Call start_session first." }],
                    isError: true,
                }
            }

            const syncRequested = requestSync(currentSession.id)
            if (syncRequested) {
                const synced = await waitForSync(currentSession.id)
                if (!synced) log.warn("get_diagram: sync timeout — state may be stale")
            }

            currentSession.lastGetDiagramTime = Date.now()

            const browserState = getState(currentSession.id)
            if (browserState?.xml) currentSession.xml = browserState.xml

            if (!currentSession.xml) {
                return {
                    content: [{ type: "text", text: "No diagram yet. Use create_new_diagram." }],
                }
            }

            return {
                content: [{ type: "text", text: `Current diagram XML:\n\n${currentSession.xml}` }],
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            return { content: [{ type: "text", text: `Error: ${message}` }], isError: true }
        }
    },
)

// ── Tool: export_diagram ──────────────────────────────────────────────────────

server.registerTool(
    "export_diagram",
    {
        description: "Export the current diagram to a file (.drawio / .png / .svg).",
        inputSchema: {
            path: z.string().describe("File path to save (e.g., ./diagram.drawio)"),
            format: z.enum(["drawio", "png", "svg"]).optional(),
        },
    },
    async ({ path, format }) => {
        try {
            if (!currentSession) {
                return {
                    content: [{ type: "text", text: "Error: No active session." }],
                    isError: true,
                }
            }

            const browserState = getState(currentSession.id)
            if (browserState?.xml) currentSession.xml = browserState.xml

            if (!currentSession.xml) {
                return {
                    content: [{ type: "text", text: "Error: No diagram to export." }],
                    isError: true,
                }
            }

            const fs = await import("node:fs/promises")
            const nodePath = await import("node:path")

            const ext = nodePath.extname(path).toLowerCase()
            const detectedFormat =
                format || (ext === ".png" ? "png" : ext === ".svg" ? "svg" : "drawio")

            if (detectedFormat === "drawio") {
                let filePath = path
                if (!filePath.endsWith(".drawio")) filePath = `${filePath}.drawio`
                const absolutePath = nodePath.resolve(filePath)
                await fs.writeFile(absolutePath, currentSession.xml, "utf-8")
                return {
                    content: [{ type: "text", text: `Exported to ${absolutePath}` }],
                }
            }

            // PNG/SVG — request via browser export
            let filePath = path
            if (ext !== `.${detectedFormat}`) {
                if ([".drawio", ".png", ".svg"].includes(ext)) filePath = filePath.slice(0, -ext.length)
                filePath = `${filePath}.${detectedFormat}`
            }
            const absolutePath = nodePath.resolve(filePath)

            const state = getState(currentSession.id)
            if (!state) {
                return {
                    content: [{ type: "text", text: "Error: Session state not found. Is the browser open?" }],
                    isError: true,
                }
            }
            state.exportFormat = detectedFormat as "png" | "svg"
            state.exportData = undefined

            const timeoutMs = 10000
            const start = Date.now()
            while (Date.now() - start < timeoutMs) {
                if (state.exportData) break
                await new Promise((r) => setTimeout(r, 200))
            }

            const exportData = state.exportData as string | undefined
            state.exportData = undefined
            state.exportFormat = undefined

            if (!exportData) {
                return {
                    content: [{ type: "text", text: "Error: Export timed out. Make sure the browser tab is open." }],
                    isError: true,
                }
            }

            if (detectedFormat === "png") {
                const base64 = exportData.replace(/^data:image\/png;base64,/, "")
                await fs.writeFile(absolutePath, Buffer.from(base64, "base64"))
            } else {
                let svgContent = exportData
                if (svgContent.startsWith("data:image/svg+xml;base64,")) {
                    const base64 = svgContent.replace(/^data:image\/svg\+xml;base64,/, "")
                    svgContent = Buffer.from(base64, "base64").toString("utf-8")
                }
                await fs.writeFile(absolutePath, svgContent, "utf-8")
            }

            const stat = await fs.stat(absolutePath)
            return {
                content: [{ type: "text", text: `Exported to ${absolutePath} (${stat.size} bytes)` }],
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            return { content: [{ type: "text", text: `Error: ${message}` }], isError: true }
        }
    },
)

// ── Tool: validate_drawio ─────────────────────────────────────────────────────

server.registerTool(
    "validate_drawio",
    {
        description:
            "Validate draw.io XML and auto-fix common issues. " +
            "Returns validation result, fixed XML if applicable, and list of fixes applied. " +
            "Use before passing XML to create_new_diagram.",
        inputSchema: {
            xml: z.string().describe("mxGraphModel XML to validate"),
            check_icon_broken: z
                .boolean()
                .optional()
                .describe("If true, also check for raster-PNG nodes that have a native stencil available"),
        },
    },
    async ({ xml, check_icon_broken }) => {
        try {
            const result = validateAndFixXml(xml)

            let iconBrokenWarning = ""
            if (check_icon_broken && result.valid) {
                // Detect nodes using data:image/png when a native stencil likely exists
                const rasterPattern = /shape=image;image=data:image\/png/g
                const rasterCount = (xml.match(rasterPattern) || []).length
                if (rasterCount > 0) {
                    iconBrokenWarning = `\n\nicon_broken: ${rasterCount} node(s) use raster PNG — check resolve_stencil for native vector alternatives.`
                }
            }

            const lines: string[] = []
            lines.push(`valid: ${result.valid}`)
            if (result.error) lines.push(`error: ${result.error}`)
            if (result.fixes.length > 0) lines.push(`fixes applied: ${result.fixes.join(", ")}`)
            if (result.fixed) lines.push(`\nFixed XML:\n${result.fixed}`)
            lines.push(iconBrokenWarning)

            return { content: [{ type: "text", text: lines.join("\n").trim() }] }
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            return { content: [{ type: "text", text: `Error: ${message}` }], isError: true }
        }
    },
)

// ── Tool: render_drawio_png ───────────────────────────────────────────────────

server.registerTool(
    "render_drawio_png",
    {
        description:
            "Headless-render mxGraph XML to PNG (returns base64). " +
            "Uses drawio desktop CLI if available, else Playwright headless browser. " +
            "The Python backend critic uses this to inspect the actual rendered draw.io output.",
        inputSchema: {
            xml: z.string().describe("mxGraphModel or mxfile XML to render"),
        },
    },
    async ({ xml }) => {
        try {
            const buf = await renderToPng(xml)
            const b64 = buf.toString("base64")
            return {
                content: [
                    {
                        type: "text",
                        text: `Rendered successfully. PNG size: ${buf.length} bytes\nbase64: data:image/png;base64,${b64}`,
                    },
                ],
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            return { content: [{ type: "text", text: `Error: ${message}` }], isError: true }
        }
    },
)

// ── Tool: resolve_stencil ─────────────────────────────────────────────────────

server.registerTool(
    "resolve_stencil",
    {
        description:
            "Look up a native draw.io stencil style string for a given cloud provider icon. " +
            "Uses the verified stencil catalog (stencils_catalog.json). " +
            "Always call this instead of hand-writing stencil names.",
        inputSchema: {
            provider: z
                .string()
                .describe("Cloud provider: aws, azure, gcp, k8s, alibabacloud, ibm, network, cisco …"),
            keyword: z
                .string()
                .describe("Icon name or keyword, e.g. 'ec2', 'virtual machine', 'load balancer'"),
        },
    },
    async ({ provider, keyword }) => {
        try {
            const match = await resolveStencil(provider, keyword)
            if (!match) {
                return {
                    content: [
                        {
                            type: "text",
                            text: `No stencil found for provider="${provider}" keyword="${keyword}". Try search_stencils for fuzzy results.`,
                        },
                    ],
                }
            }

            return {
                content: [
                    {
                        type: "text",
                        text: [
                            `provider: ${match.provider}`,
                            `library:  ${match.library}`,
                            `shape:    ${match.shape}`,
                            match.category ? `category: ${match.category}` : null,
                            `style:    ${match.style}`,
                        ]
                            .filter(Boolean)
                            .join("\n"),
                    },
                ],
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            return { content: [{ type: "text", text: `Error: ${message}` }], isError: true }
        }
    },
)

// ── Tool: search_stencils ─────────────────────────────────────────────────────

server.registerTool(
    "search_stencils",
    {
        description:
            "Search the stencil catalog by keyword (all-terms match). " +
            "Use when resolve_stencil returns no result and you need to explore available shapes.",
        inputSchema: {
            query: z.string().describe("Search query, e.g. 'load balancer' or 'storage'"),
            provider: z
                .string()
                .optional()
                .describe("Optional: limit to one provider (aws, azure, gcp, k8s …)"),
            limit: z.number().optional().describe("Max results (default 10)"),
        },
    },
    async ({ query, provider, limit }) => {
        try {
            const results = await searchStencils(query, provider, limit ?? 10)
            if (!results.length) {
                return {
                    content: [{ type: "text", text: `No stencils found for query="${query}".` }],
                }
            }

            const lines = results.map((r, i) =>
                [
                    `${i + 1}. ${r.provider}/${r.library} → ${r.shape}${r.category ? ` (${r.category})` : ""}`,
                    `   style: ${r.style}`,
                ].join("\n"),
            )

            return {
                content: [{ type: "text", text: lines.join("\n\n") }],
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            return { content: [{ type: "text", text: `Error: ${message}` }], isError: true }
        }
    },
)

// ── REST API handlers (Python backend) ───────────────────────────────────────

registerRestHandler(
    "/validate",
    async (body: unknown, res: http.ServerResponse) => {
        const { xml } = body as { xml: string }
        if (typeof xml !== "string" || !xml) {
            res.writeHead(400, { "Content-Type": "application/json" })
            res.end(JSON.stringify({ error: "xml field required" }))
            return
        }

        const result = validateAndFixXml(xml)

        // icon_broken check: count raster PNG nodes
        const rasterCount = (xml.match(/shape=image;image=data:image\/png/g) || []).length

        res.writeHead(200, { "Content-Type": "application/json" })
        res.end(
            JSON.stringify({
                valid: result.valid,
                error: result.error,
                fixed: result.fixed,
                fixes: result.fixes,
                icon_broken_count: rasterCount,
            }),
        )
    },
)

registerRestHandler(
    "/render",
    async (body: unknown, res: http.ServerResponse) => {
        const { xml } = body as { xml: string }
        if (typeof xml !== "string" || !xml) {
            res.writeHead(400, { "Content-Type": "application/json" })
            res.end(JSON.stringify({ error: "xml field required" }))
            return
        }

        try {
            const buf = await renderToPng(xml)
            res.writeHead(200, { "Content-Type": "application/json" })
            res.end(
                JSON.stringify({
                    png: buf.toString("base64"),
                    size: buf.length,
                }),
            )
        } catch (err) {
            const message = err instanceof Error ? err.message : String(err)
            res.writeHead(500, { "Content-Type": "application/json" })
            res.end(JSON.stringify({ error: message }))
        }
    },
)

registerRestHandler(
    "/resolve-stencil",
    async (body: unknown, res: http.ServerResponse) => {
        const { provider, keyword } = body as { provider: string; keyword: string }
        if (!provider || !keyword) {
            res.writeHead(400, { "Content-Type": "application/json" })
            res.end(JSON.stringify({ error: "provider and keyword fields required" }))
            return
        }

        const match = await resolveStencil(provider, keyword)
        res.writeHead(200, { "Content-Type": "application/json" })
        res.end(JSON.stringify(match ?? null))
    },
)

registerRestHandler(
    "/search-stencils",
    async (body: unknown, res: http.ServerResponse) => {
        const { query, provider, limit } = body as {
            query: string
            provider?: string
            limit?: number
        }
        if (!query) {
            res.writeHead(400, { "Content-Type": "application/json" })
            res.end(JSON.stringify({ error: "query field required" }))
            return
        }

        const results = await searchStencils(query, provider, limit ?? 10)
        res.writeHead(200, { "Content-Type": "application/json" })
        res.end(JSON.stringify(results))
    },
)

// ── Graceful shutdown ─────────────────────────────────────────────────────────

let isShuttingDown = false
function gracefulShutdown(reason: string) {
    if (isShuttingDown) return
    isShuttingDown = true
    log.info(`Shutting down: ${reason}`)
    shutdown()
    process.exit(0)
}

process.on("SIGINT", () => gracefulShutdown("SIGINT"))
process.on("SIGTERM", () => gracefulShutdown("SIGTERM"))
process.stdout.on("error", (err) => {
    if (err.code === "EPIPE" || err.code === "ERR_STREAM_DESTROYED") {
        gracefulShutdown("stdout error")
    }
})

// ── Start ─────────────────────────────────────────────────────────────────────

async function main() {
    log.info("Starting Diagram Agent MCP server…")

    // Start HTTP server (serves browser UI + REST API)
    await startHttpServer(config.port)
    log.info(`REST API available at http://localhost:${config.port}/api/rest/`)

    // MCP Streamable HTTP — stateless mode, one fresh transport+server per request.
    // langchain-mcp-adapters opens a new HTTP session for every get_tools() / tool
    // call.  Stateful mode rejects the second initialize with 400; stateless mode
    // requires a brand-new transport instance per request (SDK throws if reused).
    registerRawHandler("/mcp", async (req, res) => {
        const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined })
        const srv = makeHeadlessMcpServer()
        await srv.connect(transport)
        await transport.handleRequest(req, res)
    })
    log.info(`MCP Streamable HTTP endpoint at http://localhost:${config.port}/mcp`)

    // Start MCP stdio transport (for Claude Desktop / Cursor).
    // Skip when MCP_HTTP_ONLY=true (e.g. Docker) — stdin is not attached there
    // and an immediate EOF would shut the process down.
    if (process.env.MCP_HTTP_ONLY !== "true") {
        const transport = new StdioServerTransport()
        await server.connect(transport)
        log.info("MCP server running on stdio")

        process.stdin.on("close", () => gracefulShutdown("stdin closed"))
        process.stdin.on("end", () => gracefulShutdown("stdin ended"))
    }
}

main().catch((error) => {
    log.error("Fatal error:", error)
    process.exit(1)
})
