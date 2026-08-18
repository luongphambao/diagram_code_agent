"""Three spike routes mounted via langgraph.json's `http.app`, each testing one
undocumented-but-load-bearing assumption for the real migration (see
plans/*cicd*.md Phase 0):

- GET  /spike/health  -> quick liveness check
- GET  /spike/sse     -> does a long-lived custom SSE route survive Cloud's
                         proxy layer without being buffered/killed early?
                         Emits one event/second for 60s with a monotonic
                         counter + timestamp so the client can detect gaps,
                         reordering, or "arrived all at once" (= buffered).
- POST /spike/upload  -> does multipart/form-data reach a custom route intact?
                         Echoes filename/size/sha256 so the client can verify
                         byte-for-byte fidelity against what it sent.
- GET  /spike/render  -> does graphviz (`dot`) + Playwright Chromium run
                         inside the container's 2 vCPU / 2GB RAM budget?
                         Reports elapsed time and output size for both so a
                         near-OOM or near-timeout shows up as a number, not
                         just a binary pass/fail.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import time

from fastapi import FastAPI, UploadFile
from fastapi.responses import StreamingResponse

app = FastAPI(title="langgraph-platform-spike")

SSE_TICKS = 60
SSE_INTERVAL_S = 1.0


@app.get("/spike/health")
def health() -> dict:
    return {"ok": True}


@app.get("/spike/sse")
async def spike_sse() -> StreamingResponse:
    async def gen():
        start = time.monotonic()
        for i in range(SSE_TICKS):
            event = {
                "type": "TICK",
                "i": i,
                "elapsed_s": round(time.monotonic() - start, 3),
            }
            yield f"data: {json.dumps(event)}\n\n"
            await asyncio.sleep(SSE_INTERVAL_S)
        yield f"data: {json.dumps({'type': 'DONE', 'total_s': round(time.monotonic() - start, 3)})}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/spike/upload")
async def spike_upload(file: UploadFile) -> dict:
    content = await file.read()
    return {
        "filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


@app.get("/spike/render")
async def spike_render() -> dict:
    result: dict = {}

    t0 = time.monotonic()
    try:
        # subprocess.run is a blocking syscall — running it directly inside an
        # async route trips LangGraph dev's blocking-call detector (confirmed
        # locally: "Blocking call to os.read"), and would tie up the ASGI
        # event loop for everyone on Cloud. This is the same pattern the real
        # render_exec.py uses for graphviz, so the fix belongs there too.
        proc = await asyncio.to_thread(
            subprocess.run, ["dot", "-V"], capture_output=True, text=True, timeout=10
        )
        result["graphviz"] = {
            "ok": True,
            # graphviz prints version to stderr, not stdout
            "version": (proc.stderr or proc.stdout).strip(),
            "elapsed_s": round(time.monotonic() - t0, 3),
        }
    except Exception as exc:  # noqa: BLE001 — report to caller, not just logs
        result["graphviz"] = {"ok": False, "error": str(exc)}

    t0 = time.monotonic()
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content("<h1>langgraph-platform-spike</h1>")
            pdf_bytes = await page.pdf()
            await browser.close()
        result["playwright"] = {
            "ok": True,
            "pdf_bytes": len(pdf_bytes),
            "elapsed_s": round(time.monotonic() - t0, 3),
        }
    except Exception as exc:  # noqa: BLE001
        result["playwright"] = {
            "ok": False,
            "error": str(exc),
            "elapsed_s": round(time.monotonic() - t0, 3),
        }

    return result
