"""Tools package for the diagram deep agent.

This package replaces the original tools.py monolith. All symbols are re-exported
here for backward compatibility — existing code doing:

    from .tools import render_diagram, DIAGRAM_TOOLS, ...

continues to work without modification.
"""

from __future__ import annotations

# --- constants & stage file paths ---
from .constants import (
    CRITIC_REVISION_HARD_CAP,
    ICON_SEARCH_DEFAULT_TOTAL_CAP,
    ICON_SEARCH_PER_QUERY_CAP,
    INSPECT_MAX_WIDTH,
    NODE_SINGLE_SEARCH_HARD_CAP,
    NODE_SINGLE_SEARCH_WARN,
    RENDER_HARD_CAP,
    RENDER_SOFT_CAP,
    RENDER_TIMEOUT_S,
    TAVILY_SEARCH_URL,
    WEB_SEARCH_SESSION_CAP,
    _ARCH_ANALYSIS_FILE,
    _BLUEPRINT_FILE,
    _BRIEF_FILE,
    _CRITIQUE_FILE,
    _ICON_PLAN_FILE,
    _ICON_SEARCH_BUDGET_FILE,
    _NODE_SEARCH_BUDGET_FILE,
    _OUT_NAMES,
    _PRETTYGRAPH_PKG_DIR,
    _RENDER_COUNT_FILE,
    _RENDER_SPEC_FILE,
    _REVISION_COUNT_FILE,
    _SESSION_ARTIFACTS,
    _TECHSTACK_FILE,
    _TOOL_SUMMARY_FILE,
    _WEB_SEARCH_BUDGET_FILE,
)

# --- stage markers & helpers ---
from .stage_markers import (
    _archive_session,
    _bump_render_count,
    _bump_tool_summary,
    _icon_search_state,
    _inspection_image_b64,
    _layout_audit,
    _node_search_state,
    _read_json_file,
    _reset_revision_count,
    _reset_round_budgets,
    _save_icon_search_state,
    _save_node_search_state,
    _save_web_search_state,
    _stage_helpers,
    _web_search_state,
    _write_json_file,
    clear_stage_markers,
    reset_render_count,
    _render_count,
)

# --- icon / node search tools ---
from .icon_tools import (
    IconRequest,
    _icon_key,
    _icon_rel,
    _icon_search_total_cap,
    _node_search_hits,
    _search_icon_hits,
    _tokens,
    fetch_logo,
    resolve_icons,
    search_diagrams_nodes,
    search_drawio_shapes,
    search_icons,
)

# --- rendering tools ---
from .rendering_tools import (
    GridSection,
    NodeText,
    _VENDOR_PREFIXES,
    _WORD_ABBREVS,
    _audit_add,
    _shorten,
    audit_diagram_code,
    declare_poster_grid,
    export_drawio,
    finalize_diagram,
    fit_labels,
    list_saved_diagrams,
    plan_style_sizes,
    render_diagram,
    visualize_code_structure,
)

# --- analysis / HITL tools + Pydantic models ---
from .analysis_tools import (
    BPCluster,
    BPEdge,
    BPNode,
    Blueprint,
    CoercingModel,
    CostRange,
    DataAssumptions,
    DiagramBrief,
    LegendEntry,
    NFRMapping,
    PdfReportConfig,
    PillarCoverage,
    ProposeTechStackArgs,
    PptProposalConfig,
    ScalingPhase,
    SolutionAssumptions,
    TechAlternative,
    TechChoice,
    TechCriteria,
    TechRisk,
    TeamAssumptions,
    UserScaleAssumptions,
    WAFPillar,
    _build_render_spec,
    _detect_provider,
    _mimo_coerce_before,
    _preseed_icon_plan,
    _req_soft_match,
    _validate_nfr_mapping,
    _validate_pillar_coverage,
    _validate_req_coverage,
    _wants_structural,
    analyze_architecture_requirements,
    create_pptx,
    generate_pdf_report,
    generate_ppt_proposal,
    inspect_diagram,
    plan_deck,
    propose_blueprint,
    propose_deck_plan,
    propose_diagram_brief,
    propose_tech_stack,
    query_change_impact,
    record_evidence,
    resolve_finding,
    submit_critique,
    waive_finding,
    web_research,
)

# ---------------------------------------------------------------------------
# Tool lists — identical to what was at the bottom of the original tools.py
# ---------------------------------------------------------------------------

DIAGRAM_TOOLS = [
    analyze_architecture_requirements,
    propose_diagram_brief,
    web_research,
    record_evidence,
    propose_tech_stack,
    propose_blueprint,
    audit_diagram_code,
    render_diagram,
    export_drawio,
    list_saved_diagrams,
    search_diagrams_nodes,
    search_icons,
    search_drawio_shapes,
    resolve_icons,
    plan_style_sizes,
    fit_labels,
    declare_poster_grid,
    fetch_logo,
    visualize_code_structure,
    inspect_diagram,
    submit_critique,
    finalize_diagram,
    generate_pdf_report,
    propose_deck_plan,
    generate_ppt_proposal,
    query_change_impact,
]

# Late imports (same as original tools.py bottom section)
from integrations import send_architecture_report_email, propose_meeting_slots, create_client_meeting  # noqa: E402
from wbs_tools import (  # noqa: E402
    WBS_PLANNER_TOOLS, propose_wbs_skeleton, propose_wbs, export_wbs_excel,
)

MAIN_TOOLS = [
    analyze_architecture_requirements,
    propose_diagram_brief,
    # find_similar_solutions,   # DISABLED: focus on WBS testing
    web_research,             # 10 Tavily calls/session, split per stage (topic=tech_stack/architecture/wbs/evidence)
    record_evidence,          # persist a grounded claim -> evidence_log.json -> CSM Evidence + supports links
    waive_finding,            # accept a cross-artifact finding as a trade-off -> findings_log.json
    resolve_finding,          # mark a cross-artifact finding fixed -> findings_log.json
    propose_tech_stack,
    propose_blueprint,
    visualize_code_structure,
    list_saved_diagrams,
    finalize_diagram,
    generate_pdf_report,
    propose_deck_plan,        # HITL: approve the deck storyboard before rendering
    generate_ppt_proposal,
    send_architecture_report_email,
    propose_meeting_slots,    # uses internal interrupt() — NOT in GATE_TOOL_NAMES
    create_client_meeting,    # interrupt_on gate — in GATE_TOOL_NAMES
    propose_wbs_skeleton,     # WBS structure approval gate
    propose_wbs,              # WBS plan/effort approval gate
    export_wbs_excel,         # WBS .xlsx deliverable gate
    query_change_impact,      # report blast radius of a requirement change (CSM diff)
]

# Icon resolver subagent tools: node search + icon resolution (runs before drawer).
ICON_RESOLVER_TOOLS = [search_diagrams_nodes, resolve_icons, search_icons, search_drawio_shapes, fetch_logo]

# Drawer subagent tools: render-refine loop only (icons pre-resolved by icon_resolver).
DRAWER_TOOLS = [plan_style_sizes, fit_labels, declare_poster_grid, audit_diagram_code, render_diagram, export_drawio]

# Critic subagent tools: read-only review of the rendered diagram.
CRITIC_TOOLS = [inspect_diagram, submit_critique]

# PPT generator subagent tools: plan the traceable storyboard, then render the deck.
PPT_GENERATOR_TOOLS = [plan_deck, create_pptx]

# Tools that require human approval before they run (interrupt_on in agent.py).
GATE_TOOL_NAMES = [
    "propose_tech_stack",
    "propose_blueprint",
    "finalize_diagram",
    "generate_pdf_report",
    "propose_deck_plan",
    "generate_ppt_proposal",
    "send_architecture_report_email",
    "create_client_meeting",
    "propose_wbs_skeleton",
    "propose_wbs",
    "export_wbs_excel",
]

# HITL v2 decision menu (docx §5.3): the trade-off ACTIONS each gate offers the user,
# beyond binary approve/reject. This is the *product* vocabulary that drives the
# frontend decision card and is persisted as a DecisionRecord (decisions.py).
#
# Note: the underlying langchain HITL middleware only understands approve/edit/reject/
# respond, so each action maps onto one of those at resume time (session_state.
# _decision_from_payload). "accept_risk"/"approve_with_assumptions" proceed (approve);
# "request_evidence"/"request_alternative" send the agent back to revise (reject with a
# guiding message). The structured intent is captured in the persisted record + CSM.
GATE_DECISIONS: dict[str, list[str]] = {
    "propose_tech_stack": ["approve", "approve_with_assumptions", "accept_risk",
                           "request_evidence", "request_alternative", "reject"],
    "propose_blueprint": ["approve", "approve_with_assumptions", "accept_risk",
                          "request_alternative", "request_evidence", "reject"],
    "finalize_diagram": ["approve", "reject"],
    "generate_pdf_report": ["approve", "request_evidence", "reject"],
    "propose_deck_plan": ["approve", "request_alternative", "reject"],
    "generate_ppt_proposal": ["approve", "request_evidence", "reject"],
    "send_architecture_report_email": ["approve", "reject"],
    "create_client_meeting": ["approve", "reject"],
    "propose_wbs_skeleton": ["approve", "request_alternative", "reject"],
    "propose_wbs": ["approve", "approve_with_assumptions", "accept_risk",
                    "request_alternative", "reject"],
    "export_wbs_excel": ["approve", "reject"],
}


def allowed_decisions_for(gate: str) -> list[str]:
    """The HITL v2 action menu for a gate (defaults to binary approve/reject)."""
    return GATE_DECISIONS.get(gate, ["approve", "reject"])
