"""Phase-based tool schema + prompt-prose filtering.

Phase is inferred from the most-advanced workspace file present, then used to
trim both the tool list (``PhaseToolFilterMiddleware``) and the system prompt's
``[[PHASE ...]]`` spans (``PhasePromptFilterMiddleware``) to what that stage
actually needs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from langchain.agents.middleware import AgentMiddleware, ModelRequest

# Same kill switch as prompts/_blocks.py's _TYPED_DIAGRAM_ENABLED (env var
# shared, not imported from there, to keep this module import-light and
# independent of the prompts package). Both must agree: this is the
# enforcement layer (blocks the tool schema itself, per AGENTS.md's "block at
# the permission/filter layer, not just the prompt"); _blocks.py just keeps
# the prompt from mentioning a tool the model can't call anyway.
_TYPED_DIAGRAM_ENABLED = os.getenv("TYPED_DIAGRAM_ENABLED", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
_TYPED_DIAGRAM_TOOLS = frozenset({"render_typed_diagram", "sql_to_erd_script"})

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
# BRD Agent: import/read/validate/gates are all reachable from "draw" onward,
# same as generate_pdf_report/propose_deck_plan below — any deliverable stage
# once a diagram exists, not gated behind strict phase progression.
_BRD_TOOLS = frozenset(
    {
        "import_brd_docx",
        "read_brd_outline",
        "validate_brd",
        "propose_brd_outline",
        "generate_brd_docx",
        "edit_brd_section",
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
        # Typed-diagram foundation: Sequence (and later ERD/State Machine) skip
        # the tech-stack/blueprint gates entirely (proposal §9) and are
        # authored code-first — render_typed_diagram must be reachable
        # straight from intake, not just the "blueprint" phase below.
        "render_typed_diagram",
        "sql_to_erd_script",
        # Solution-memory retrieval — ground the upcoming tech-stack proposal in real
        # past BnK delivery history; see rag_tools.py docstrings ("call BEFORE
        # propose_tech_stack" / "sanity-check a total estimate").
        # find_similar_solutions temporarily disabled: OpenAI embeddings key is broken,
        # so it only errors out. Re-add once the key is fixed.
        "benchmark_solution",
        # Knowledge-graph exact-overlap tools (rag/kg_store.py) — NOT subject to the
        # OpenAI-embeddings outage above, these query Postgres directly.
        "find_related_projects",
        "find_related_technologies",
        "trace_project_lineage",
    },
    "blueprint": _UTILITY_TOOLS
    | {
        "propose_tech_stack",
        "propose_blueprint",
        "render_typed_diagram",
        "sql_to_erd_script",
        "web_research",
        "propose_diagram_brief",
        "apply_compliance_pack",
        "export_adr_pack",
        "reality_sync",
        "visualize_code_structure",
        "finalize_diagram",
        "propose_business_case",
        # find_similar_solutions temporarily disabled: OpenAI embeddings key is broken.
        "benchmark_solution",
        "find_related_projects",
        "find_related_technologies",
        "trace_project_lineage",
    },
    "draw": _UTILITY_TOOLS
    | _WBS_DELIVERABLE_TOOLS
    | _BRD_TOOLS
    | {
        "finalize_diagram",
        "render_typed_diagram",
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
    | _BRD_TOOLS
    | {
        "web_research",
        "send_email",
        "propose_business_case",
        # Ad-hoc analog lookup while sizing effort — the automatic benchmark inside
        # compute_wbs_rollup (wbs_tools._benchmark_effort_totals) already runs
        # deterministically on every rollup; this lets the agent additionally query
        # a different/narrower domain on demand.
        # find_similar_solutions temporarily disabled: OpenAI embeddings key is broken.
        "benchmark_solution",
        # Task-level (not whole-project) effort benchmark + module reuse + evidence
        # drill-down — rag/kg_store.py + rag/kg_neo4j.py, see kg_tools.py.
        "benchmark_role_effort",
        "find_related_projects",
        "find_reusable_modules",
        "trace_project_lineage",
    },
    "ppt": _UTILITY_TOOLS
    | _WBS_DELIVERABLE_TOOLS
    | _BRD_TOOLS
    | {
        "propose_deck_plan",
        "generate_ppt_proposal",
        "send_email",
        "propose_business_case",
    },
    "report": _UTILITY_TOOLS
    | _WBS_DELIVERABLE_TOOLS
    | _BRD_TOOLS
    | {
        "generate_pdf_report",
        "send_email",
        "propose_business_case",
    },
    # BRD Agent: reached once out.brd.docx exists (generated or imported) or a
    # draft outline has been started — carries forward every other deliverable
    # tool so entering this phase never strands the report/wbs/ppt tools.
    "brd": _UTILITY_TOOLS
    | _WBS_DELIVERABLE_TOOLS
    | _BRD_TOOLS
    | {
        "generate_pdf_report",
        "propose_deck_plan",
        "generate_ppt_proposal",
        "send_email",
        "propose_business_case",
    },
}


# Ordered most-advanced-wins evidence chain -- same order as the original
# if-chain (test_brd_registration.py::test_brd_phase_outranks_report_phase
# pins "brd" above "report"), now data instead of code so _blocked_phases can
# skip a phase without duplicating the chain.
_PHASE_EVIDENCE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("brd", ("out.brd.docx", "brd_outline_draft.json")),
    ("report", ("out.pdf",)),
    ("ppt", ("deck_plan.json",)),
    ("wbs", ("wbs.json",)),
    ("draw", ("out.png", "blueprint.json")),
    ("blueprint", ("tech_stack.json", "architecture_analysis.json")),
)


def _blocked_phases(workspace: "Path") -> frozenset[str]:
    """Phases held back by an explicit gate rejection (session/workflow_state.py,
    MEDIUM-2). Fails open to "nothing blocked" on any error, same shape as
    _waived_artifacts above -- a broken/absent state file can never make phase
    detection worse than plain file-existence."""
    try:
        from session.workflow_state import blocked_phases

        return blocked_phases(workspace)
    except Exception:  # noqa: BLE001
        return frozenset()


def _detect_phase(workspace: "Path") -> str:
    """Infer the current workflow phase from workspace files (most-advanced wins),
    skipping any phase whose authorizing gate was explicitly REJECTED
    (session/workflow_state.py) and any evidence file that is missing or fails
    the minimum-content check (_ready) -- a partial write no longer counts as
    "stage complete" (MEDIUM-2).

    A blocked phase is skipped for ONE rung only: if a higher phase's evidence
    is independently ready (e.g. deck_plan.json already exists even though
    "draw" was just rejected), that higher phase still wins. State can only
    ever hold detection BACK relative to file evidence, never push it forward
    past what a rejection actually blocks.
    """
    blocked = _blocked_phases(workspace)
    for phase, evidence in _PHASE_EVIDENCE:
        if phase in blocked:
            continue
        if any(_ready(workspace, name) for name in evidence):
            return phase
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


def _ready(workspace: "Path", name: str) -> bool:
    """exists() + minimum-content gate (session/workflow_state.py, MEDIUM-2).

    Falls back to plain .exists() on ANY failure (missing module, corrupt
    state file, etc.), so a broken/absent session.workflow_state can never
    narrow phase detection relative to the pre-existing exists()-only
    behavior -- same fail-open shape as _stale_artifact_tools' import guard.
    """
    try:
        from session.workflow_state import artifact_ready

        return artifact_ready(workspace, name)
    except Exception:  # noqa: BLE001
        return (workspace / name).exists()


def _waived_artifacts(workspace: "Path") -> frozenset[str]:
    try:
        from session.workflow_state import waived_artifacts

        return waived_artifacts(workspace)
    except Exception:  # noqa: BLE001
        return frozenset()


def _missing_artifact_tools(workspace: "Path") -> set[str]:
    """Tool names that produce a foundational artifact currently missing (or
    present-but-empty/corrupt, see _ready) from the workspace.

    An artifact explicitly WAIVED via session/workflow_state.py::record_waiver
    is treated as intentionally absent, so its producer tool stops being
    carried into every downstream phase forever -- the one place this whole
    module narrows the allowed toolset, and only on an explicit recorded
    human decision, never as a side effect of file state.
    """
    waived = _waived_artifacts(workspace)
    return {
        tool_name
        for filename, tool_name in _ARTIFACT_BACKFILL_TOOLS.items()
        if filename not in waived and not _ready(workspace, filename)
    }


# Artifacts tracked by session/artifact_manifest.py -> their producer tool.
# Extends _ARTIFACT_BACKFILL_TOOLS with a downstream case: deck_plan.json's
# producer (propose_deck_plan) is phase-gated OUT once phase reaches "report"
# (see _PHASE_TOOLS["report"]) — if the blueprint/wbs deck_plan.json was built
# from has since changed, the model needs propose_deck_plan back to rebuild it,
# exactly the same "producer tool locked out past its phase" problem
# _missing_artifact_tools solves for a MISSING file, here for a STALE one.
_ARTIFACT_PRODUCER_TOOLS: dict[str, str] = {
    **_ARTIFACT_BACKFILL_TOOLS,
    "deck_plan.json": "propose_deck_plan",
}


def _stale_artifact_tools(workspace: "Path") -> set[str]:
    """Tool names that produce an artifact currently on disk but stale relative
    to an upstream it was derived from (session/artifact_manifest.py, H-3).

    Mirrors _missing_artifact_tools' shape exactly, for the drifted-not-missing
    case: a workspace with no artifact_manifest.json (or an artifact never
    passed through record_artifact) yields an empty set here, so this is a pure
    addition — it can never narrow the allowed toolset relative to today.
    """
    try:
        from session.artifact_manifest import is_stale
    except Exception:
        return set()
    tools: set[str] = set()
    for filename, tool_name in _ARTIFACT_PRODUCER_TOOLS.items():
        if not (workspace / filename).exists():
            continue
        stale, _drifted = is_stale(workspace, filename)
        if stale:
            tools.add(tool_name)
    return tools


def _pending_gate_tools(workspace: "Path") -> set[str]:
    """Tool names needed to revise or resume a gate already shown to the user.

    MEDIUM-1 fix: a resolved gate (status="resolved", written by
    resolve_pending_gate on resume) must stop keeping its tool artificially
    alive past its normal phase — before this check, an approved gate's tool
    stayed in the allowed set forever, because nothing on the resume path
    ever touched pending_gate.json. Absent status = pending (files written
    before this fix, or a genuinely still-open gate).
    """
    try:
        pending = json.loads((workspace / "pending_gate.json").read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(pending, dict) or pending.get("status", "pending") != "pending":
        return set()
    tool = pending.get("tool")
    return {tool} if isinstance(tool, str) and tool else set()


class PhaseToolFilterMiddleware(AgentMiddleware):
    """Filter MAIN_TOOLS down to the phase-relevant subset each call.

    Avoids sending ~34 tool schemas (~12K tok) when only 8-12 are relevant.
    Falls back to the full tool list if the workspace phase can't be determined.
    Only modifies the request.tools list; doesn't touch messages or state.
    """

    @staticmethod
    def _drop_disabled_typed_diagram(tools):
        """Strip render_typed_diagram/sql_to_erd_script when the kill switch is
        off. Applied on every return path of _filtered_tools (including the
        phase-detection-failed fallback) so a workspace/backends error can
        never re-expose these tools — the exclusion must hold unconditionally,
        not just on the happy path."""
        if _TYPED_DIAGRAM_ENABLED:
            return tools
        return [t for t in tools if _tool_name(t) not in _TYPED_DIAGRAM_TOOLS]

    def _filtered_tools(self, tools):
        try:
            from backends import current_workspace

            workspace = current_workspace()
            phase = _detect_phase(workspace)
        except Exception:
            return self._drop_disabled_typed_diagram(tools)  # safe fallback: no phase filtering
        allowed = _PHASE_TOOLS.get(phase)
        if not allowed:
            return self._drop_disabled_typed_diagram(tools)
        # Keep a foundational artifact's producing tool available even past its normal
        # phase — never let "most-advanced phase wins" permanently lock out backfilling
        # a step that got skipped (see _missing_artifact_tools).
        allowed = (
            allowed
            | _missing_artifact_tools(workspace)
            | _pending_gate_tools(workspace)
            | _stale_artifact_tools(workspace)
        )
        # Always keep built-ins (filesystem tools, task, write_todos) which don't
        # appear in _PHASE_TOOLS but are always injected by deepagents.
        allowed = allowed | _DEEP_AGENT_BUILTIN_TOOLS
        if not _TYPED_DIAGRAM_ENABLED:
            allowed = allowed - _TYPED_DIAGRAM_TOOLS
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
