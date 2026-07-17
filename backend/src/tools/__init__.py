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
    resolve_missing_icons,
    resolve_tech_stack_icons,
    search_diagrams_nodes,
    search_drawio_shapes,
    search_icons,
    update_icon_plan_entry,
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
    edit_drawio,
    export_drawio,
    export_drawio_native,
    finalize_diagram,
    fit_labels,
    inspect_render_quality,
    list_saved_diagrams,
    plan_style_sizes,
    read_drawio,
    render_diagram,
    upgrade_drawio,
    visualize_code_structure,
)

# --- analysis / HITL tools + Pydantic models ---
from .schemas.coercion import CoercingModel, _mimo_coerce_before, _wants_structural
from .schemas.brief import DiagramBrief
from .schemas.tech_stack import (
    CostRange,
    DataAssumptions,
    ProposeTechStackArgs,
    ScalingPhase,
    SolutionAssumptions,
    TeamAssumptions,
    TechAlternative,
    TechChoice,
    TechCriteria,
    TechRisk,
    UserScaleAssumptions,
)
from .schemas.blueprint import (
    BPCluster,
    BPEdge,
    BPNode,
    Blueprint,
    LegendEntry,
    NFRMapping,
    PillarCoverage,
    WAFPillar,
)
from .analysis.architecture import analyze_architecture_requirements
from .analysis.blueprint_tools import (
    _build_render_spec,
    _detect_provider,
    _preseed_icon_plan,
    _req_soft_match,
    _validate_nfr_mapping,
    _validate_pillar_coverage,
    _validate_req_coverage,
    inspect_diagram,
    propose_blueprint,
    propose_diagram_brief,
    propose_tech_stack,
    submit_critique,
)
from .analysis.gates import compare_revisions, query_change_impact
from .analysis.reporting_gates import (
    PdfReportConfig,
    PptProposalConfig,
    create_pptx,
    generate_pdf_report,
    generate_ppt_proposal,
    plan_deck,
    propose_deck_plan,
)
from .analysis.research import web_research
from .analysis.findings import (
    add_comment,
    apply_compliance_pack,
    edit_entity,
    export_adr_pack,
    export_to_delivery,
    quality_summary,
    reality_sync,
    record_evidence,
    resolve_comment,
    resolve_finding,
    waive_finding,
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
    export_drawio_native,
    upgrade_drawio,
    read_drawio,
    edit_drawio,
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
    edit_entity,
    quality_summary,
    apply_compliance_pack,
    compare_revisions,
    add_comment,
    resolve_comment,
    export_adr_pack,
    export_to_delivery,
    reality_sync,
]

# Late imports (same as original tools.py bottom section)
from integrations import send_email, propose_meeting_slots, create_client_meeting  # noqa: E402
from domain.wbs.wbs_tools import (  # noqa: E402
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
    edit_entity,              # patch a single field on a CSM entity -> solution_model.json
    quality_summary,          # aggregate quality health snapshot (findings/evidence/assumptions/score)
    apply_compliance_pack,    # activate a compliance control pack -> CSM Control entities + compliance findings
    compare_revisions,        # diff current CSM vs an approved revision snapshot (§8.6)
    add_comment,              # anchor a review comment to a CSM entity -> comment_log.json
    resolve_comment,          # close a review comment
    export_adr_pack,          # render decisions -> adr_pack.md for the proposal package
    export_to_delivery,       # idempotent sync of WBS work items to Jira/Linear/Confluence (gate)
    reality_sync,             # diff design vs a real repo/infra source -> drift_report.json (§5.2)
    propose_tech_stack,
    propose_blueprint,
    visualize_code_structure,
    list_saved_diagrams,
    finalize_diagram,
    generate_pdf_report,
    propose_deck_plan,        # HITL: approve the deck storyboard before rendering
    generate_ppt_proposal,
    send_email,
    propose_meeting_slots,    # uses internal interrupt() — NOT in GATE_TOOL_NAMES
    create_client_meeting,    # interrupt_on gate — in GATE_TOOL_NAMES
    propose_wbs_skeleton,     # WBS structure approval gate
    propose_wbs,              # WBS plan/effort approval gate
    export_wbs_excel,         # WBS .xlsx deliverable gate
    query_change_impact,      # report blast radius of a requirement change (CSM diff)
]

# Icon resolver subagent tools: node search + icon resolution (runs before drawer).
ICON_RESOLVER_TOOLS = [
    search_diagrams_nodes, resolve_icons, search_icons, search_drawio_shapes, fetch_logo,
    update_icon_plan_entry, resolve_missing_icons,
]

# Drawer subagent tools: render-refine loop only. Icons are pre-resolved by
# icon_resolver; style_plan.json/label_fits.json are pre-computed code-side by
# propose_blueprint (write_style_and_fit_plans); the static audit runs inside
# render_diagram as a pre-flight gate. export_drawio_native is the deterministic
# DEFAULT for architecture diagrams (spec -> native engine, no Graphviz);
# read_drawio/edit_drawio are the targeted in-place fix loop on its output.
DRAWER_TOOLS = [declare_poster_grid, render_diagram, export_drawio,
                export_drawio_native, upgrade_drawio, read_drawio, edit_drawio]

# Critic subagent tools: read-only review of the rendered diagram.
CRITIC_TOOLS = [inspect_diagram, submit_critique]

# PPT generator subagent tools: plan the traceable storyboard, then render the deck.
# resolve_tech_stack_icons fetches per-technology logos (grouped by layer) for the
# "PROPOSED SOLUTION | Technical Stack" slide — call before create_pptx.
PPT_GENERATOR_TOOLS = [plan_deck, resolve_tech_stack_icons, create_pptx]

# Tools that require human approval before they run (interrupt_on in agent.py).
GATE_TOOL_NAMES = [
    "propose_tech_stack",
    "propose_blueprint",
    "finalize_diagram",
    "generate_pdf_report",
    "propose_deck_plan",
    "generate_ppt_proposal",
    "send_email",
    "create_client_meeting",
    "propose_wbs_skeleton",
    "propose_wbs",
    "export_wbs_excel",
    "export_to_delivery",
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
    "send_email": ["approve", "reject"],
    "create_client_meeting": ["approve", "reject"],
    "propose_wbs_skeleton": ["approve", "request_alternative", "reject"],
    "propose_wbs": ["approve", "approve_with_assumptions", "accept_risk",
                    "request_alternative", "reject"],
    "export_wbs_excel": ["approve", "reject"],
    "export_to_delivery": ["approve", "reject"],
}


def allowed_decisions_for(gate: str) -> list[str]:
    """The HITL v2 action menu for a gate (defaults to binary approve/reject)."""
    return GATE_DECISIONS.get(gate, ["approve", "reject"])


# Role-based approval (docx §8.6, §12.2 "human actions map to persisted entities").
# Which roles may sign off at which gate. A gate not listed here is open to any role.
# Technical design gates require an architect; client-facing sends require a PM/lead.
ROLE_GATE_PERMISSIONS: dict[str, set[str]] = {
    "propose_tech_stack": {"architect", "lead", "admin"},
    "propose_blueprint": {"architect", "lead", "admin"},
    "finalize_diagram": {"architect", "lead", "admin"},
    "propose_wbs": {"pm", "lead", "architect", "admin"},
    "export_wbs_excel": {"pm", "lead", "admin"},
    "generate_pdf_report": {"pm", "lead", "architect", "admin"},
    "generate_ppt_proposal": {"pm", "lead", "architect", "admin"},
    "send_email": {"pm", "lead", "admin"},
    "create_client_meeting": {"pm", "lead", "admin"},
    "export_to_delivery": {"pm", "lead", "admin"},
}


def can_approve(role: str, gate: str) -> bool:
    """Whether ``role`` is permitted to sign off ``gate``.

    Permissive by default: an empty/unknown role (the current frontend does not yet send
    one) or a gate with no role restriction returns True, so enabling roles never blocks
    an existing flow. Enforcement tightens only when a real role is supplied AND the gate
    restricts it.
    """
    allowed = ROLE_GATE_PERMISSIONS.get(gate)
    if not allowed:
        return True
    role = (role or "").strip().lower()
    if not role:
        return True
    return role in allowed
