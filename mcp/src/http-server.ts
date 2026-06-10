/**
 * Embedded HTTP Server for MCP
 * Serves draw.io embed with state sync and history UI.
 * Also exposes a REST API for headless render/validate used by Python backend.
 */

import http from "node:http"

const MAX_BODY_BYTES = 10 * 1024 * 1024 // 10 MiB

function readBody(
    req: http.IncomingMessage,
    res: http.ServerResponse,
    cb: (body: string) => void,
): void {
    let body = ""
    let size = 0
    req.on("data", (chunk: Buffer) => {
        size += chunk.length
        if (size > MAX_BODY_BYTES) {
            res.writeHead(413, { "Content-Type": "application/json" })
            res.end(JSON.stringify({ error: "Payload too large" }))
            req.destroy()
            return
        }
        body += chunk
    })
    req.on("end", () => cb(body))
}

import {
    addHistory,
    clearHistory,
    getHistory,
    getHistoryEntry,
    updateLastHistorySvg,
} from "./history.js"
import { log } from "./logger.js"
import { validateAndFixXml } from "./xml-validation.js"

// Configurable draw.io embed URL for private deployments
const DRAWIO_BASE_URL =
    process.env.DRAWIO_BASE_URL || "https://embed.diagrams.net"

function getOrigin(url: string): string {
    try {
        const parsed = new URL(url)
        return `${parsed.protocol}//${parsed.host}`
    } catch {
        return url
    }
}

const DRAWIO_ORIGIN = getOrigin(DRAWIO_BASE_URL)

const DEFAULT_DIAGRAM_XML = `<mxfile host="app.diagrams.net"><diagram id="blank" name="Page-1"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel></diagram></mxfile>`

function normalizeUrl(url: string): string {
    return url.replace(/\/$/, "")
}

function isLikelyMcpSessionId(sessionId: string): boolean {
    return sessionId.startsWith("mcp-") && sessionId.length <= 128
}

function getMostRecentSessionId(): string | null {
    let mostRecent: { id: string; lastUpdated: Date } | null = null
    for (const [sessionId, state] of stateStore) {
        if (!mostRecent || state.lastUpdated > mostRecent.lastUpdated) {
            mostRecent = { id: sessionId, lastUpdated: state.lastUpdated }
        }
    }
    return mostRecent?.id || null
}

function ensureSessionStateInitialized(sessionId: string): void {
    if (!sessionId) return
    if (!isLikelyMcpSessionId(sessionId)) return
    if (stateStore.has(sessionId)) return
    setState(sessionId, DEFAULT_DIAGRAM_XML)
}

interface SessionState {
    xml: string
    version: number
    lastUpdated: Date
    svg?: string
    syncRequested?: number
    exportFormat?: "png" | "svg"
    exportData?: string
}

export const stateStore = new Map<string, SessionState>()

let server: http.Server | null = null
let serverPort = 6002
const MAX_PORT = 6020
const SESSION_TTL = 60 * 60 * 1000

// REST API handlers injected from index.ts
type RestHandler = (
    body: unknown,
    res: http.ServerResponse,
) => Promise<void>

const restHandlers = new Map<string, RestHandler>()

export function registerRestHandler(path: string, handler: RestHandler): void {
    restHandlers.set(path, handler)
}

// Raw handlers bypass the built-in REST/UI routing (used by MCP Streamable HTTP)
type RawHandler = (
    req: http.IncomingMessage,
    res: http.ServerResponse,
) => void | Promise<void>

const rawHandlers = new Map<string, RawHandler>()

export function registerRawHandler(path: string, handler: RawHandler): void {
    rawHandlers.set(path, handler)
}

export function getState(sessionId: string): SessionState | undefined {
    return stateStore.get(sessionId)
}

export function setState(sessionId: string, xml: string, svg?: string): number {
    const existing = stateStore.get(sessionId)
    const newVersion = (existing?.version || 0) + 1
    stateStore.set(sessionId, {
        xml,
        version: newVersion,
        lastUpdated: new Date(),
        svg: svg || existing?.svg,
        syncRequested: undefined,
        exportFormat: existing?.exportFormat,
        exportData: existing?.exportData,
    })
    log.debug(`State updated: session=${sessionId}, version=${newVersion}`)
    return newVersion
}

export function requestSync(sessionId: string): boolean {
    const state = stateStore.get(sessionId)
    if (state) {
        state.syncRequested = Date.now()
        log.debug(`Sync requested for session=${sessionId}`)
        return true
    }
    log.debug(`Sync requested for non-existent session=${sessionId}`)
    return false
}

export async function waitForSync(
    sessionId: string,
    timeoutMs = 3000,
): Promise<boolean> {
    const start = Date.now()
    while (Date.now() - start < timeoutMs) {
        const state = stateStore.get(sessionId)
        if (!state?.syncRequested) return true
        await new Promise((r) => setTimeout(r, 100))
    }
    log.warn(`Sync timeout for session=${sessionId}`)
    return false
}

export function startHttpServer(port = 6002): Promise<number> {
    return new Promise((resolve, reject) => {
        if (server) {
            resolve(serverPort)
            return
        }

        serverPort = port
        server = http.createServer(handleRequest)

        server.on("error", (err: NodeJS.ErrnoException) => {
            if (err.code === "EADDRINUSE") {
                if (port >= MAX_PORT) {
                    reject(
                        new Error(
                            `No available ports in range 6002-${MAX_PORT}`,
                        ),
                    )
                    return
                }
                log.info(`Port ${port} in use, trying ${port + 1}`)
                server = null
                startHttpServer(port + 1)
                    .then(resolve)
                    .catch(reject)
            } else {
                reject(err)
            }
        })

        server.listen(port, process.env.HTTP_HOST || "127.0.0.1", () => {
            serverPort = port
            log.info(`HTTP server running on http://localhost:${port}`)
            resolve(port)
        })
    })
}

export function stopHttpServer(): void {
    if (server) {
        server.close()
        server = null
    }
}

function cleanupExpiredSessions(): void {
    const now = Date.now()
    for (const [sessionId, state] of stateStore) {
        if (now - state.lastUpdated.getTime() > SESSION_TTL) {
            stateStore.delete(sessionId)
            clearHistory(sessionId)
            log.info(`Cleaned up expired session: ${sessionId}`)
        }
    }
}

const cleanupIntervalId = setInterval(cleanupExpiredSessions, 5 * 60 * 1000)

export function shutdown(): void {
    clearInterval(cleanupIntervalId)
    stopHttpServer()
}

export function getServerPort(): number {
    return serverPort
}

function setCors(req: http.IncomingMessage, res: http.ServerResponse): void {
    const origin = req.headers.origin
    // Allow same-origin and Python backend (localhost)
    if (origin && /^http:\/\/localhost(:\d+)?$/.test(origin)) {
        res.setHeader("Access-Control-Allow-Origin", origin)
        res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        res.setHeader("Access-Control-Allow-Headers", "Content-Type")
    }
}

function handleRequest(
    req: http.IncomingMessage,
    res: http.ServerResponse,
): void {
    const url = new URL(req.url || "/", `http://localhost:${serverPort}`)

    setCors(req, res)

    if (req.method === "OPTIONS") {
        res.writeHead(204)
        res.end()
        return
    }

    // Raw handlers (e.g. MCP Streamable HTTP at /mcp) — checked before REST routes
    const rawHandler = rawHandlers.get(url.pathname)
    if (rawHandler) {
        Promise.resolve(rawHandler(req, res)).catch((err) => {
            if (!res.headersSent) {
                res.writeHead(500, { "Content-Type": "application/json" })
                res.end(JSON.stringify({ error: String(err) }))
            }
        })
        return
    }

    // REST API routes for Python backend
    if (url.pathname.startsWith("/api/rest/")) {
        handleRestApi(req, res, url)
        return
    }

    if (url.pathname === "/" || url.pathname === "/index.html") {
        const sessionId = url.searchParams.get("mcp") || ""

        if (!sessionId) {
            const recentSessionId = getMostRecentSessionId()
            if (recentSessionId) {
                res.writeHead(302, { Location: `/?mcp=${recentSessionId}` })
                res.end()
                return
            }
        }

        ensureSessionStateInitialized(sessionId)

        res.writeHead(200, { "Content-Type": "text/html" })
        res.end(getHtmlPage(sessionId))
    } else if (url.pathname === "/api/state") {
        handleStateApi(req, res, url)
    } else if (url.pathname === "/api/history") {
        handleHistoryApi(req, res, url)
    } else if (url.pathname === "/api/restore") {
        handleRestoreApi(req, res)
    } else if (url.pathname === "/api/history-svg") {
        handleHistorySvgApi(req, res)
    } else {
        res.writeHead(404)
        res.end("Not Found")
    }
}

function handleRestApi(
    req: http.IncomingMessage,
    res: http.ServerResponse,
    url: URL,
): void {
    // GET /api/rest/health
    if (url.pathname === "/api/rest/health" && req.method === "GET") {
        res.writeHead(200, { "Content-Type": "application/json" })
        res.end(JSON.stringify({ ok: true, version: "0.1.0" }))
        return
    }

    if (req.method !== "POST") {
        res.writeHead(405, { "Content-Type": "application/json" })
        res.end(JSON.stringify({ error: "Method not allowed" }))
        return
    }

    const routeKey = url.pathname.replace("/api/rest", "")
    const handler = restHandlers.get(routeKey)

    if (!handler) {
        res.writeHead(404, { "Content-Type": "application/json" })
        res.end(JSON.stringify({ error: `Unknown route: ${url.pathname}` }))
        return
    }

    readBody(req, res, async (body) => {
        try {
            const parsed = JSON.parse(body)
            await handler(parsed, res)
        } catch (err) {
            const msg = err instanceof Error ? err.message : String(err)
            if (!res.headersSent) {
                res.writeHead(500, { "Content-Type": "application/json" })
                res.end(JSON.stringify({ error: msg }))
            }
        }
    })
}

function handleStateApi(
    req: http.IncomingMessage,
    res: http.ServerResponse,
    url: URL,
): void {
    if (req.method === "GET") {
        const sessionId = url.searchParams.get("sessionId")
        if (!sessionId) {
            res.writeHead(400, { "Content-Type": "application/json" })
            res.end(JSON.stringify({ error: "sessionId required" }))
            return
        }
        ensureSessionStateInitialized(sessionId)
        const state = stateStore.get(sessionId)
        res.writeHead(200, { "Content-Type": "application/json" })
        res.end(
            JSON.stringify({
                xml: state?.xml || null,
                version: state?.version || 0,
                syncRequested: !!state?.syncRequested,
                exportFormat: state?.exportFormat || null,
            }),
        )
    } else if (req.method === "POST") {
        readBody(req, res, (body) => {
            try {
                const data = JSON.parse(body)
                const { sessionId } = data
                if (!sessionId) {
                    res.writeHead(400, { "Content-Type": "application/json" })
                    res.end(JSON.stringify({ error: "sessionId required" }))
                    return
                }

                if (data.exportData !== undefined) {
                    const state = stateStore.get(sessionId)
                    if (state) {
                        state.exportData = data.exportData
                        state.exportFormat = undefined
                        log.debug(
                            `Export data received for session=${sessionId}`,
                        )
                    }
                    res.writeHead(200, { "Content-Type": "application/json" })
                    res.end(JSON.stringify({ success: true }))
                    return
                }

                const version = setState(sessionId, data.xml, data.svg)
                res.writeHead(200, { "Content-Type": "application/json" })
                res.end(JSON.stringify({ success: true, version }))
            } catch {
                res.writeHead(400, { "Content-Type": "application/json" })
                res.end(JSON.stringify({ error: "Invalid JSON" }))
            }
        })
    } else {
        res.writeHead(405)
        res.end("Method Not Allowed")
    }
}

function handleHistoryApi(
    req: http.IncomingMessage,
    res: http.ServerResponse,
    url: URL,
): void {
    if (req.method !== "GET") {
        res.writeHead(405)
        res.end("Method Not Allowed")
        return
    }

    const sessionId = url.searchParams.get("sessionId")
    if (!sessionId) {
        res.writeHead(400, { "Content-Type": "application/json" })
        res.end(JSON.stringify({ error: "sessionId required" }))
        return
    }

    const history = getHistory(sessionId)
    res.writeHead(200, { "Content-Type": "application/json" })
    res.end(
        JSON.stringify({
            entries: history.map((entry, i) => ({ index: i, svg: entry.svg })),
            count: history.length,
        }),
    )
}

function handleRestoreApi(
    req: http.IncomingMessage,
    res: http.ServerResponse,
): void {
    if (req.method !== "POST") {
        res.writeHead(405)
        res.end("Method Not Allowed")
        return
    }

    readBody(req, res, (body) => {
        try {
            const { sessionId, index } = JSON.parse(body)
            if (!sessionId || index === undefined) {
                res.writeHead(400, { "Content-Type": "application/json" })
                res.end(
                    JSON.stringify({ error: "sessionId and index required" }),
                )
                return
            }

            const entry = getHistoryEntry(sessionId, index)
            if (!entry) {
                res.writeHead(404, { "Content-Type": "application/json" })
                res.end(JSON.stringify({ error: "Entry not found" }))
                return
            }

            const newVersion = setState(sessionId, entry.xml)
            addHistory(sessionId, entry.xml, entry.svg)

            log.info(`Restored session ${sessionId} to index ${index}`)

            res.writeHead(200, { "Content-Type": "application/json" })
            res.end(JSON.stringify({ success: true, newVersion }))
        } catch {
            res.writeHead(400, { "Content-Type": "application/json" })
            res.end(JSON.stringify({ error: "Invalid JSON" }))
        }
    })
}

function handleHistorySvgApi(
    req: http.IncomingMessage,
    res: http.ServerResponse,
): void {
    if (req.method !== "POST") {
        res.writeHead(405)
        res.end("Method Not Allowed")
        return
    }

    readBody(req, res, (body) => {
        try {
            const { sessionId, svg } = JSON.parse(body)
            if (!sessionId || !svg) {
                res.writeHead(400, { "Content-Type": "application/json" })
                res.end(JSON.stringify({ error: "sessionId and svg required" }))
                return
            }

            updateLastHistorySvg(sessionId, svg)
            res.writeHead(200, { "Content-Type": "application/json" })
            res.end(JSON.stringify({ success: true }))
        } catch {
            res.writeHead(400, { "Content-Type": "application/json" })
            res.end(JSON.stringify({ error: "Invalid JSON" }))
        }
    })
}

function getHtmlPage(sessionId: string): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Diagram Agent MCP</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap');
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body { width: 100%; height: 100%; overflow: hidden; }
        #container { width: 100%; height: 100%; display: flex; flex-direction: column; }
        #header {
            padding: 0 20px; height: 52px;
            background: linear-gradient(to bottom, #ffffff, #fafbfc);
            border-bottom: 1px solid #e8ecf0;
            font-family: 'DM Sans', system-ui, -apple-system, sans-serif;
            display: flex; justify-content: space-between; align-items: center;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
            position: relative; z-index: 10;
        }
        #header .brand { display: flex; align-items: center; gap: 10px; }
        #header .title { font-size: 15px; font-weight: 600; color: #1a1a2e; letter-spacing: -0.3px; }
        #header .session {
            font-size: 11px; color: #8b95a5; font-weight: 400;
            background: #f1f3f9; padding: 3px 8px; border-radius: 4px;
            margin-left: 12px; font-family: 'SF Mono', Monaco, monospace;
        }
        #header .right { display: flex; align-items: center; gap: 12px; }
        #save-btn {
            display: flex; align-items: center; gap: 6px;
            padding: 7px 14px; border-radius: 8px; font-size: 13px;
            background: linear-gradient(to bottom, #18181b, #27272a);
            color: white; border: none; cursor: pointer;
            font-weight: 500; font-family: inherit;
            box-shadow: 0 1px 2px rgba(0,0,0,0.1), inset 0 1px 0 rgba(255,255,255,0.1);
            transition: all 0.15s ease;
        }
        #save-btn:hover {
            background: linear-gradient(to bottom, #27272a, #3f3f46);
            transform: translateY(-1px);
        }
        #save-btn:active { transform: translateY(0); }
        #save-btn:disabled { background: #e5e7eb; color: #9ca3af; cursor: not-allowed; transform: none; box-shadow: none; }
        #drawio { flex: 1; border: none; }
        #save-modal {
            display: none; position: fixed; inset: 0;
            background: rgba(0,0,0,0.4); backdrop-filter: blur(4px);
            z-index: 2000; align-items: center; justify-content: center;
        }
        #save-modal.open { display: flex; }
        .modal-content {
            background: white; border-radius: 16px;
            width: 90%; max-width: 480px;
            display: flex; flex-direction: column;
            box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);
            font-family: 'DM Sans', system-ui, -apple-system, sans-serif;
        }
        .modal-header { padding: 20px 24px 16px; border-bottom: 1px solid #f1f3f5; }
        .modal-header h2 { font-size: 17px; font-weight: 600; margin: 0; color: #18181b; }
        .modal-body { padding: 20px 24px; }
        .modal-footer { padding: 16px 24px; border-top: 1px solid #f1f3f5; display: flex; gap: 10px; justify-content: flex-end; }
        .btn { padding: 9px 18px; border-radius: 8px; font-size: 13px; cursor: pointer; border: none; font-weight: 500; font-family: inherit; transition: all 0.15s ease; }
        .btn-primary { background: linear-gradient(to bottom, #18181b, #27272a); color: white; }
        .btn-primary:hover { background: linear-gradient(to bottom, #27272a, #3f3f46); }
        .btn-primary:disabled { background: #e4e4e7; color: #a1a1aa; cursor: not-allowed; }
        .btn-secondary { background: #f4f4f5; color: #3f3f46; border: 1px solid #e4e4e7; }
        .btn-secondary:hover { background: #e4e4e7; }
        .form-group { margin-bottom: 18px; }
        .form-group label { display: block; font-size: 13px; font-weight: 500; margin-bottom: 8px; color: #3f3f46; }
        .form-group select, .form-group input {
            width: 100%; padding: 10px 14px; border: 1px solid #e4e4e7;
            border-radius: 8px; font-size: 14px; outline: none; font-family: inherit; background: white;
        }
        .form-group select:focus, .form-group input:focus { border-color: #18181b; }
        .filename-group { display: flex; }
        .filename-group input { border-radius: 8px 0 0 8px; border-right: none; }
        .filename-group .ext { padding: 10px 14px; background: #f4f4f5; border: 1px solid #e4e4e7; border-radius: 0 8px 8px 0; font-size: 13px; color: #71717a; }
    </style>
</head>
<body>
    <div id="container">
        <div id="header">
            <div class="brand">
                <span class="title">Diagram Agent MCP</span>
                ${sessionId ? `<span class="session">${sessionId.slice(-8)}</span>` : ""}
            </div>
            <div class="right">
                <button id="save-btn" ${sessionId ? "" : "disabled"}>Download</button>
            </div>
        </div>
        <iframe id="drawio" src="${normalizeUrl(DRAWIO_BASE_URL)}/?embed=1&proto=json&spin=1&libraries=1&noSaveBtn=1&noExitBtn=1&saveAndExit=0"></iframe>
    </div>
    <div id="save-modal">
        <div class="modal-content">
            <div class="modal-header"><h2>Download Diagram</h2></div>
            <div class="modal-body">
                <div class="form-group">
                    <label>Format</label>
                    <select id="save-format">
                        <option value="drawio">Draw.io (.drawio)</option>
                        <option value="png">PNG Image (.png)</option>
                        <option value="svg">SVG Vector (.svg)</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Filename</label>
                    <div class="filename-group">
                        <input type="text" id="save-filename" value="diagram" placeholder="Enter filename">
                        <span class="ext" id="save-ext">.drawio</span>
                    </div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" id="save-cancel-btn">Cancel</button>
                <button class="btn btn-primary" id="save-confirm-btn">Save</button>
            </div>
        </div>
    </div>
    <script>
        const sessionId = "${sessionId}";
        const iframe = document.getElementById('drawio');
        let currentVersion = 0, isReady = false, pendingXml = null, lastXml = null;
        let pendingSvgExport = null;
        let pendingAiSvg = false;
        let pendingMcpExport = null;

        window.addEventListener('message', (e) => {
            if (e.origin !== '${DRAWIO_ORIGIN}') return;
            try {
                const msg = JSON.parse(e.data);
                if (msg.event === 'init') {
                    isReady = true;
                    if (pendingXml) { loadDiagram(pendingXml); pendingXml = null; }
                } else if ((msg.event === 'save' || msg.event === 'autosave') && msg.xml && msg.xml !== lastXml) {
                    pendingSvgExport = msg.xml;
                    iframe.contentWindow.postMessage(JSON.stringify({ action: 'export', format: 'svg' }), '*');
                    setTimeout(() => { if (pendingSvgExport === msg.xml) { pushState(msg.xml, ''); pendingSvgExport = null; } }, 2000);
                } else if (msg.event === 'export' && msg.data) {
                    if (pendingMcpExport) {
                        const d = msg.data;
                        const isPng = pendingMcpExport === 'png' && (d.startsWith('data:image/png') || (typeof d === 'string' && d.length > 100 && !d.startsWith('<')));
                        const isSvg = pendingMcpExport === 'svg' && (d.startsWith('data:image/svg') || d.startsWith('<svg'));
                        if (isPng || isSvg) {
                            pendingMcpExport = null;
                            fetch('/api/state', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ sessionId, exportData: d })
                            }).catch(() => {});
                            return;
                        }
                    }
                    if (pendingDownload && (pendingDownload.format === 'png' || pendingDownload.format === 'svg')) {
                        const dl = pendingDownload;
                        pendingDownload = null;
                        let dataUrl = msg.data;
                        if (!dataUrl.startsWith('data:')) {
                            const mime = dl.format === 'png' ? 'image/png' : 'image/svg+xml';
                            dataUrl = 'data:' + mime + ';base64,' + btoa(unescape(encodeURIComponent(msg.data)));
                        }
                        const a = document.createElement('a');
                        a.href = dataUrl; a.download = dl.filename;
                        document.body.appendChild(a); a.click(); document.body.removeChild(a);
                        saveModal.classList.remove('open');
                        saveConfirmBtn.disabled = false;
                        saveConfirmBtn.textContent = 'Save';
                        return;
                    }
                    let svg = msg.data;
                    if (!svg.startsWith('data:')) svg = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svg)));
                    if (pendingSvgExport) {
                        const xml = pendingSvgExport;
                        pendingSvgExport = null;
                        pushState(xml, svg);
                    } else if (pendingAiSvg) {
                        pendingAiSvg = false;
                        fetch('/api/history-svg', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ sessionId, svg })
                        }).catch(() => {});
                    }
                }
            } catch {}
        });

        function loadDiagram(xml, capturePreview = false) {
            if (!isReady) { pendingXml = xml; return; }
            lastXml = xml;
            iframe.contentWindow.postMessage(JSON.stringify({ action: 'load', xml, autosave: 1 }), '*');
            if (capturePreview) {
                setTimeout(() => {
                    pendingAiSvg = true;
                    iframe.contentWindow.postMessage(JSON.stringify({ action: 'export', format: 'svg' }), '*');
                }, 500);
            }
        }

        async function pushState(xml, svg = '') {
            if (!sessionId) return;
            try {
                const r = await fetch('/api/state', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sessionId, xml, svg })
                });
                if (r.ok) { const d = await r.json(); currentVersion = d.version; lastXml = xml; }
            } catch (e) { console.error('Push failed:', e); }
        }

        let pendingSyncExport = false;

        async function poll() {
            if (!sessionId) return;
            try {
                const r = await fetch('/api/state?sessionId=' + encodeURIComponent(sessionId));
                if (!r.ok) return;
                const s = await r.json();
                if (s.syncRequested && !pendingSyncExport) {
                    pendingSyncExport = true;
                    iframe.contentWindow.postMessage(JSON.stringify({ action: 'export', format: 'xml' }), '*');
                }
                if (s.version > currentVersion && s.xml) {
                    currentVersion = s.version;
                    loadDiagram(s.xml, true);
                }
                if (s.exportFormat && !pendingMcpExport && isReady) {
                    pendingMcpExport = s.exportFormat;
                    const exportOpts = s.exportFormat === 'png'
                        ? { action: 'export', format: 'png', scale: 2 }
                        : { action: 'export', format: 'svg' };
                    iframe.contentWindow.postMessage(JSON.stringify(exportOpts), '*');
                    setTimeout(() => { if (pendingMcpExport) { pendingMcpExport = null; } }, 8000);
                }
            } catch {}
        }

        if (sessionId) { poll(); setInterval(poll, 2000); }

        const saveBtn = document.getElementById('save-btn');
        const saveModal = document.getElementById('save-modal');
        const saveFormat = document.getElementById('save-format');
        const saveFilename = document.getElementById('save-filename');
        const saveExt = document.getElementById('save-ext');
        const saveCancelBtn = document.getElementById('save-cancel-btn');
        const saveConfirmBtn = document.getElementById('save-confirm-btn');
        let pendingDownload = null;

        const extMap = { drawio: '.drawio', png: '.png', svg: '.svg' };

        saveBtn.onclick = () => {
            if (!sessionId || !isReady) return;
            saveModal.classList.add('open');
            saveFilename.focus();
            saveFilename.select();
        };

        saveFormat.onchange = () => { saveExt.textContent = extMap[saveFormat.value] || '.drawio'; };
        saveCancelBtn.onclick = () => { saveModal.classList.remove('open'); };
        saveModal.onclick = (e) => { if (e.target === saveModal) saveCancelBtn.onclick(); };

        saveConfirmBtn.onclick = () => {
            const format = saveFormat.value;
            const filename = (saveFilename.value.trim() || 'diagram') + extMap[format];
            saveConfirmBtn.disabled = true;
            saveConfirmBtn.textContent = 'Exporting...';

            if (format === 'drawio') {
                let xmlData = lastXml || '';
                if (xmlData && !xmlData.includes('<mxfile')) {
                    xmlData = '<mxfile host="mcp"><diagram name="Page-1">' + xmlData + '</diagram></mxfile>';
                }
                const blob = new Blob([xmlData], { type: 'application/xml' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url; a.download = filename;
                document.body.appendChild(a); a.click(); document.body.removeChild(a);
                URL.revokeObjectURL(url);
                saveModal.classList.remove('open');
                saveConfirmBtn.disabled = false;
                saveConfirmBtn.textContent = 'Save';
            } else if (format === 'png') {
                pendingDownload = { format: 'png', filename };
                iframe.contentWindow.postMessage(JSON.stringify({ action: 'export', format: 'png', scale: 2 }), '*');
                setTimeout(() => { saveConfirmBtn.disabled = false; saveConfirmBtn.textContent = 'Save'; pendingDownload = null; }, 5000);
            } else if (format === 'svg') {
                pendingDownload = { format: 'svg', filename };
                iframe.contentWindow.postMessage(JSON.stringify({ action: 'export', format: 'svg' }), '*');
                setTimeout(() => { saveConfirmBtn.disabled = false; saveConfirmBtn.textContent = 'Save'; pendingDownload = null; }, 5000);
            }
        };
    </script>
</body>
</html>`
}
