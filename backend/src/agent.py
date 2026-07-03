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
    LLMToolSelectorMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallLimitMiddleware,
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
    before new ones are injected — belt-and-suspenders cleanup; in practice edits
    are ephemeral (re-applied to a fresh copy of persisted history on every model
    call, never written back), so a prior call's relay message is never actually
    present here.

    Depends on KeepLatestImagesEdit running FIRST in _middleware()'s edits list:
    that edit trims the persisted ToolMessage history down to a single live image
    before this edit runs, so this edit only ever finds and relays that one image.
    If this edit ran first instead, it would relay every historical render/inspect
    image on every call (unbounded payload growth). Do not reorder without
    updating this note.
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


_OFFLOAD_GATE_TOOLS = frozenset({"propose_blueprint", "propose_tech_stack"})


class OffloadGateArgsEdit:
    """Replace large gate-tool call args with a pointer once the gate is resolved.

    propose_blueprint/propose_tech_stack receive the full Blueprint/tech_stack as
    *tool-call arguments* (not a return value — both tools only return a short
    confirmation string). Both are in GATE_TOOL_NAMES, so ClearToolUsesEdit's
    `exclude_tools=GATE_TOOL_NAMES` exempts them from clearing forever (needed so
    an interrupted gate stays resumable) — meaning this ~3-9K token blob rides
    along in every subsequent model call for the rest of the run even though
    nothing ever re-reads it (drawer/critic/icon_resolver all read
    render_spec.json/blueprint.json/tech_stack.json from disk instead).

    This edit only rewrites the transient request-local copy of `tool_calls[i].args`
    (it runs inside ContextEditingMiddleware like KeepLatestImagesEdit, so it never
    touches the persisted LangGraph checkpoint state — session_state.py's activity-log
    reconstruction reads that checkpoint directly and is unaffected). It only offloads
    once a ToolMessage is already paired with the call (i.e. the gate was approved and
    the run moved on), so a still-pending/interrupted gate is never touched.
    """

    _NOTE = "[cleared — full content persisted to disk, already applied]"

    def apply(self, messages: list[AnyMessage], *, count_tokens: Any) -> None:
        resolved_ids = {
            getattr(m, "tool_call_id", None)
            for m in messages
            if isinstance(m, LCToolMessage)
        }
        for i, msg in enumerate(messages):
            if not isinstance(msg, AIMessage) or not msg.tool_calls:
                continue
            new_calls = []
            changed = False
            for tc in msg.tool_calls:
                if (
                    tc.get("name") in _OFFLOAD_GATE_TOOLS
                    and tc.get("id") in resolved_ids
                    and tc.get("args")
                ):
                    tc = {**tc, "args": {"_offloaded": self._NOTE}}
                    changed = True
                new_calls.append(tc)
            if changed:
                messages[i] = msg.model_copy(update={"tool_calls": new_calls})


def _warn_missing_text_blocks(agent_name: str, messages: list[AnyMessage]) -> None:
    """Log any outgoing content block lacking a non-empty "text" key.

    mimo rejects requests containing a content block with no (or empty) "text"
    field (see InjectVisionAsUserEdit) — this is a diagnostic-only check (no
    behavior change) so a recurrence pinpoints the exact offending message
    instead of requiring another from-scratch investigation. Callers gate this
    to mimo-backed agents only.
    """
    for i, msg in enumerate(messages):
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and not block.get("text"):
                logger.warning(
                    "agent %s: outgoing message block missing non-empty text — "
                    "msg_idx=%d msg_type=%s block_type=%s",
                    agent_name, i, type(msg).__name__, block.get("type"),
                )


class UsageLoggingMiddleware(AgentMiddleware):
    """Append per-model-call token usage to WORKSPACE/usage.json.

    Reads ``usage_metadata`` from the first AIMessage in the response and appends
    a record to usage.json so we can observe token spend per agent over time.
    """

    def __init__(self, agent_name: str, *, check_missing_text: bool = False) -> None:
        self._agent_name = agent_name
        self._call_count = 0
        self._check_missing_text = check_missing_text

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
        if self._check_missing_text:
            _warn_missing_text_blocks(self._agent_name, request.messages)
        response: ModelResponse = await handler(request)
        usage = self._extract_usage(response)
        if usage:
            self._call_count += 1
            if self._call_count > _WARN_CALL_COUNT:
                logger.warning(
                    "agent %s: %d model calls (threshold=%d) — potential runaway loop",
                    self._agent_name, self._call_count, _WARN_CALL_COUNT,
                )
            if usage["input_tokens"] > _WARN_INPUT_TOKENS:
                logger.warning(
                    "agent %s: input context=%d tok (threshold=%d) — approaching limit",
                    self._agent_name, usage["input_tokens"], _WARN_INPUT_TOKENS,
                )
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._log, usage)
        return response

    def wrap_model_call(self, request: ModelRequest, handler):
        if self._check_missing_text:
            _warn_missing_text_blocks(self._agent_name, request.messages)
        response: ModelResponse = handler(request)
        usage = self._extract_usage(response)
        if usage:
            self._call_count += 1
            if self._call_count > _WARN_CALL_COUNT:
                logger.warning(
                    "agent %s: %d model calls (threshold=%d) — potential runaway loop",
                    self._agent_name, self._call_count, _WARN_CALL_COUNT,
                )
            if usage["input_tokens"] > _WARN_INPUT_TOKENS:
                logger.warning(
                    "agent %s: input context=%d tok (threshold=%d) — approaching limit",
                    self._agent_name, usage["input_tokens"], _WARN_INPUT_TOKENS,
                )
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
# A clean drawer pass needs ~12-18 calls (prompt budget: "≤15 model calls").
# The render/icon-search per-tool budgets (tools.RENDER_HARD_CAP etc.) don't
# cover every drawer tool (audit_diagram_code, export_drawio, plan_style_sizes,
# fit_labels are uncapped), so the model-call ceiling is the real backstop for
# a stuck drawer — keep it comfortably above the intended budget, not 8x looser.
# Override via env for experiments.
_RUN_CALL_LIMIT = int(os.getenv("RUN_CALL_LIMIT", "120"))         # main only
_CRITIC_CALL_LIMIT = int(os.getenv("CRITIC_CALL_LIMIT", "40"))    # inspect+critique only

# Per-stage (per-subagent) model-call budgets (§4.10 "per-stage budget"). Each
# subagent is a separate run with its own ceiling so a single stage can't burn
# the whole session; tune independently via env without touching the others.
# Token/cost per stage is recorded separately by UsageLoggingMiddleware → usage.json
# (keyed by agent_name), which the quality dashboard reads for spend-to-quality.
_ICON_CALL_LIMIT = int(os.getenv("ICON_CALL_LIMIT", str(_CRITIC_CALL_LIMIT)))
_DRAWER_CALL_LIMIT = int(os.getenv("DRAWER_CALL_LIMIT", "40"))    # ~2.5x the ≤15-call budget
_WBS_CALL_LIMIT = int(os.getenv("WBS_CALL_LIMIT", str(_RUN_CALL_LIMIT)))
_PPT_CALL_LIMIT = int(os.getenv("PPT_CALL_LIMIT", "60"))

# Early-warning thresholds: log at WARNING level so runaway traces surface in
# logs before they show up in LangSmith. Both are env-tunable.
_WARN_CALL_COUNT   = int(os.getenv("WARN_CALL_COUNT", "30"))
_WARN_INPUT_TOKENS = int(os.getenv("WARN_INPUT_TOKENS", "80000"))


# Main agent has ~42 tool schemas every call (34 MAIN_TOOLS + 6 filesystem
# built-ins + write_todos + task). LLMToolSelectorMiddleware trims that down via
# one small extra selection call — only worth it for the main agent; subagents
# already have narrow (2-9 tool) tool sets where the selector call would cost
# more than it saves. Env-gated so it can be turned off without a code change if
# usage.json shows it isn't paying for itself, or the selector excludes a tool
# the model actually needed.
_MAIN_TOOL_SELECTOR = os.getenv("MAIN_TOOL_SELECTOR", "1").strip().lower() not in ("0", "false", "no")
_MAIN_TOOL_SELECTOR_ALWAYS_INCLUDE = [
    "read_file", "ls", "glob", "grep", "task", "write_todos", "finalize_diagram",
]

# Phase-based static tool filter: send only the tools relevant to the current
# stage instead of all 34 MAIN_TOOLS every call. Phase is inferred from the most
# advanced workspace file present. Falls back to all tools if undetermined.
# Utility tools (evidence, findings, comments, quality) appear in every phase.
_UTILITY_TOOLS = frozenset({
    "record_evidence", "waive_finding", "resolve_finding", "edit_entity",
    "quality_summary", "compare_revisions", "add_comment", "resolve_comment",
    "query_change_impact", "propose_meeting_slots", "create_client_meeting",
    "export_to_delivery",
})
_PHASE_TOOLS: dict[str, frozenset[str]] = {
    "intake": _UTILITY_TOOLS | {
        "analyze_architecture_requirements", "propose_diagram_brief",
        "web_research", "apply_compliance_pack", "reality_sync",
        "propose_tech_stack", "propose_blueprint",
    },
    "blueprint": _UTILITY_TOOLS | {
        "propose_tech_stack", "propose_blueprint", "web_research",
        "propose_diagram_brief", "apply_compliance_pack",
        "export_adr_pack", "reality_sync", "visualize_code_structure",
        "finalize_diagram",
    },
    "draw": _UTILITY_TOOLS | {
        "finalize_diagram", "list_saved_diagrams", "visualize_code_structure",
        "export_adr_pack", "reality_sync",
        "generate_pdf_report", "propose_deck_plan", "generate_ppt_proposal",
        "send_email",
    },
    "wbs": _UTILITY_TOOLS | {
        "propose_wbs_skeleton", "propose_wbs", "export_wbs_excel",
        "web_research",
    },
    "ppt": _UTILITY_TOOLS | {
        "propose_deck_plan", "generate_ppt_proposal",
        "send_email",
    },
    "report": _UTILITY_TOOLS | {
        "generate_pdf_report", "send_email",
    },
}


def _detect_phase(workspace: "Path") -> str:
    """Infer the current workflow phase from workspace files (most-advanced wins)."""
    if (workspace / "out.pdf").exists():
        return "report"
    if (workspace / "deck_plan.json").exists():
        return "ppt"
    if (workspace / "wbs.json").exists():
        return "wbs"
    if (workspace / "out.png").exists() or (workspace / "blueprint.json").exists():
        return "draw"
    if (workspace / "tech_stack.json").exists() or (workspace / "architecture_analysis.json").exists():
        return "blueprint"
    return "intake"


def _tool_name(tool) -> str:
    """Return the name of a tool (BaseTool or schema dict)."""
    if isinstance(tool, dict):
        return tool.get("name", "")
    return getattr(tool, "name", "")


class PhaseToolFilterMiddleware(AgentMiddleware):
    """Filter MAIN_TOOLS down to the phase-relevant subset each call.

    Avoids sending ~34 tool schemas (~12K tok) when only 8-12 are relevant.
    Falls back to the full tool list if the workspace phase can't be determined.
    Only modifies the request.tools list; doesn't touch messages or state.
    """

    def _filtered_tools(self, tools):
        try:
            from backends import current_workspace
            phase = _detect_phase(current_workspace())
        except Exception:
            return tools  # safe fallback: no filtering
        allowed = _PHASE_TOOLS.get(phase)
        if not allowed:
            return tools
        # Always keep built-ins (filesystem tools, task, write_todos) which don't
        # appear in _PHASE_TOOLS but are always injected by deepagents.
        return [t for t in tools if _tool_name(t) in allowed or not _tool_name(t)]

    async def awrap_model_call(self, request: ModelRequest, handler):
        request.tools = self._filtered_tools(request.tools)
        return await handler(request)

    def wrap_model_call(self, request: ModelRequest, handler):
        request.tools = self._filtered_tools(request.tools)
        return handler(request)


def _middleware(run_limit: int = _RUN_CALL_LIMIT, *, agent_name: str = "agent",
                model: str | None = None,
                use_vision_relay: bool = False,
                use_tool_selector: bool = False,
                use_phase_filter: bool = False,
                task_call_limit: int | None = None):
    from config import resolve_provider as _resolve_provider
    exclude = GATE_TOOL_NAMES
    # KeepLatestImagesEdit MUST run before InjectVisionAsUserEdit: it reduces
    # the ToolMessage history down to a single live image before the relay
    # edit scans for images to relay. See InjectVisionAsUserEdit's docstring.
    edits: list = [KeepLatestImagesEdit()]
    if use_vision_relay:
        edits.append(InjectVisionAsUserEdit())
    edits += [
        OffloadGateArgsEdit(),
        ClearToolUsesEdit(
            trigger=CONTEXT_TRIGGER_TOKENS,
            clear_at_least=8_000,
            keep=4,
            clear_tool_inputs=True,
            exclude_tools=exclude,
        ),
    ]
    layers = [
        ContextEditingMiddleware(
            edits=edits,
            token_count_method="approximate",
        ),
        UsageLoggingMiddleware(
            agent_name,
            check_missing_text=bool(model) and _resolve_provider(model)[0] == "mimo",
        ),
        ModelCallLimitMiddleware(run_limit=run_limit, exit_behavior="end"),
    ]
    if task_call_limit is not None:
        # Defense-in-depth against subagent-dispatch storms: caps `task` calls
        # per run. exit_behavior="continue" (not "end") — "end" raises
        # NotImplementedError when parallel tool calls are pending.
        layers.append(ToolCallLimitMiddleware(
            tool_name="task", run_limit=task_call_limit, exit_behavior="continue",
        ))
    if use_phase_filter:
        layers.append(PhaseToolFilterMiddleware())
    if use_tool_selector and _MAIN_TOOL_SELECTOR:
        layers.append(LLMToolSelectorMiddleware(
            max_tools=20,
            always_include=_MAIN_TOOL_SELECTOR_ALWAYS_INCLUDE,
        ))
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


def _register_tuned_summarization_profiles() -> None:
    """Tune deepagents' bundled SummarizationMiddleware for the models we use.

    create_deep_agent() always adds a SummarizationMiddleware safety net
    (compute_summarization_defaults). Every model we use (mimo-v2.5, gpt-5.4-mini)
    is built via ChatOpenAI (config.make_llm) — including mimo, which is an
    OpenAI-compatible endpoint reached through ChatOpenAI with a custom base_url —
    so `model.profile` is empty for both and the fallback branch kicks in:
    trigger=("tokens", 170_000), keep=("messages", 6). Since ClearToolUsesEdit
    (this module, CONTEXT_TRIGGER_TOKENS=30_000) already keeps the working set
    well under 170K tokens, that fallback almost never fires — it isn't the
    "long-run safety net" the module comment above assumes, just dead weight.
    Register a profile so it actually engages as a backstop once ClearToolUsesEdit
    alone isn't enough (e.g. a stuck drawer render-refine loop), well above
    CONTEXT_TRIGGER_TOKENS so it doesn't fire on every normal run.

    HarnessProfile keys are `provider:identifier`, where the provider comes from
    the *LangChain class*'s `_get_ls_params()["ls_provider"]` — for ChatOpenAI
    this is always "openai", regardless of a custom base_url — so both roles key
    under "openai:<model-name>", not "mimo:<model-name>".
    """
    from deepagents import HarnessProfile, register_harness_profile
    from deepagents.middleware.summarization import SummarizationMiddleware

    def _tuned_summarizer(model_str: str):
        def factory():
            return [SummarizationMiddleware(
                model=_make_llm(model_str),
                backend=make_local_backend(),
                trigger=("tokens", 60_000),
                keep=("messages", 12),
            )]
        return factory

    for model_str in ("mimo-v2.5", "gpt-5.4-mini"):
        register_harness_profile(f"openai:{model_str}", HarnessProfile(
            excluded_middleware={"SummarizationMiddleware"},
            extra_middleware=_tuned_summarizer(model_str),
        ))


_register_tuned_summarization_profiles()


def _set_general_purpose_enabled(enabled: bool, model_strs: set[str]) -> None:
    """Toggle deepagents' auto-added "general-purpose" subagent per model key.

    create_deep_agent() silently adds a "general-purpose" subagent (plus the
    SubAgentMiddleware `task` tool) to every agent that doesn't already define
    one. For worker subagents (icon_resolver/drawer/critic/ppt_generator) that
    tool is an unintended escape hatch: a failed render once led the drawer to
    retry via task(general-purpose) three times, each a stateless nested agent
    with no call limit — 1.66M tokens (42%) of a single 4M-token run.

    Harness profiles are keyed per provider:model and the registry is
    process-global, so per-agent behavior requires toggling around each
    create_deep_agent call in build_agent (profiles are read at build time,
    and register_harness_profile merges field-wise with incoming values
    winning). build_agent runs once at server startup, so the toggling is not
    a concurrency concern.
    """
    from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile
    for model_str in model_strs:
        register_harness_profile(f"openai:{model_str}", HarnessProfile(
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=enabled),
        ))


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
    from config import get_model, get_system_prompt_prefix, supports_structured_output

    main_model           = model or get_model("main",          DEFAULT_MODEL)
    # LLMToolSelectorMiddleware calls main_model.with_structured_output() to pick
    # tools; only enable it when the provider actually supports that (mimo does
    # not — see config.supports_structured_output). Still AND-gated by the
    # MAIN_TOOL_SELECTOR env flag inside _middleware().
    _selector_ok         = supports_structured_output(main_model)
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

    # wbs_planner is built FIRST, with the auto-added general-purpose subagent
    # left enabled (its behavior is intentionally unchanged). Every agent built
    # after the False toggle — icon_resolver/drawer/critic/ppt_generator and the
    # main agent — gets no implicit general-purpose subagent: workers lose the
    # unintended `task` escape hatch entirely, and main keeps `task` only for
    # its five named subagents. See _set_general_purpose_enabled.
    _set_general_purpose_enabled(True, {wbs_planner_model})
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
                middleware=_middleware(run_limit=_WBS_CALL_LIMIT, agent_name="wbs_planner",
                                     model=wbs_planner_model),
                store=store,
            ),
            "wbs_planner",
        ),
    }
    _set_general_purpose_enabled(False, {
        icon_resolver_model, drawer_model, critic_model, ppt_generator_model, main_model,
    })
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
                middleware=_middleware(run_limit=_ICON_CALL_LIMIT, agent_name="icon_resolver",
                                     model=icon_resolver_model),
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
                                     model=drawer_model, use_vision_relay=drawer_vision_relay),
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
                                     model=critic_model, use_vision_relay=drawer_vision_relay),
                store=store,
            ),
            "critic",
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
                middleware=_middleware(run_limit=_PPT_CALL_LIMIT, agent_name="ppt_generator",
                                     model=ppt_generator_model),
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
        middleware=_middleware(agent_name="main", model=main_model, use_tool_selector=_selector_ok,
                               use_phase_filter=True),
        checkpointer=checkpointer,
        store=store,
        interrupt_on=interrupt_on,
        # Per-session config (credentials, account ids, user email) reaches the
        # gate tools via runtime.context instead of the prompt; see context.py.
        context_schema=SessionContext,
    )
