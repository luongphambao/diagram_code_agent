"""Re-export shim — the original monolith (HITL Pydantic models + propose_diagram_brief,
propose_tech_stack, propose_blueprint, analyze_architecture_requirements, web_research,
inspect_diagram, submit_critique, generate_pdf_report, generate_ppt_proposal, ...) has
been split into cohesive submodules for readability:

  tools/schemas/       — Pydantic schemas (coercion, brief, tech_stack, blueprint)
  tools/analysis/      — tool functions (architecture, blueprint_tools, gates,
                          reporting_gates, research, findings)

This module re-exports the full original public surface (including the private
helpers a few tests and ``tools/rendering_tools.py`` reach into directly, e.g.
``analysis_tools.submit_critique`` / ``_epistemic_note`` / ``_diagram_gate_note``)
so every existing ``from tools.analysis_tools import ...`` / ``import
tools.analysis_tools as analysis_tools`` keeps working unmodified.
"""

from __future__ import annotations

# --- schemas -----------------------------------------------------------------
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

# --- analysis / HITL tool functions -------------------------------------------
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
from .analysis.gates import (
    _diagram_gate_note,
    _epistemic_note,
    _impact_ids,
    _render_model_diff_body,
    _solution_gate_note,
    compare_revisions,
    query_change_impact,
)
from .analysis.reporting_gates import (
    PdfReportConfig,
    PptProposalConfig,
    _deck_qa_note,
    _refresh_deck_plan,
    _visual_audit_note,
    audit_deck_visual,
    create_pptx,
    export_proposal_package,
    generate_pdf_report,
    generate_ppt_proposal,
    plan_deck,
    propose_deck_plan,
)
from .analysis.research import (
    _web_search_budget_report,
    _web_search_category,
    web_research,
)
from .analysis.findings import (
    _CSM_COLLECTIONS,
    _PATCHABLE_FIELDS,
    _settle_finding,
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
