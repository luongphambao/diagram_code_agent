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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from agent import build_agent, make_persistence
import conversations as conv_db
import session_state

from routers.chat import router as chat_router
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
            os.getenv("LANGSMITH_PROJECT"), "set" if has_key else "MISSING (set LANGSMITH_API_KEY)",
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

_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(upload_router)
app.include_router(conversations_router)


@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok", "agent": "diagram_agent"}


def main() -> None:
    port = int(os.getenv("DIAGRAM_AGENT_PORT", "8001"))
    logger.info("Starting diagram agent server on port %d", port)
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
