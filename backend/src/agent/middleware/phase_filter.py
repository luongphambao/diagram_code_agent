"""Phase-based tool schema + prompt-prose filtering.

Phase is inferred from the most-advanced workspace file present, then used to
trim both the tool list (``PhaseToolFilterMiddleware``) and the system prompt's
``[[PHASE ...]]`` spans (``PhasePromptFilterMiddleware``) to what that stage
actually needs.
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain.agents.middleware import AgentMiddleware, ModelRequest

# Phase-based static tool filter: send only the tools relevant to the current
# stage instead of all 34 MAIN_TOOLS every call. Phase is inferred from the most
# advanced workspace file present. Falls back to all tools if undetermined.
# Utility tools (evidence, findings, comments, quality) appear in every phase.
_UTILITY_TOOLS = frozenset(
    {
        "record_evidence",
        "waive_finding",
        "resolve_finding",
        "edit_entity",
        "quality_summary",
        "compare_revisions",
        "add_comment",
        "resolve_comment",
        "query_change_impact",
        "propose_meeting_slots",
        "create_client_meeting",
        "export_to_delivery",
        "list_meeting_records",
        "get_meeting_transcript",
        "get_meeting_recordings",
        "list_meeting_participants",
    }
)
_DEEP_AGENT_BUILTIN_TOOLS = frozenset(
    {
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        "write_todos",
        "task",
    }
)
_WBS_DELIVERABLE_TOOLS = frozenset(
    {
        "propose_wbs_skeleton",
        "propose_wbs",
        "export_wbs_excel",
    }
)
_PHASE_TOOLS: dict[str, frozenset[str]] = {
    "intake": _UTILITY_TOOLS
    | {
        "analyze_architecture_requirements",
        "propose_diagram_brief",
        "web_research",
        "apply_compliance_pack",
        "reality_sync",
        "propose_tech_stack",
        "propose_blueprint",
    },
    "blueprint": _UTILITY_TOOLS
    | {
        "propose_tech_stack",
        "propose_blueprint",
        "web_research",
        "propose_diagram_brief",
        "apply_compliance_pack",
        "export_adr_pack",
        "reality_sync",
        "visualize_code_structure",
        "finalize_diagram",
        "propose_business_case",
    },
    "draw": _UTILITY_TOOLS
    | _WBS_DELIVERABLE_TOOLS
    | {
        "finalize_diagram",
        "list_saved_diagrams",
        "visualize_code_structure",
        "export_adr_pack",
        "reality_sync",
        "generate_pdf_report",
        "propose_deck_plan",
        "generate_ppt_proposal",
        "send_email",
        "propose_business_case",
    },
    "wbs": _UTILITY_TOOLS
    | _WBS_DELIVERABLE_TOOLS
    | {
        "web_research",
        "send_email",
        "propose_business_case",
    },
    "ppt": _UTILITY_TOOLS
    | _WBS_DELIVERABLE_TOOLS
    | {
        "propose_deck_plan",
        "generate_ppt_proposal",
        "send_email",
        "propose_business_case",
    },
    "report": _UTILITY_TOOLS
    | _WBS_DELIVERABLE_TOOLS
    | {
        "generate_pdf_report",
        "send_email",
        "propose_business_case",
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


# Foundational artifact -> the tool that produces it. PhaseToolFilterMiddleware uses
# "most-advanced phase wins": once wbs.json/deck_plan.json exists, phase advances to
# "wbs"/"ppt" and _PHASE_TOOLS no longer includes analyze_architecture_requirements /
# propose_diagram_brief / propose_tech_stack / propose_blueprint — so if one of these
# was skipped earlier in the session (or its file was lost), the agent can NEVER call
# the tool to backfill it again; the workspace is stuck with a permanently incomplete
# artifact set. This is the concrete cause of thin/empty decks downstream (deck
# generation reads these files/their CSM projection and finds nothing). See
# _missing_artifact_tools below — it keeps a producing tool available past its normal
# phase whenever its target file is still missing.
_ARTIFACT_BACKFILL_TOOLS: dict[str, str] = {
    "architecture_analysis.json": "analyze_architecture_requirements",
    "diagram_brief.json": "propose_diagram_brief",
    "tech_stack.json": "propose_tech_stack",
    "blueprint.json": "propose_blueprint",
}


def _missing_artifact_tools(workspace: "Path") -> set[str]:
    """Tool names that produce a foundational artifact currently missing from workspace."""
    return {
        tool_name
        for filename, tool_name in _ARTIFACT_BACKFILL_TOOLS.items()
        if not (workspace / filename).exists()
    }


def _pending_gate_tools(workspace: "Path") -> set[str]:
    """Tool names needed to revise or resume a gate already shown to the user."""
    try:
        pending = json.loads((workspace / "pending_gate.json").read_text(encoding="utf-8"))
    except Exception:
        return set()
    tool = pending.get("tool")
    return {tool} if isinstance(tool, str) and tool else set()


class PhaseToolFilterMiddleware(AgentMiddleware):
    """Filter MAIN_TOOLS down to the phase-relevant subset each call.

    Avoids sending ~34 tool schemas (~12K tok) when only 8-12 are relevant.
    Falls back to the full tool list if the workspace phase can't be determined.
    Only modifies the request.tools list; doesn't touch messages or state.
    """

    def _filtered_tools(self, tools):
        try:
            from backends import current_workspace

            workspace = current_workspace()
            phase = _detect_phase(workspace)
        except Exception:
            return tools  # safe fallback: no filtering
        allowed = _PHASE_TOOLS.get(phase)
        if not allowed:
            return tools
        # Keep a foundational artifact's producing tool available even past its normal
        # phase — never let "most-advanced phase wins" permanently lock out backfilling
        # a step that got skipped (see _missing_artifact_tools).
        allowed = allowed | _missing_artifact_tools(workspace) | _pending_gate_tools(workspace)
        # Always keep built-ins (filesystem tools, task, write_todos) which don't
        # appear in _PHASE_TOOLS but are always injected by deepagents.
        allowed = allowed | _DEEP_AGENT_BUILTIN_TOOLS
        return [t for t in tools if _tool_name(t) in allowed or not _tool_name(t)]

    async def awrap_model_call(self, request: ModelRequest, handler):
        request.tools = self._filtered_tools(request.tools)
        return await handler(request)

    def wrap_model_call(self, request: ModelRequest, handler):
        request.tools = self._filtered_tools(request.tools)
        return handler(request)


_PHASE_SPAN_RE = None  # compiled lazily (re imported locally to keep module top light)


def _strip_phase_spans(text: str, phase: str | None) -> str:
    """Strip [[PHASE a,b]]...[[/PHASE]] spans not matching *phase*.

    Marker syntax itself is always removed, so it can never leak to the model.
    With phase=None (detection failed) every span is KEPT — safe fallback.
    """
    global _PHASE_SPAN_RE
    import re

    if _PHASE_SPAN_RE is None:
        _PHASE_SPAN_RE = re.compile(r"\[\[PHASE ([a-z_,\s]+)\]\]\n?(.*?)\[\[/PHASE\]\]\n?", re.DOTALL)

    def _repl(m):
        phases = {p.strip() for p in m.group(1).split(",")}
        if phase is None or phase in phases:
            return m.group(2)
        return ""

    return _PHASE_SPAN_RE.sub(_repl, text)


class PhasePromptFilterMiddleware(AgentMiddleware):
    """Strip phase-irrelevant [[PHASE ...]] spans from the main system prompt.

    Companion to PhaseToolFilterMiddleware: that one trims tool SCHEMAS, this one
    trims the prompt PROSE (_STAGED_FLOW stages + _MAIN_TOOLS_BLOCK descriptions
    in _blocks.py) to the current workflow phase — ~2.5-3K tokens saved on every
    main model call, ~150K+ per run at main's call volume. NOTE: this makes the
    system prompt vary by phase, which is correct for non-caching providers
    (mimo); if main ever moves to a provider WITH prompt caching, disable this
    (and the tool filter) and keep the prompt byte-stable instead.
    """

    name = "PhasePromptFilterMiddleware"

    @staticmethod
    def _current_phase() -> str | None:
        try:
            from backends import current_workspace

            return _detect_phase(current_workspace())
        except Exception:
            return None

    def _filtered(self, request: ModelRequest) -> ModelRequest:
        sysmsg = getattr(request, "system_message", None)
        content = getattr(sysmsg, "content", None)
        if not isinstance(content, str) or "[[PHASE " not in content:
            return request
        new_content = _strip_phase_spans(content, self._current_phase())
        if new_content == content:
            return request
        return request.override(system_message=sysmsg.model_copy(update={"content": new_content}))

    async def awrap_model_call(self, request: ModelRequest, handler):
        return await handler(self._filtered(request))

    def wrap_model_call(self, request: ModelRequest, handler):
        return handler(self._filtered(request))
