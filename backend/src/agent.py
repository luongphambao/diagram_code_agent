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

import asyncio
import logging
import os
import json
from typing import Any

from deepagents import create_deep_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.messages import ToolMessage as LCToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.store.memory import InMemoryStore

from backends import (
    LOCAL_ICONS,
    LOCAL_MANIFEST,
    MEMORY_PATH,
    SKILLS_DIR,
    WORKSPACE,
    make_local_backend,
)
from prompts import (
    build_critic_prompt,
    build_drawer_prompt,
    build_icon_resolver_prompt,
    build_ppt_generator_prompt,
    build_pretty_system_prompt,
    build_system_prompt,
    build_wbs_planner_prompt,
)
from context import SessionContext
from tools import (
    CRITIC_TOOLS, DRAWER_TOOLS, GATE_TOOL_NAMES, ICON_RESOLVER_TOOLS, MAIN_TOOLS,
    PPT_GENERATOR_TOOLS, WBS_PLANNER_TOOLS,
)

logger = logging.getLogger(__name__)

_IMAGE_TOOLS = frozenset({"render_diagram", "inspect_diagram"})
_USAGE_FILE = None  # set lazily after WORKSPACE is imported


class KeepLatestImagesEdit:
    """Strip image blocks from all render/inspect ToolMessages except the most recent.

    count_tokens_approximately counts images as a flat 85 tokens regardless of size,
    so image accumulation is invisible to ClearToolUsesEdit.  This edit removes the
    base64 payload from every image-bearing ToolMessage except the last one, replacing
    each image block with a lightweight sentinel.  Runs unconditionally (no token
    threshold) so it applies on every model call.
    """

    _STRIPPED = {"type": "text", "text": "[image cleared — see latest render]"}

    def apply(self, messages: list[AnyMessage], *, count_tokens: Any) -> None:
        image_indices: list[int] = []
        for i, msg in enumerate(messages):
            if not isinstance(msg, LCToolMessage):
                continue
            if getattr(msg, "name", None) not in _IMAGE_TOOLS:
                continue
            content = msg.content
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "image" for b in content
            ):
                image_indices.append(i)

        # Keep the last one; strip the rest.
        for idx in image_indices[:-1]:
            msg = messages[idx]
            old = msg.content if isinstance(msg.content, list) else [msg.content]
            new_content = [
                self._STRIPPED if (isinstance(b, dict) and b.get("type") == "image") else b
                for b in old
            ]
            messages[idx] = msg.model_copy(update={"content": new_content})


class InjectVisionAsUserEdit:
    """Relay PNG images from tool messages into a follow-up user message.

    Some providers (e.g. mimo-v2.5) reject image blocks in tool messages with
    400: 'text' is not set, even though they accept images in user messages.
    This edit strips image blocks from render_diagram/inspect_diagram ToolMessages
    and injects a synthetic HumanMessage immediately after each one, so the model
    can still see the rendered PNG via the user-message path.

    Old relay messages (marked with _SENTINEL) are removed on every apply() call
    before new ones are injected, so only the latest image is live in context.
    KeepLatestImagesEdit is a no-op after this edit because ToolMessages no longer
    carry images.
    """

    _SENTINEL = "[VISION_RELAY]"

    def apply(self, messages: list[AnyMessage], *, count_tokens: Any) -> None:
        # Remove previously injected relay messages.
        i = 0
        while i < len(messages):
            msg = messages[i]
            if isinstance(msg, HumanMessage):
                c = msg.content
                is_relay = (
                    (isinstance(c, str) and c.startswith(self._SENTINEL))
                    or (
                        isinstance(c, list)
                        and any(
                            isinstance(b, dict) and str(b.get("text", "")).startswith(self._SENTINEL)
                            for b in c
                        )
                    )
                )
                if is_relay:
                    messages.pop(i)
                    continue
            i += 1

        # Strip images from ToolMessages and inject relay HumanMessages.
        # Iterate in reverse so insert() indices stay valid.
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if not isinstance(msg, LCToolMessage):
                continue
            if getattr(msg, "name", None) not in _IMAGE_TOOLS:
                continue
            content = msg.content
            if not isinstance(content, list):
                continue

            image_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "image"]
            if not image_blocks:
                continue

            # Strip image blocks from ToolMessage, keep text.
            text_only = [b for b in content if not (isinstance(b, dict) and b.get("type") == "image")]
            messages[i] = msg.model_copy(update={"content": text_only or "[rendered]"})

            # Build relay HumanMessage with image_url blocks (user-message format).
            relay_content: list = [{"type": "text", "text": self._SENTINEL + " Rendered diagram image:"}]
            for block in image_blocks:
                b64 = block.get("base64", "")
                mime = block.get("mime_type", "image/png")
                relay_content.append({
                    "type": "image_url",
                    "text": "[image]",  # mimo requires a non-empty text on every content block
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                })
            messages.insert(i + 1, HumanMessage(content=relay_content))


class UsageLoggingMiddleware(AgentMiddleware):
    """Append per-model-call token usage to WORKSPACE/usage.json.

    Reads ``usage_metadata`` from the first AIMessage in the response and appends
    a record to usage.json so we can observe token spend per agent over time.
    """

    def __init__(self, agent_name: str) -> None:
        self._agent_name = agent_name

    def _log(self, usage: dict) -> None:
        try:
            from backends import current_workspace  # avoid circular at module load

            path = current_workspace() / "usage.json"
            try:
                records: list = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            except Exception:
                records = []
            records.append({"agent": self._agent_name, **usage})
            path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        except Exception:
            logger.debug("UsageLoggingMiddleware: failed to write usage.json", exc_info=True)

    def _extract_usage(self, response: ModelResponse) -> dict | None:
        for msg in response.result or []:
            if isinstance(msg, AIMessage) and msg.usage_metadata:
                m = msg.usage_metadata
                return {
                    "input_tokens": m.get("input_tokens", 0),
                    "output_tokens": m.get("output_tokens", 0),
                    "total_tokens": m.get("total_tokens", 0),
                }
        return None

    async def awrap_model_call(self, request: ModelRequest, handler):
        response: ModelResponse = await handler(request)
        usage = self._extract_usage(response)
        if usage:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._log, usage)
        return response

    def wrap_model_call(self, request: ModelRequest, handler):
        response: ModelResponse = handler(request)
        usage = self._extract_usage(response)
        if usage:
            self._log(usage)
        return response


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
                "style": bp.get("presentation_style", "diagram"),
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
REASONING_EFFORT = "medium"          # used as fallback when no config.yaml present

MAIN_SKILL_PATHS = [
    str(SKILLS_DIR / "diagrams-as-code"),
    str(SKILLS_DIR / "pro-style"),
]
DRAWER_SKILL_PATHS = [
    str(SKILLS_DIR / "drawer" / "diagrams-as-code"),
    str(SKILLS_DIR / "drawer" / "pro-style"),
]
WBS_PLANNER_SKILL_PATHS = [
    str(SKILLS_DIR / "wbs-planning"),
]
PPT_GENERATOR_SKILL_PATHS = [
    str(SKILLS_DIR / "ppt-generator"),
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

# Per-run model-call caps: after this many model calls in one run the agent
# exits cleanly ("Model call limits exceeded") instead of looping forever.
# Each agent (main / drawer / critic) is a SEPARATE run with its own budget.
# A clean drawer pass needs ~12-18 calls; the budget is headroom, and runaway
# loops are bounded earlier by the render budget (tools.RENDER_HARD_CAP) and
# the icon-search budget — hitting these caps means something is wrong, so we
# stop spending. Override via env for experiments.
_RUN_CALL_LIMIT = int(os.getenv("RUN_CALL_LIMIT", "120"))         # main + drawer
_CRITIC_CALL_LIMIT = int(os.getenv("CRITIC_CALL_LIMIT", "40"))    # inspect+critique only

# Per-stage (per-subagent) model-call budgets (§4.10 "per-stage budget"). Each
# subagent is a separate run with its own ceiling so a single stage can't burn
# the whole session; tune independently via env without touching the others.
# Token/cost per stage is recorded separately by UsageLoggingMiddleware → usage.json
# (keyed by agent_name), which the quality dashboard reads for spend-to-quality.
_ICON_CALL_LIMIT = int(os.getenv("ICON_CALL_LIMIT", str(_CRITIC_CALL_LIMIT)))
_DRAWER_CALL_LIMIT = int(os.getenv("DRAWER_CALL_LIMIT", str(_RUN_CALL_LIMIT)))
_WBS_CALL_LIMIT = int(os.getenv("WBS_CALL_LIMIT", str(_RUN_CALL_LIMIT)))
_PPT_CALL_LIMIT = int(os.getenv("PPT_CALL_LIMIT", "60"))


def _middleware(run_limit: int = _RUN_CALL_LIMIT, *, agent_name: str = "agent",
                use_vision_relay: bool = False):
    from config import vision_in_tools as _vision_in_tools
    edits: list = []
    if use_vision_relay:
        edits.append(InjectVisionAsUserEdit())
    edits += [
        KeepLatestImagesEdit(),
        ClearToolUsesEdit(
            trigger=CONTEXT_TRIGGER_TOKENS,
            clear_at_least=8_000,
            keep=8,
            clear_tool_inputs=True,
            exclude_tools=GATE_TOOL_NAMES,
        ),
    ]
    layers = [
        ContextEditingMiddleware(
            edits=edits,
            token_count_method="approximate",
        ),
        UsageLoggingMiddleware(agent_name),
        ModelCallLimitMiddleware(run_limit=run_limit, exit_behavior="end"),
    ]
    # Optional model fallback: set FALLBACK_MODEL env var to activate.
    # Format: "provider:model-name" e.g. "anthropic:claude-sonnet-4-5-20250929"
    fallback = os.getenv("FALLBACK_MODEL", "").strip()
    if fallback:
        layers.append(ModelFallbackMiddleware(fallback))
        logger.info("ModelFallbackMiddleware active  fallback=%s", fallback)
    return layers


def _make_llm(model: str):
    from config import make_llm as _cfg_make_llm
    return _cfg_make_llm(model)


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


def _icon_resolver_subagent(workdir: str, icons_root: str, manifest: str) -> dict:
    """Config for the icon_resolver subagent: batch node/icon resolution before drawing."""
    return {
        "name": "icon_resolver",
        "description": (
            "Resolves all icon paths and built-in node class names for the approved "
            "blueprint. Reads render_spec.json, calls search_diagrams_nodes + "
            "resolve_icons in batch, writes icon_plan.json. Returns a short status."
        ),
        "system_prompt": build_icon_resolver_prompt(workdir, icons_root, manifest),
        "tools": ICON_RESOLVER_TOOLS,
    }


def _drawer_subagent(workdir: str, icons_root: str, manifest: str, style: str) -> dict:
    """Config for the drawer subagent: render-refine loop + export (icons pre-resolved)."""
    return {
        "name": "drawer",
        "description": (
            "Renders the approved architecture blueprint into a production-quality "
            "diagram. Reads pre-resolved icon_plan.json, writes diagram code, "
            "render-refine loop (≤3), and drawio export. Returns ONLY a short text "
            "status — no images."
        ),
        "system_prompt": build_drawer_prompt(workdir, icons_root, manifest, style=style),
        "tools": DRAWER_TOOLS,
        "skills": DRAWER_SKILL_PATHS,
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


def _ppt_generator_subagent(workdir: str) -> dict:
    """Config for the ppt_generator subagent: read workspace context + write out.pptx."""
    return {
        "name": "ppt_generator",
        "description": (
            "Reads approved workspace artifacts (blueprint.json, diagram_brief.json, "
            "tech_stack.json, out.png) and generates out.pptx using the BnK proposal "
            "template.  Called BEFORE the generate_ppt_proposal gate so the main agent "
            "can pass rich defaults (title, subtitle, brand, sections) to the user. "
            "Returns a short status."
        ),
        "system_prompt": build_ppt_generator_prompt(workdir),
        "tools": PPT_GENERATOR_TOOLS,
        "skills": PPT_GENERATOR_SKILL_PATHS,
    }


def _wbs_planner_subagent(workdir: str) -> dict:
    """Config for the wbs_planner subagent: decompose + estimate the WBS.

    Reads the approved brief/tech_stack/blueprint, breaks the solution into a
    BnK-format WBS (phases→modules→features), estimates dev effort (BA/QC/PM are
    derived), plans timeline/team/milestones and writes wbs.json. The gate tools
    (propose_wbs_skeleton / propose_wbs / export_wbs_excel) live on the MAIN agent.
    """
    return {
        "name": "wbs_planner",
        "description": (
            "Builds a BnK-format Work Breakdown Structure from the approved solution. "
            "Reads diagram_brief.json + tech_stack.json + blueprint.json, drafts the "
            "phase/module skeleton, estimates dev effort per feature (BA/QC/PM derived), "
            "rolls up totals, plans the timeline/team/milestones, validates, and writes "
            "wbs.json / wbs_skeleton.json. Returns a short status — the MAIN agent runs "
            "the propose/export gates."
        ),
        "system_prompt": build_wbs_planner_prompt(workdir),
        "tools": WBS_PLANNER_TOOLS,
        "skills": WBS_PLANNER_SKILL_PATHS,
    }


def build_agent(model: str | None = None, *, style: str = DEFAULT_STYLE,
                checkpointer=None, store=None):
    """Create the diagram deep agent (a compiled LangGraph graph).

    Pass ``checkpointer``/``store`` from :func:`make_persistence` for durable
    sessions; if omitted, an in-memory checkpointer is used (dev only).

    Subagents (icon_resolver, drawer, critic) are pre-compiled as
    ``CompiledSubAgent`` TypedDicts so deepagents uses our
    ``_StreamingSubAgentRunnable`` wrapper as-is.  This lets each subagent's
    internal tool calls stream through the outer graph's ``"custom"`` mode and
    appear as live ACTIVITY events.

    *model* overrides the 'main' role in config.yaml; icon_resolver/drawer/critic
    always come from config.yaml (falling back to the resolved main model).
    """
    from config import get_model, get_system_prompt_prefix

    main_model           = model or get_model("main",          DEFAULT_MODEL)
    icon_resolver_model  = get_model("icon_resolver",   main_model)
    drawer_model         = get_model("drawer",           main_model)
    critic_model         = get_model("critic",           main_model)
    wbs_planner_model    = get_model("wbs_planner",      main_model)
    ppt_generator_model  = get_model("ppt_generator",    main_model)

    workdir = str(WORKSPACE)
    prefix = get_system_prompt_prefix(main_model)
    if style == "pretty":
        system_prompt = prefix + build_pretty_system_prompt(workdir, LOCAL_ICONS, LOCAL_MANIFEST)
    else:
        system_prompt = prefix + build_system_prompt(workdir, LOCAL_ICONS, LOCAL_MANIFEST)

    icon_resolver_prefix  = get_system_prompt_prefix(icon_resolver_model)
    drawer_prefix         = get_system_prompt_prefix(drawer_model)
    critic_prefix         = get_system_prompt_prefix(critic_model)
    wbs_planner_prefix    = get_system_prompt_prefix(wbs_planner_model)
    ppt_generator_prefix  = get_system_prompt_prefix(ppt_generator_model)

    if not os.getenv("TAVILY_API_KEY"):
        logger.warning(
            "TAVILY_API_KEY not set — web_research tool will return NO_API_KEY. "
            "Set TAVILY_API_KEY in .env to enable live tech-stack fact-checking."
        )

    logger.info(
        "build_agent  main=%s  icon_resolver=%s  drawer=%s  critic=%s  style=%s",
        main_model, icon_resolver_model, drawer_model, critic_model, style,
    )

    from config import vision_in_tools as _vision_in_tools
    drawer_vision_in_tools = _vision_in_tools(drawer_model)
    # vision_relay: provider can see images in user messages but not tool messages.
    # Enable RENDER_INCLUDES_IMAGE so tools still return PNG data; InjectVisionAsUserEdit
    # will move the image from the ToolMessage into a synthetic HumanMessage.
    drawer_vision_relay = not drawer_vision_in_tools
    if drawer_vision_relay:
        os.environ["RENDER_INCLUDES_IMAGE"] = "1"
        logger.info(
            "Vision relay enabled for drawer model %s (images relayed via user message)",
            drawer_model,
        )
    else:
        os.environ.setdefault("RENDER_INCLUDES_IMAGE", "1")

    llm                 = _make_llm(main_model)
    icon_resolver_llm   = _make_llm(icon_resolver_model)
    drawer_llm          = _make_llm(drawer_model)
    critic_llm          = _make_llm(critic_model)
    wbs_planner_llm     = _make_llm(wbs_planner_model)
    ppt_generator_llm   = _make_llm(ppt_generator_model)
    backend = make_local_backend()

    # Pre-compile subagents so their internal steps are visible in the outer stream.
    icon_resolver_spec  = _icon_resolver_subagent(workdir, LOCAL_ICONS, LOCAL_MANIFEST)
    drawer_spec         = _drawer_subagent(workdir, LOCAL_ICONS, LOCAL_MANIFEST, style)
    critic_spec         = _critic_subagent(style)
    wbs_planner_spec    = _wbs_planner_subagent(workdir)
    ppt_generator_spec  = _ppt_generator_subagent(workdir)
    icon_resolver_spec["system_prompt"] = icon_resolver_prefix + icon_resolver_spec["system_prompt"]
    drawer_spec["system_prompt"]        = drawer_prefix + drawer_spec["system_prompt"]
    critic_spec["system_prompt"]        = critic_prefix + critic_spec["system_prompt"]
    wbs_planner_spec["system_prompt"]   = wbs_planner_prefix + wbs_planner_spec["system_prompt"]
    ppt_generator_spec["system_prompt"] = ppt_generator_prefix + ppt_generator_spec["system_prompt"]

    icon_resolver_compiled: dict = {
        "name": icon_resolver_spec["name"],
        "description": icon_resolver_spec["description"],
        "runnable": _StreamingSubAgentRunnable(
            create_deep_agent(
                model=icon_resolver_llm,
                tools=icon_resolver_spec["tools"],
                system_prompt=icon_resolver_spec["system_prompt"],
                backend=backend,
                memory=[MEMORY_PATH],
                middleware=_middleware(run_limit=_ICON_CALL_LIMIT, agent_name="icon_resolver"),
                store=store,
            ),
            "icon_resolver",
        ),
    }
    drawer_compiled: dict = {
        "name": drawer_spec["name"],
        "description": drawer_spec["description"],
        "runnable": _StreamingSubAgentRunnable(
            create_deep_agent(
                model=drawer_llm,
                tools=drawer_spec["tools"],
                system_prompt=drawer_spec["system_prompt"],
                backend=backend,
                memory=[MEMORY_PATH],
                skills=drawer_spec.get("skills"),
                middleware=_middleware(run_limit=_DRAWER_CALL_LIMIT, agent_name="drawer",
                                     use_vision_relay=drawer_vision_relay),
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
                model=critic_llm,
                tools=critic_spec["tools"],
                system_prompt=critic_spec["system_prompt"],
                backend=backend,
                memory=[MEMORY_PATH],
                middleware=_middleware(run_limit=_CRITIC_CALL_LIMIT, agent_name="critic",
                                     use_vision_relay=drawer_vision_relay),
                store=store,
            ),
            "critic",
        ),
    }
    wbs_planner_compiled: dict = {
        "name": wbs_planner_spec["name"],
        "description": wbs_planner_spec["description"],
        "runnable": _StreamingSubAgentRunnable(
            create_deep_agent(
                model=wbs_planner_llm,
                tools=wbs_planner_spec["tools"],
                system_prompt=wbs_planner_spec["system_prompt"],
                backend=backend,
                memory=[MEMORY_PATH],
                skills=wbs_planner_spec.get("skills"),
                middleware=_middleware(run_limit=_WBS_CALL_LIMIT, agent_name="wbs_planner"),
                store=store,
            ),
            "wbs_planner",
        ),
    }
    ppt_generator_compiled: dict = {
        "name": ppt_generator_spec["name"],
        "description": ppt_generator_spec["description"],
        "runnable": _StreamingSubAgentRunnable(
            create_deep_agent(
                model=ppt_generator_llm,
                tools=ppt_generator_spec["tools"],
                system_prompt=ppt_generator_spec["system_prompt"],
                backend=backend,
                memory=[MEMORY_PATH],
                skills=ppt_generator_spec.get("skills"),
                middleware=_middleware(run_limit=_PPT_CALL_LIMIT, agent_name="ppt_generator"),
                store=store,
            ),
            "ppt_generator",
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
        skills=MAIN_SKILL_PATHS,
        subagents=[
            icon_resolver_compiled, drawer_compiled, critic_compiled,
            wbs_planner_compiled, ppt_generator_compiled,
        ],
        middleware=_middleware(agent_name="main"),
        checkpointer=checkpointer,
        store=store,
        interrupt_on=interrupt_on,
        # Per-session config (credentials, account ids, user email) reaches the
        # gate tools via runtime.context instead of the prompt; see context.py.
        context_schema=SessionContext,
    )
