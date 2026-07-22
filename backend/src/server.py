"""AG-UI server for the staged diagram deep agent (port 8001).

ONE deep agent runs a staged, human-approved flow:
  understand requirements (+ uploaded docs) → propose_tech_stack [HITL] →
  propose_blueprint [HITL] → render diagram → finalize_diagram [HITL] → done.

Run:  diagram-agent-server   (or  python -m server)
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from agent import build_agent, make_persistence
from config.cors import resolve_allowed_origins
import conversations as conv_db
from health_checks import run_readiness_checks, version_info
from security.auth import AUTH_MODE
import session_state

from routers.chat import router as chat_router
from routers.comments import router as comments_router
from routers.conversations import router as conversations_router
from routers.upload import router as upload_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("diagram-agent")
for _noisy in ("httpx", "httpcore", "openai", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def _configure_tracing() -> bool:
    """Enable LangSmith tracing from env (LANGSMITH_TRACING / legacy LANGCHAIN_TRACING_V2)."""
    on = os.getenv("LANGSMITH_TRACING", os.getenv("LANGCHAIN_TRACING_V2", "")).lower() in ("1", "true", "yes")
    if on:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ.setdefault("LANGSMITH_PROJECT", "diagram-code-agent")
        has_key = bool(os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY"))
        logger.info(
            "LangSmith tracing ON  project=%s  api_key=%s",
            os.getenv("LANGSMITH_PROJECT"),
            "set" if has_key else "MISSING (set LANGSMITH_API_KEY)",
        )
    else:
        logger.info("LangSmith tracing OFF (set LANGSMITH_TRACING=true + LANGSMITH_API_KEY to enable)")
    return on


TRACING_ON = _configure_tracing()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the (Postgres) session store, build the agent, close the pool on exit."""
    checkpointer, store, aclose, pool = await make_persistence()
    session_state.AGENT = build_agent(checkpointer=checkpointer, store=store)
    app.state.aclose = aclose
    app.state.pool = pool
    await conv_db.setup(pool)
    logger.info("Agent ready.")
    try:
        yield
    finally:
        await aclose()
        logger.info("Session pool closed.")


app = FastAPI(title="Diagram Agent", version="3.0.0", lifespan=lifespan)

# --- CORS (improvement plan §0.5) -------------------------------------------
# The previous default (`ALLOWED_ORIGINS` unset -> "*") combined with
# allow_credentials=True is an open CORS policy: any origin could read
# authenticated responses. APP_ENV=production now fails CLOSED — it refuses
# to start rather than silently falling back to a wildcard — so a forgotten
# env var can never ship an open policy. Non-production keeps a small,
# explicit local-dev default (matches docker-compose.yml's frontend origin)
# instead of "*", so dev behavior matches prod's allowlist model.
_APP_ENV = os.getenv("APP_ENV", "development")
_origins = resolve_allowed_origins(_APP_ENV, os.getenv("ALLOWED_ORIGINS", ""))
if not os.getenv("ALLOWED_ORIGINS", "").strip():
    logger.warning(
        "ALLOWED_ORIGINS not set — defaulting to local-dev origins %s (APP_ENV=%s). "
        "Set ALLOWED_ORIGINS explicitly for any non-dev deployment.",
        _origins,
        _APP_ENV,
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# --- Auth (improvement plan §0.6) -------------------------------------------
# Importing security.auth above already evaluated AUTH_MODE and raised
# AuthConfigError if APP_ENV=production picked an insecure mode (see
# resolve_auth_mode) — this just makes the effective posture visible at
# startup, mirroring the CORS warning above.
logger.info(
    "Auth mode: %s%s",
    AUTH_MODE,
    " (DEV FALLBACK — trusts client-supplied userEmail/userRole; refused in APP_ENV=production)"
    if AUTH_MODE == "none"
    else "",
)


@app.middleware("http")
async def _security_headers(request, call_next):
    """Baseline security headers (improvement plan §0.5) — cheap, broadly
    applicable defenses that cost nothing for a JSON/SSE API with no
    same-origin HTML rendering of user content."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


app.include_router(chat_router)
app.include_router(upload_router)
app.include_router(conversations_router)
app.include_router(comments_router)


@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok", "agent": "diagram_agent"}


@app.get("/health/live", tags=["ops"])
def health_live():
    """Liveness: the process is up and serving requests. No dependency checks —
    a slow/degraded dependency belongs in /health/ready, not in a liveness
    probe (which typically triggers a container restart on failure — restarting
    a healthy process because Postgres is briefly slow would make things worse,
    not better)."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["ops"])
async def health_ready(request: Request):
    """Readiness: can THIS instance actually serve a request right now?
    Checks Postgres and Modal auth/App lookup (improvement plan §1.5) — a load
    balancer or orchestrator should stop routing traffic here on a non-200."""
    ok, checks = await run_readiness_checks(request.app.state.pool)
    status_code = 200 if ok else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ok" if ok else "degraded", "checks": checks},
    )


@app.get("/version", tags=["ops"])
def version():
    return version_info(app_version=app.version, auth_mode=AUTH_MODE)


def main() -> None:
    port = int(os.getenv("DIAGRAM_AGENT_PORT", "8001"))
    logger.info("Starting diagram agent server on port %d", port)
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
