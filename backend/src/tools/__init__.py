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
    generate_pdf_report,
    inspect_diagram,
    propose_blueprint,
    propose_diagram_brief,
    propose_tech_stack,
    submit_critique,
    web_research,
)

# ---------------------------------------------------------------------------
# Tool lists — identical to what was at the bottom of the original tools.py
# ---------------------------------------------------------------------------

DIAGRAM_TOOLS = [
    analyze_architecture_requirements,
    propose_diagram_brief,
    web_research,
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
    web_research,             # ≤3 Tavily calls/session — for tech-stack fact-checking
    propose_tech_stack,
    propose_blueprint,
    visualize_code_structure,
    list_saved_diagrams,
    finalize_diagram,
    generate_pdf_report,
    send_architecture_report_email,
    propose_meeting_slots,    # uses internal interrupt() — NOT in GATE_TOOL_NAMES
    create_client_meeting,    # interrupt_on gate — in GATE_TOOL_NAMES
    propose_wbs_skeleton,     # WBS structure approval gate
    propose_wbs,              # WBS plan/effort approval gate
    export_wbs_excel,         # WBS .xlsx deliverable gate
]

# Icon resolver subagent tools: node search + icon resolution (runs before drawer).
ICON_RESOLVER_TOOLS = [search_diagrams_nodes, resolve_icons, search_icons, search_drawio_shapes, fetch_logo]

# Drawer subagent tools: render-refine loop only (icons pre-resolved by icon_resolver).
DRAWER_TOOLS = [plan_style_sizes, fit_labels, declare_poster_grid, audit_diagram_code, render_diagram, export_drawio]

# Critic subagent tools: read-only review of the rendered diagram.
CRITIC_TOOLS = [inspect_diagram, submit_critique]

# Tools that require human approval before they run (interrupt_on in agent.py).
GATE_TOOL_NAMES = [
    "propose_tech_stack",
    "propose_blueprint",
    "finalize_diagram",
    "generate_pdf_report",
    "send_architecture_report_email",
    "create_client_meeting",
    "propose_wbs_skeleton",
    "propose_wbs",
    "export_wbs_excel",
]
