"""The diagram deep agent — a single `create_deep_agent` with tools + memory.

Design: **deep agent + tools + memory**, no shell.
  - backend : FilesystemBackend (workspace) + a `/memories/` route  (see backends.py)
  - tools   : render_diagram / export_drawio / search_icons / fetch_logo  (see tools.py)
  - memory  : /memories/AGENTS.md   (persistent learnings, loaded at startup)
  - skills  : diagrams-as-code, pro-style   (on-demand know-how)

The agent writes `diagrams` code, calls `render_diagram` to run it and LOOK at the
PNG, refines, then `export_drawio`. The server (`server.py`) streams this agent and
surfaces the produced out.png / out.drawio / diagram.py to the frontend.
"""

from __future__ import annotations

import logging
import os
import json

from deepagents import create_deep_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
)
from langchain_core.messages import AIMessage
from langchain_core.messages import ToolMessage as LCToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.store.memory import InMemoryStore

from .backends import (
    LOCAL_ICONS,
    LOCAL_MANIFEST,
    MEMORY_PATH,
    SKILLS_DIR,
    WORKSPACE,
    make_local_backend,
)
from .prompts import (
    build_critic_prompt,
    build_drawer_prompt,
    build_pretty_system_prompt,
    build_system_prompt,
)
from .tools import CRITIC_TOOLS, DRAWER_TOOLS, GATE_TOOL_NAMES, MAIN_TOOLS

logger = logging.getLogger(__name__)


def _compact_tool_args(args: dict | None, *, limit: int = 260) -> str:
    """Human-readable one-line summary of tool args for live UI activity."""
    if not isinstance(args, dict) or not args:
        return ""
    safe = dict(args)
    if "code" in safe:
        code = str(safe["code"])
        safe["code"] = f"{len(code)} chars"
    if "blueprint" in safe:
        bp = safe["blueprint"] or {}
        if isinstance(bp, dict):
            safe["blueprint"] = {
                "pattern": bp.get("pattern"),
                "nodes": len(bp.get("nodes") or []),
                "clusters": len(bp.get("clusters") or []),
                "edges": len(bp.get("edges") or []),
            }
    if "description" in safe:
        desc = " ".join(str(safe["description"]).split())
        safe["description"] = desc[:180] + ("..." if len(desc) > 180 else "")
    if "icons" in safe and isinstance(safe["icons"], list):
        labels = [
            str(x.get("label", ""))
            for x in safe["icons"]
            if isinstance(x, dict) and x.get("label")
        ]
        safe["icons"] = f"{len(safe['icons'])} icons: {', '.join(labels[:8])}"
    try:
        text = json.dumps(safe, ensure_ascii=False)
    except Exception:
        text = str(safe)
    return text[:limit] + ("..." if len(text) > limit else "")


def _compact_tool_output(content, *, limit: int = 320) -> str:
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                if "text" in p:
                    parts.append(str(p.get("text") or ""))
                elif p.get("type") == "image":
                    parts.append("[image preview]")
        text = " ".join(parts)
    else:
        text = ""
    text = " ".join(text.split())
    return text[:limit] + ("..." if len(text) > limit else "")


class _StreamingSubAgentRunnable:
    """Wraps a compiled subagent graph so its per-step tool calls surface in the
    outer LangGraph stream.

    deepagents calls ``compiled["runnable"].with_config(...).ainvoke(state, cfg)``
    for every ``task(...)`` call.  We intercept ``ainvoke``, run ``astream``
    internally, and write each tool-call / tool-result event to the outer stream
    via ``get_stream_writer()``.  The server handles these as ``"custom"`` mode
    events and re-emits them as live ACTIVITY SSE events.

    ``get_stream_writer()`` is captured **before** we enter the inner astream
    (LangGraph sets a new context-var value for the inner graph), so we always
    write to the *outer* stream.  If we are not inside a streaming context
    (tests, headless eval) the writer is ``None`` and we fall back silently.
    """

    def __init__(self, runnable, name: str) -> None:
        self._runnable = runnable
        self._name = name

    def with_config(self, config=None, **kwargs):
        return _StreamingSubAgentRunnable(
            self._runnable.with_config(config or {}, **kwargs), self._name
        )

    async def ainvoke(self, state, config=None, **kwargs):
        # Capture the outer stream writer once, before entering the inner astream.
        try:
            writer = get_stream_writer()
        except Exception:
            writer = None

        final_values = None
        try:
            async for mode, data in self._runnable.astream(
                state, config, stream_mode=["updates", "values"], **kwargs
            ):
                if mode == "values":
                    final_values = data
                elif mode == "updates" and writer is not None:
                    for _node, upd in (data or {}).items():
                        if not isinstance(upd, dict):
                            continue
                        for msg in upd.get("messages", []) or []:
                            if isinstance(msg, AIMessage):
                                for tc in (msg.tool_calls or []):
                                    writer({
                                        "subagent": self._name,
                                        "phase": "start",
                                        "tool": tc.get("name", "tool"),
                                        "detail": _compact_tool_args(tc.get("args")),
                                    })
                            elif isinstance(msg, LCToolMessage):
                                writer({
                                    "subagent": self._name,
                                    "phase": "end",
                                    "tool": getattr(msg, "name", "tool"),
                                    "ok": getattr(msg, "status", None) != "error",
                                    "detail": _compact_tool_output(getattr(msg, "content", "")),
                                })
        except Exception:
            # Streaming failed (version mismatch, wrong context, etc.) — fall back
            # to a plain invoke so the task still completes.
            logger.warning(
                "subagent %s streaming failed, falling back to ainvoke", self._name,
                exc_info=True,
            )
            return await self._runnable.ainvoke(state, config, **kwargs) or {}

        return final_values or {}


DEFAULT_MODEL    = "gpt-5.4-mini"
DEFAULT_STYLE    = "pretty"          # "pretty" (prettygraph) or "plain" (raw diagrams)
RECURSION_LIMIT  = 160               # max agent steps per run (used by the server)
REASONING_EFFORT = "medium"

SKILL_PATHS = [
    str(SKILLS_DIR / "diagrams-as-code"),
    str(SKILLS_DIR / "pro-style"),
]

# Context-management: the conversation is re-sent every turn, so stale tool
# outputs (read_file of skill docs, repeated search_icons, old render images)
# dominate cost. ClearToolUsesEdit replaces old tool results with "[cleared]"
# once a turn's (approximate) tokens exceed the trigger, keeping the most recent
# few intact. It runs locally (no LLM) and preserves tool_call/result pairs, so
# HITL gates and resume are unaffected. We clear aggressively (clear_at_least is
# huge → drop every clearable old result, keep only the recent ones) because the
# agent re-reads anything it still needs from disk. (deepagents already bundles a
# SummarizationMiddleware as the long-run safety net.)
CONTEXT_TRIGGER_TOKENS = 30_000   # main context is lean (no images/icons), can be higher

# Critic/refine sub-loop cap: after this many model calls in one run the agent
# exits cleanly instead of looping forever. Sized to allow full staged flow plus
# 2 critic+refine rounds with headroom (tech_stack → blueprint → drawer → critic
# → revise → critic → finalize ≈ ~30 calls for a complex diagram).
_RUN_CALL_LIMIT = 80


def _middleware():
    layers = [
        ContextEditingMiddleware(
            edits=[
                ClearToolUsesEdit(
                    trigger=CONTEXT_TRIGGER_TOKENS,
                    clear_at_least=1_000_000,
                    keep=6,
                    clear_tool_inputs=False,
                )
            ],
            token_count_method="approximate",
        ),
        ModelCallLimitMiddleware(run_limit=_RUN_CALL_LIMIT, exit_behavior="end"),
    ]
    # Optional model fallback: set FALLBACK_MODEL env var to activate.
    # Format: "provider:model-name" e.g. "anthropic:claude-sonnet-4-5-20250929"
    fallback = os.getenv("FALLBACK_MODEL", "").strip()
    if fallback:
        layers.append(ModelFallbackMiddleware(fallback))
        logger.info("ModelFallbackMiddleware active  fallback=%s", fallback)
    return layers


def _make_llm(model: str):
    # timeout + max_retries: basic resilience against slow/transient model errors.
    m = model.lower()
    if m.startswith("claude") or m.startswith("anthropic"):
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, max_tokens=16000, temperature=0,
                             timeout=90, max_retries=6)
    return ChatOpenAI(model=model, reasoning_effort=REASONING_EFFORT,
                      use_responses_api=True, timeout=90, max_retries=6)


async def make_persistence():
    """Build session persistence: ``(checkpointer, store, aclose, pool)``.

    Sessions (conversation/thread state + HITL interrupts) are checkpointed so a
    thread survives a server restart. With ``DATABASE_URL`` set we use Postgres
    (durable, the production path); without it we fall back to in-memory (dev only,
    lost on restart). ``aclose`` is an async callable to close the pool on shutdown.
    ``pool`` is the raw AsyncConnectionPool (or None in dev mode) — exposed so the
    server can reuse it for the conversations metadata table.
    """
    db = os.getenv("DATABASE_URL", "").strip()
    if not db:
        logger.warning("DATABASE_URL not set — using IN-MEMORY sessions (NOT durable; dev only).")

        async def _noop():
            return None

        return MemorySaver(), InMemoryStore(), _noop, None

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.store.postgres.aio import AsyncPostgresStore
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(
        conninfo=db, max_size=20, open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()          # idempotent: creates tables on first run
    store = AsyncPostgresStore(pool)
    await store.setup()
    logger.info("Postgres session persistence ready (checkpointer + store).")

    async def _aclose():
        await pool.close()

    return checkpointer, store, _aclose, pool


def _drawer_subagent(workdir: str, icons_root: str, manifest: str, style: str) -> dict:
    """Config for the drawer subagent: owns icon search + render-refine + export."""
    return {
        "name": "drawer",
        "description": (
            "Renders the approved architecture blueprint into a production-quality "
            "diagram. Handles icon search, diagram code, render-refine loop (≤3), "
            "and drawio export. Returns ONLY a short text status — no images."
        ),
        "system_prompt": build_drawer_prompt(workdir, icons_root, manifest, style=style),
        "tools": DRAWER_TOOLS,
        "skills": SKILL_PATHS,
    }


def _critic_subagent(style: str) -> dict:
    """Config for the critic subagent: read-only review of the rendered diagram."""
    return {
        "name": "critic",
        "description": (
            "Reviews the rendered diagram against the approved blueprint. Looks at "
            "out.png itself (no image reaches the caller's context) and returns a "
            "VERDICT: PASS / REVISE line with a small set of concrete findings. "
            "Does NOT edit code or re-render."
        ),
        "system_prompt": build_critic_prompt(style=style),
        "tools": CRITIC_TOOLS,
    }


def build_agent(model: str = DEFAULT_MODEL, *, style: str = DEFAULT_STYLE,
                checkpointer=None, store=None):
    """Create the diagram deep agent (a compiled LangGraph graph).

    Pass ``checkpointer``/``store`` from :func:`make_persistence` for durable
    sessions; if omitted, an in-memory checkpointer is used (dev only).

    Subagents (drawer, critic) are pre-compiled as ``CompiledSubAgent`` TypedDicts
    so deepagents uses our ``_StreamingSubAgentRunnable`` wrapper as-is.  This lets
    each subagent's internal tool calls (render_diagram, search_icons, …) stream
    through the outer graph's ``"custom"`` mode and appear as live ACTIVITY events.
    """
    workdir = str(WORKSPACE)
    if style == "pretty":
        system_prompt = build_pretty_system_prompt(workdir, LOCAL_ICONS, LOCAL_MANIFEST)
    else:
        system_prompt = build_system_prompt(workdir, LOCAL_ICONS, LOCAL_MANIFEST)

    logger.info("build_agent  model=%s  style=%s", model, style)

    llm = _make_llm(model)
    backend = make_local_backend()

    # Pre-compile subagents so their internal steps are visible in the outer stream.
    # Each task still gets an ephemeral thread, but both subagents load the shared
    # semantic memory file so learned icon/import/style notes survive delegations.
    drawer_spec = _drawer_subagent(workdir, LOCAL_ICONS, LOCAL_MANIFEST, style)
    critic_spec = _critic_subagent(style)

    drawer_compiled: dict = {
        "name": drawer_spec["name"],
        "description": drawer_spec["description"],
        "runnable": _StreamingSubAgentRunnable(
            create_deep_agent(
                model=llm,
                tools=drawer_spec["tools"],
                system_prompt=drawer_spec["system_prompt"],
                backend=backend,
                memory=[MEMORY_PATH],
                skills=drawer_spec.get("skills"),
                middleware=_middleware(),
                store=store,
            ),
            "drawer",
        ),
    }
    critic_compiled: dict = {
        "name": critic_spec["name"],
        "description": critic_spec["description"],
        "runnable": _StreamingSubAgentRunnable(
            create_deep_agent(
                model=llm,
                tools=critic_spec["tools"],
                system_prompt=critic_spec["system_prompt"],
                backend=backend,
                memory=[MEMORY_PATH],
                middleware=_middleware(),
                store=store,
            ),
            "critic",
        ),
    }

    # Each gate tool pauses for human review/approval before it runs.
    interrupt_on = {
        name: {"allowed_decisions": ["approve", "reject"]}
        for name in GATE_TOOL_NAMES
    }
    if checkpointer is None:
        checkpointer = MemorySaver()
    return create_deep_agent(
        model=llm,
        tools=MAIN_TOOLS,
        system_prompt=system_prompt,
        backend=backend,
        memory=[MEMORY_PATH],
        skills=SKILL_PATHS,
        subagents=[drawer_compiled, critic_compiled],
        middleware=_middleware(),
        checkpointer=checkpointer,
        store=store,
        interrupt_on=interrupt_on,
    )
