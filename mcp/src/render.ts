/**
 * Headless render of mxGraph XML → PNG
 *
 * Strategy (tried in order):
 *  1. drawio desktop CLI  (`drawio --export …`)
 *  2. Playwright headless browser loading embed.diagrams.net
 *
 * The Python backend calls `POST /api/rest/render` which invokes renderToPng().
 */

import { execFile } from "node:child_process"
import { writeFile, readFile, unlink, mkdtemp, rm } from "node:fs/promises"
import { join } from "node:path"
import { tmpdir } from "node:os"
import { log } from "./logger.js"

// Wrap mxGraphModel XML in mxfile envelope if missing
function ensureMxFile(xml: string): string {
    const trimmed = xml.trim()
    if (trimmed.startsWith("<mxfile")) return trimmed
    if (trimmed.startsWith("<mxGraphModel")) {
        return `<mxfile host="mcp"><diagram name="Page-1">${trimmed}</diagram></mxfile>`
    }
    return trimmed
}

// ── 1. drawio desktop CLI ────────────────────────────────────────────────────

async function renderWithCli(xml: string): Promise<Buffer> {
    const tmpDir = await mkdtemp(join(tmpdir(), "drawio-render-"))
    const inputPath = join(tmpDir, "input.drawio")
    const outputPath = join(tmpDir, "output.png")

    await writeFile(inputPath, ensureMxFile(xml), "utf-8")

    await new Promise<void>((resolve, reject) => {
        execFile(
            "drawio",
            [
                "--export",
                "--format",
                "png",
                "--output",
                outputPath,
                "--no-sandbox",
                inputPath,
            ],
            { timeout: 30_000 },
            (err) => (err ? reject(err) : resolve()),
        )
    })

    const buf = await readFile(outputPath)
    await rm(tmpDir, { recursive: true, force: true }).catch(() => {})
    return buf
}

// ── 2. Playwright headless browser ──────────────────────────────────────────

// Playwright is an optional dependency — import dynamically to avoid hard crash.
async function renderWithPlaywright(xml: string): Promise<Buffer> {
    // Dynamic import so missing playwright doesn't break startup.
    let chromium: typeof import("playwright").chromium
    try {
        const pw = await import("playwright")
        chromium = pw.chromium
    } catch {
        throw new Error(
            "Playwright not installed. Run: npm install playwright && npx playwright install chromium",
        )
    }

    const drawioEmbedUrl = process.env.DRAWIO_BASE_URL || "https://embed.diagrams.net"
    const mxfileXml = ensureMxFile(xml)

    const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] })
    try {
        const page = await browser.newPage()
        await page.setViewportSize({ width: 1200, height: 900 })

        // Navigate to draw.io embed
        await page.goto(`${drawioEmbedUrl}/?embed=1&proto=json&spin=1`, {
            waitUntil: "networkidle",
            timeout: 30_000,
        })

        // Wait for draw.io iframe to signal init
        const pngBase64 = await page.evaluate(
            async (xmlPayload: string): Promise<string> => {
                return await new Promise<string>((resolve, reject) => {
                    const timeout = setTimeout(
                        () => reject(new Error("draw.io export timeout")),
                        20_000,
                    )

                    window.addEventListener("message", function handler(e) {
                        try {
                            const msg = JSON.parse(e.data as string)
                            if (msg.event === "init") {
                                // Load diagram
                                ;(e.source as Window).postMessage(
                                    JSON.stringify({ action: "load", xml: xmlPayload, autosave: 0 }),
                                    "*",
                                )
                            } else if (msg.event === "load") {
                                // Request PNG export
                                ;(e.source as Window).postMessage(
                                    JSON.stringify({ action: "export", format: "png", scale: 2 }),
                                    "*",
                                )
                            } else if (msg.event === "export" && msg.data) {
                                clearTimeout(timeout)
                                window.removeEventListener("message", handler)
                                resolve(msg.data as string)
                            }
                        } catch {}
                    })
                })
            },
            mxfileXml,
        )

        // pngBase64 is a data URI: "data:image/png;base64,..."
        const base64 = (pngBase64 as string).replace(/^data:image\/png;base64,/, "")
        return Buffer.from(base64, "base64")
    } finally {
        await browser.close()
    }
}

// ── Public API ───────────────────────────────────────────────────────────────

export async function renderToPng(xml: string): Promise<Buffer> {
    // Try drawio CLI first
    try {
        const buf = await renderWithCli(xml)
        log.info("renderToPng: used drawio CLI")
        return buf
    } catch (cliErr) {
        const msg = cliErr instanceof Error ? cliErr.message : String(cliErr)
        log.warn(`renderToPng: drawio CLI failed (${msg}), trying Playwright…`)
    }

    // Fall back to Playwright
    const buf = await renderWithPlaywright(xml)
    log.info("renderToPng: used Playwright headless")
    return buf
}
