"""HITL Pydantic models + propose_diagram_brief, propose_tech_stack, propose_blueprint,
analyze_architecture_requirements, web_research, inspect_diagram, submit_critique,
generate_pdf_report, generate_ppt_proposal."""

from __future__ import annotations

import json
import os
import typing as _t
from typing import Annotated, Literal, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from architecture_advisor import analyze_requirements
from backends import WORKSPACE
from csm import SolutionModel
from csm_adapter import build_solution_model, SOLUTION_MODEL_NAME, SOLUTION_MODEL_PREV_NAME
from csm_diff import diff_solution_models
from deck import (
    DECK_QA_NAME,
    build_deck_plan,
    load_deck_plan,
    score_deck_structure,
    validate_deck,
    write_deck_plan,
)
from deck_visual_qa import (
    VISUAL_AUDIT_NAME,
    audit_pptx_deterministic,
    format_visual_audit,
    patch_pptx_overflow,
    write_visual_audit,
)
from proposal_package import (
    build_manifest,
    export_proposal_package as _export_proposal_package,
    format_manifest,
)
from quality_dashboard import (
    SNAPSHOT_NAME as QUALITY_SNAPSHOT_NAME,
    build_quality_snapshot,
    format_snapshot,
    write_snapshot,
)
from findings import DiagramFinding, format_critique, prune, verdict_for
from solution_validator import format_validation, validate_solution
from traceability import write_trace_links
from reporting import (
    DEFAULT_REPORT_SECTIONS,
    ReportRenderError,
    generate_report,
    record_artifact_inventory,
    record_report_step,
)
from ppt_reporting import DEFAULT_PPT_SECTIONS, PPTProposalError, generate_ppt_proposal_file
from .constants import (
    CRITIC_REVISION_HARD_CAP,
    TAVILY_SEARCH_URL,
    WEB_SEARCH_CATEGORY_CAPS,
    WEB_SEARCH_SESSION_CAP,
    WEB_SEARCH_TAVILY_TOPICS,
    _ARCH_ANALYSIS_FILE,
    _BLUEPRINT_FILE,
    _BRIEF_FILE,
    _CRITIQUE_FILE,
    _ICON_PLAN_FILE,
    _ICON_SEARCH_BUDGET_FILE,
    _RENDER_SPEC_FILE,
    _REVISION_COUNT_FILE,
    _TECHSTACK_FILE,
)
from .icon_tools import _icon_rel, _search_icon_hits
from .stage_markers import (
    _bump_tool_summary,
    _inspection_image_b64,
    _layout_audit,
    _read_json_file,
    _reset_revision_count,
    _save_web_search_state,
    _web_search_state,
    _write_json_file,
    reset_render_count,
)


# ---------------------------------------------------------------------------
# CoercingModel helpers
# ---------------------------------------------------------------------------

def _wants_structural(ann) -> bool:
    """True if the annotation expects a model/list/dict (not a bare str/number)."""
    for a in (_t.get_args(ann) or (ann,)):
        origin = _t.get_origin(a) or a
        if origin in (list, dict):
            return True
        if isinstance(origin, type) and issubclass(origin, BaseModel):
            return True
    return False


def _mimo_coerce_before(cls, values):
    """Before-validator: coerce mimo's non-standard outputs to what Pydantic expects."""
    if not isinstance(values, dict):
        return values
    for field_name in cls.model_fields:
        if field_name not in values:
            continue
        field = cls.model_fields[field_name]
        val = values[field_name]
        ann = field.annotation
        if ann is None:
            continue
        if isinstance(val, str) and _wants_structural(ann):
            try:
                parsed = json.loads(val)
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, (dict, list)):
                values[field_name] = val = parsed
        origin = _t.get_origin(ann)
        if origin is list:
            if isinstance(val, dict):
                values[field_name] = list(val.values())
            elif val is None:
                values[field_name] = []
            continue
        if origin is _t.Union:
            for arg in _t.get_args(ann):
                if _t.get_origin(arg) is list:
                    if isinstance(val, dict):
                        values[field_name] = list(val.values())
                    break
            continue
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        lo = hi = None
        for m in field.metadata:
            if getattr(m, "ge", None) is not None:
                lo = m.ge
            if getattr(m, "le", None) is not None:
                hi = m.le
        if lo is not None and val < lo:
            values[field_name] = lo
        elif hi is not None and val > hi:
            values[field_name] = hi
    return values


class CoercingModel(BaseModel):
    """BaseModel that auto-coerces dict-with-numeric-string-keys → list for list-typed fields."""

    @model_validator(mode="before")
    @classmethod
    def _coerce_dict_lists(cls, values):
        return _mimo_coerce_before(cls, values)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class DiagramBrief(CoercingModel):
    """Requirements-derived diagram brief used before tech stack and blueprint."""

    objective: str = Field(description="one concise sentence describing what the diagram must communicate")
    application_type: str = Field("", description="application type from architecture analysis, e.g. web_application|api_service|data_analytics")
    scale_level: str = Field("", description="scale signal from architecture analysis: small|medium|large|enterprise")
    security_level: str = Field("", description="security signal from architecture analysis: basic|standard|high|critical")
    provider_preference: str = Field("", description="cloud/provider signal, e.g. aws|azure|gcp|oci|onprem")
    analysis_signals: list[str] = Field(
        default_factory=list,
        description="short copied signals from architecture_analysis.json: capabilities, constraints, selected pattern hints",
    )
    stakeholders: list[str] = Field(
        default_factory=list,
        description="intended readers/reviewers, e.g. cloud/devops, security, developers, management",
    )
    functional_requirements: list[str] = Field(
        default_factory=list,
        description="architecture capabilities that must appear or be represented in the diagram",
    )
    non_functional_requirements: list[str] = Field(
        default_factory=list,
        description="quality constraints such as scalability, availability, security, governance, maintainability",
    )
    layout_constraints: list[str] = Field(
        default_factory=list,
        description="visual/layout constraints and simplification choices for the diagram",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="explicit assumptions made when the prompt/docs do not fully specify details",
    )


class TechCriteria(CoercingModel):
    """1–5 scoring dimensions for a technology choice."""
    cost: int = Field(3, ge=1, le=5, description="1=very low cost, 5=very high cost")
    ops_complexity: int = Field(3, ge=1, le=5, description="1=simple to operate, 5=high operational burden")
    scalability: int = Field(3, ge=1, le=5, description="1=limited, 5=highly scalable")
    vendor_lockin: int = Field(3, ge=1, le=5, description="1=fully portable, 5=deeply vendor-locked")
    team_fit: int = Field(3, ge=1, le=5, description="1=unfamiliar to team, 5=strong team expertise")


class TechAlternative(CoercingModel):
    """An alternative technology with rejection rationale and optional scoring."""
    name: str = Field(description="technology name")
    why_rejected: str = Field("", description="one sentence: why this alternative was not chosen for this context")
    criteria: Optional[TechCriteria] = Field(default=None, description="optional 1-5 scores for this alternative")


class CostRange(CoercingModel):
    """Assumption-based monthly cost estimate in USD (always a range)."""
    min_usd: int = Field(0, ge=0)
    max_usd: int = Field(0, ge=0)


class UserScaleAssumptions(BaseModel):
    mau: Optional[int] = None
    dau: Optional[int] = None
    peak_concurrent: Optional[int] = None
    peak_rps: Optional[int] = None
    growth_rate_yoy_pct: Optional[int] = None


class DataAssumptions(BaseModel):
    initial_gb: Optional[int] = None
    growth_gb_per_month: Optional[int] = None
    read_write_ratio: str = ""


class TeamAssumptions(BaseModel):
    size: Optional[int] = None
    skill_level: str = ""
    devops_maturity: str = ""


class SolutionAssumptions(CoercingModel):
    budget_tier: str = ""
    monthly_budget_range_usd: Optional[CostRange] = None
    users: Optional[UserScaleAssumptions] = None
    data: Optional[DataAssumptions] = None
    team: Optional[TeamAssumptions] = None
    project_phase: str = ""
    availability_target: str = ""
    latency_target_p99_ms: Optional[int] = None
    compliance: list[str] = Field(default_factory=list)
    primary_region: str = ""
    confirm_with_customer: list[str] = Field(
        default_factory=list,
        description="assumptions NOT yet confirmed by the customer — the senior-SA hedge list",
    )


class TechRisk(CoercingModel):
    risk: str
    mitigation: str = ""


class ScalingPhase(CoercingModel):
    phase: str
    trigger: str = ""
    changes: list[str] = Field(default_factory=list)
    est_monthly_cost_usd: Optional[CostRange] = None


class TechChoice(CoercingModel):
    """One layer of the recommended technology stack."""
    layer: str = Field(
        description=(
            "the layer name — core layers: frontend, backend, database, auth, infra, monitoring, networking, security; "
            "conditional layers: cache, queue, cdn, search, storage, ci_cd, analytics, ai_ml, integration"
        )
    )
    choice: str = Field(description="the specific technology chosen for this layer")
    rationale: str = Field("", description="1-2 sentence reason tied to the requirements")
    cost_tier: str = Field("$$", description="relative cost: $=low, $$=medium, $$$=high")
    decision_criteria: Optional[TechCriteria] = Field(
        default=None,
        description="1-5 scores for the CHOSEN technology on cost, ops_complexity, scalability, vendor_lockin, team_fit",
    )
    alternatives: list[TechAlternative] = Field(
        default_factory=list,
        description="rejected alternatives with why_rejected and optional criteria scores",
    )
    estimated_monthly_cost_usd: Optional[CostRange] = Field(
        default=None,
        description="assumption-based cost range for this layer in USD/month",
    )
    capacity_sizing: str = Field(
        "",
        description="instance type/count WITH the math — e.g. '2× Fargate 0.5vCPU, autoscale 2–6 — sized for ~150 RPS peak × 2 headroom'",
    )
    performance_target: str = Field(
        "",
        description="measurable target tied to an NFR — e.g. 'p99 ≤ 120 ms at 150 RPS'",
    )
    risks: list[TechRisk] = Field(
        default_factory=list,
        description="1-2 risks for this layer with mitigation",
    )


class WAFPillar(CoercingModel):
    """Coverage of one AWS Well-Architected Framework pillar in the blueprint."""
    addressed_by: list[str] = Field(
        default_factory=list,
        description="node IDs or key_decision labels that address this pillar",
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="known gaps — explicitly declare rather than leave empty; gaps are allowed when stated",
    )


class PillarCoverage(BaseModel):
    """Well-Architected Framework 6-pillar coverage."""
    operational_excellence: WAFPillar = Field(default_factory=WAFPillar)
    security: WAFPillar = Field(default_factory=WAFPillar)
    reliability: WAFPillar = Field(default_factory=WAFPillar)
    performance_efficiency: WAFPillar = Field(default_factory=WAFPillar)
    cost_optimization: WAFPillar = Field(default_factory=WAFPillar)
    sustainability: WAFPillar = Field(default_factory=WAFPillar)


class NFRMapping(CoercingModel):
    """Maps one non-functional requirement to the mechanism(s) and nodes that satisfy it."""
    nfr: str = Field(description="the NFR text, ideally measurable: e.g. '99.9% uptime SLA'")
    mechanism: str = Field(description="how this NFR is addressed: e.g. 'Multi-AZ RDS + ALB health checks'")
    node_ids: list[str] = Field(default_factory=list, description="blueprint node IDs implementing this mechanism")


class BPNode(BaseModel):
    id: str = Field(description="unique snake_case id")
    label: str = Field(description="human-readable component name")
    tech: str = Field("", description="technology for this node")
    cluster: str = Field("", description="id of the cluster this node belongs to")
    type: str = Field("", description="service|database|queue|cache|gateway|external|lb|cdn")


class BPCluster(BaseModel):
    id: str = Field(description="unique snake_case id")
    label: str = Field(description="tier / group name")
    tier: str = Field("", description="frontend|backend|data|infra|external|security")
    parent: str = Field(
        "",
        description="id of the parent cluster when this group nests inside another "
                    "(e.g. an 'OCR Pipeline' sub-group inside a 'Serving' zone); "
                    "leave empty for top-level zones",
    )
    accent: str = Field(
        "",
        description="optional pinned accent color for this zone — one of: blue, cyan, "
                    "teal, violet, indigo, green, amber, rose, slate. Leave empty to "
                    "auto-assign by declaration order. Use to color-code phases.",
    )
    number: Optional[int] = Field(
        None,
        description="optional explicit step number shown as a badge in the zone header "
                    "(1, 2, 3 …). Leave null to skip numbering.",
    )


class BPEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from", description="source node id")
    to: str = Field(description="target node id")
    label: str = Field("", description="operation or protocol label")
    protocol: str = Field("", description="HTTP|gRPC|AMQP|TCP|WebSocket|SQL|Redis")
    flow: str = Field(
        "",
        description="semantic flow category used to color-code the arrow consistently "
                    "with the legend: data|control|serving|registry|monitoring|security. "
                    "Leave empty for a neutral default arrow.",
    )
    style: str = Field(
        "",
        description="line style override: solid|dashed|dotted. Leave empty to use the "
                    "style implied by `flow` (control/monitoring/security are dashed).",
    )


class LegendEntry(BaseModel):
    """One row of the diagram legend mapping a flow category to a human label."""
    label: str = Field(description="human-readable name, e.g. 'Data & Training Flow'")
    flow: str = Field(
        "",
        description="the matching BPEdge.flow key (data|control|serving|registry|"
                    "monitoring|security) — its color/style is taken from that flow",
    )


class Blueprint(CoercingModel):
    """A structured architecture blueprint."""
    audience: str = Field(
        "client",
        description="target reader for the diagram; default client for customer-facing architecture diagrams",
    )
    detail_level: str = Field(
        "architecture",
        description="architecture|engineering|code; default architecture hides implementation details",
    )
    layout_intent: str = Field(
        "left_to_right_pipeline",
        description="intended visual flow, e.g. left_to_right_pipeline or top_down_stack",
    )
    presentation_style: Literal["slide", "diagram"] = Field(
        "slide",
        description="slide (default): production output with the gradient hero "
                    "title band + caption + legend; diagram: body-only output, "
                    "ONLY when the user explicitly asks for a plain/raw diagram",
    )
    density: Literal["standard", "detailed", "poster"] = Field(
        "detailed",
        description="detailed (DEFAULT): flow-driven landscape slide — ~20-28 nodes "
                    "(more is fine for complex systems; engine scales to fit one page), "
                    "direction='LR', flow_layout=True so real cross-cluster edges pull "
                    "the layout and connections between zones are clearly visible. "
                    "Clusters size to their content (small clusters stay small); only "
                    "clusters with ≥4 nodes get grid packing via g.grid_cluster(). "
                    "Sublabel (tech + sizing) MANDATORY for every compute/data/network "
                    "node. Primary-flow edges carry protocol labels (≤3 words). "
                    "Choose density based on actual architecture complexity — do NOT "
                    "cut nodes to fit the page; the engine scales the diagram to fit "
                    "inside one 16:9 slide. "
                    "poster: dense wall-grid output (flow_layout=False) — 25-45 nodes "
                    "in 6-12 numbered planes each packed as a multi-column logo grid; "
                    "use ONLY when the user explicitly requests a poster/wall layout. "
                    "standard: ONLY for genuinely small systems (<10 components, ≤3 "
                    "tiers) — 12-18 nodes, ≤5 columns. "
                    "Pass density to the drawer so it calls plan_style_sizes(output='poster') "
                    "for poster, or plan_style_sizes(output='slide') for standard/detailed.",
    )
    slide_title: str = Field(
        "",
        description="large slide hero title; default to the system/product name when presentation_style=slide",
    )
    slide_kicker: str = Field(
        "",
        description="small hero kicker/subtitle above the slide title",
    )
    brand: str = Field(
        "",
        description="brand text shown in the slide top-right; omit when unknown",
    )
    diagram_title: str = Field(
        "",
        description="caption above the architecture panel inside a slide",
    )
    pattern: str = Field(description="microservices|monolith|serverless|event-driven|hybrid")
    pattern_rationale: str = Field("", description="2-3 sentences: why this architecture pattern fits these requirements")
    key_decisions: list[str] = Field(
        default_factory=list,
        description="3-6 concrete design decisions & trade-offs: data flow, scaling/performance, "
                    "availability/HA, security/auth, storage, integration — one sentence each",
    )
    c4_level: Literal["context", "container"] = Field(
        "container",
        description="C4 diagram level: container (default, full component view) or context (5-8 nodes, "
                    "system boundaries + external actors only — use for executive/client slide audience)",
    )
    pillar_coverage: Optional[PillarCoverage] = Field(
        default=None,
        description="Well-Architected Framework 6-pillar coverage; for each pillar list node IDs / "
                    "key decisions that address it, and any known gaps. Gaps are allowed when declared.",
    )
    nfr_mapping: list[NFRMapping] = Field(
        default_factory=list,
        description="Maps each NFR from the diagram brief to the mechanism and blueprint nodes that satisfy it. "
                    "Use measurable NFRs when possible (SLA %, RPO minutes, latency ms).",
    )
    legend: list[LegendEntry] = Field(
        default_factory=list,
        description="optional legend rows mapping each flow category used in `edges` to "
                    "a human label (e.g. data → 'Data & Training Flow'). Leave empty to "
                    "auto-derive one row per distinct flow present in the edges.",
    )
    nodes: list[BPNode] = Field(default_factory=list)
    clusters: list[BPCluster] = Field(default_factory=list)
    edges: list[BPEdge] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool(parse_docstring=True)
def analyze_architecture_requirements(requirements: str, provider_preference: str = "") -> str:
    """Analyze architecture requirements into deterministic planning signals.

    Writes `architecture_analysis.json` so the brief, tech stack, blueprint, and
    critic stay aligned on pattern, scale, security, provider, and scope signals.
    This is NOT a human-approval gate.

    When to use: once, after reading the user prompt and attached requirement docs,
    before `propose_diagram_brief`.

    Args:
        requirements: The combined requirement text (user prompt plus extracted
            content from any uploaded requirement documents).
        provider_preference: Optional cloud preference to bias detection, e.g.
            "aws", "azure", "gcp"; empty means cloud-neutral.
    """
    analysis = analyze_requirements(requirements, provider_preference)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _ARCH_ANALYSIS_FILE.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    record_report_step(
        WORKSPACE,
        "analyze_architecture_requirements",
        summary=(
            f"Detected {analysis.get('application_type', 'application')} workload, "
            f"{analysis.get('scale_level', 'unspecified')} scale, "
            f"{analysis.get('security_level', 'unspecified')} security, "
            f"provider={analysis.get('provider_preference') or 'cloud-neutral'}."
        ),
        data=analysis,
    )
    return json.dumps(analysis, indent=2)


@tool(parse_docstring=True)
def propose_diagram_brief(brief: DiagramBrief) -> str:
    """Record the diagram requirements brief before recommending a tech stack.

    Captures objective, stakeholders, requirements, constraints, and assumptions so
    later blueprint and rendering decisions stay grounded and simplification choices
    are explicit. This is NOT a human-approval gate.

    When to use: after reading the user's prompt and any attached documents, before
    propose_tech_stack.

    Args:
        brief: The structured diagram brief (objective, stakeholders, functional and
            non-functional requirements, constraints, and assumptions).
    """
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _BRIEF_FILE.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
    record_report_step(
        WORKSPACE,
        "propose_diagram_brief",
        summary=(
            f"Recorded diagram brief with {len(brief.functional_requirements)} functional "
            f"and {len(brief.non_functional_requirements)} non-functional requirements."
        ),
        data=brief.model_dump(),
    )
    return (
        "Diagram brief recorded. Next: propose the technology stack with "
        "propose_tech_stack."
    )


class ProposeTechStackArgs(CoercingModel):
    """Args wrapper for propose_tech_stack."""
    tech_stack: list[TechChoice] = Field(
        description="one entry per layer; cover the core layers (frontend, backend, "
                    "database, auth, infra, monitoring, networking, security)",
    )
    assumptions: Optional[SolutionAssumptions] = Field(
        default=None, description="sizing basis: budget, user scale, data, team, compliance",
    )
    scaling_roadmap: Optional[list[ScalingPhase]] = Field(
        default=None, description="2-3 phase roadmap with measurable triggers",
    )
    estimated_total_monthly_cost_usd: Optional[CostRange] = Field(
        default=None, description="sum across all layers",
    )


@tool(args_schema=ProposeTechStackArgs)
def propose_tech_stack(
    tech_stack: list[TechChoice],
    assumptions: Optional[SolutionAssumptions] = None,
    scaling_roadmap: Optional[list[ScalingPhase]] = None,
    estimated_total_monthly_cost_usd: Optional[CostRange] = None,
) -> str:
    """Propose the technology stack for the user to review and approve.

    `tech_stack` is a LIST of layers, each an object with layer, choice, rationale,
    cost_tier, decision_criteria, alternatives, estimated_monthly_cost_usd,
    capacity_sizing, performance_target, risks.

    Core layers (always consider): frontend, backend, database, auth, infra,
    monitoring, networking, security.
    Conditional layers (add when requirements call for it): cache, queue, cdn,
    search, storage, ci_cd, analytics, ai_ml, integration.

    `assumptions` captures the sizing basis (budget, user scale, data, team,
    availability, compliance) BEFORE listing tech choices — state assumptions
    explicitly, put unconfirmed ones in confirm_with_customer.

    `scaling_roadmap` is a 2-3 phase roadmap with measurable triggers.
    `estimated_total_monthly_cost_usd` is the sum across all layers.

    This PAUSES for human approval — only call it once you have analysed the
    requirements. If rejected you get the user's note — revise and propose again.
    """
    if not _BRIEF_FILE.exists():
        return "Create the diagram brief first by calling propose_diagram_brief."
    WORKSPACE.mkdir(parents=True, exist_ok=True)

    layers_dict = {
        t.layer: {
            "choice": t.choice,
            "rationale": t.rationale,
            "cost_tier": t.cost_tier,
            "decision_criteria": t.decision_criteria.model_dump() if t.decision_criteria else None,
            "alternatives": [
                a.model_dump() if isinstance(a, TechAlternative) else {"name": str(a), "why_rejected": ""}
                for a in t.alternatives
            ],
            "estimated_monthly_cost_usd": t.estimated_monthly_cost_usd.model_dump() if t.estimated_monthly_cost_usd else None,
            "capacity_sizing": t.capacity_sizing,
            "performance_target": t.performance_target,
            "risks": [r.model_dump() if isinstance(r, TechRisk) else r for r in t.risks],
        }
        for t in tech_stack
    }

    as_dict: dict = {
        "assumptions": assumptions.model_dump() if assumptions else None,
        "layers": layers_dict,
        "scaling_roadmap": [p.model_dump() if isinstance(p, ScalingPhase) else p for p in (scaling_roadmap or [])],
        "estimated_total_monthly_cost_usd": estimated_total_monthly_cost_usd.model_dump() if estimated_total_monthly_cost_usd else None,
    }

    warnings: list[str] = []

    if not assumptions:
        warnings.append(
            "No sizing assumptions recorded — a senior proposal states budget, user scale, and concurrency explicitly."
        )
    elif not assumptions.confirm_with_customer:
        warnings.append(
            "confirm_with_customer is empty — list every assumption that has NOT been validated by the customer."
        )

    layers_without_cost = [t.layer for t in tech_stack if not t.estimated_monthly_cost_usd]
    if layers_without_cost:
        warnings.append(f"Layers missing cost estimate: {', '.join(layers_without_cost)}.")

    if estimated_total_monthly_cost_usd and assumptions and assumptions.monthly_budget_range_usd:
        budget_max = assumptions.monthly_budget_range_usd.max_usd
        if estimated_total_monthly_cost_usd.max_usd > budget_max:
            warnings.append(
                f"Total cost ceiling ${estimated_total_monthly_cost_usd.max_usd}/mo exceeds budget "
                f"${budget_max}/mo — adjust design or re-scope."
            )

    if estimated_total_monthly_cost_usd:
        layer_min_sum = sum(
            t.estimated_monthly_cost_usd.min_usd for t in tech_stack if t.estimated_monthly_cost_usd
        )
        if layer_min_sum > estimated_total_monthly_cost_usd.max_usd:
            warnings.append(
                f"Sum of layer minimums (${layer_min_sum}/mo) exceeds stated total maximum "
                f"(${estimated_total_monthly_cost_usd.max_usd}/mo) — cost estimates are inconsistent."
            )

    analysis_file = WORKSPACE / "architecture_analysis.json"
    if analysis_file.exists():
        try:
            import json as _json
            analysis = _json.loads(analysis_file.read_text(encoding="utf-8"))
            sec_level = (analysis.get("security_level") or "").lower()
            layer_names = {t.layer for t in tech_stack}
            if sec_level in ("high", "critical"):
                for required in ("security", "networking"):
                    if required not in layer_names:
                        warnings.append(
                            f"security_level is '{sec_level}' but layer '{required}' is missing — "
                            "add it or document why it's omitted."
                        )
        except Exception:
            pass

    _TECHSTACK_FILE.write_text(json.dumps(as_dict, indent=2), encoding="utf-8")
    record_report_step(
        WORKSPACE,
        "propose_tech_stack",
        summary=f"Approved technology stack covering {len(layers_dict)} layer(s).",
        data=as_dict,
    )

    result = (
        "Tech stack APPROVED. Next: design the architecture and call "
        "propose_blueprint with the components, clusters and connections."
    )
    if warnings:
        result += "\n\nSoft warnings (informational — does not block):\n" + "\n".join(f"• {w}" for w in warnings)
    return result


def _req_soft_match(requirement: str, candidates: list[str]) -> bool:
    """Return True if any candidate substring-matches the requirement text."""
    req_norm = requirement.lower().replace("-", " ").replace("_", " ")
    for c in candidates:
        c_norm = c.lower().replace("-", " ").replace("_", " ")
        terms = [t for t in c_norm.split() if len(t) > 3]
        if terms and any(t in req_norm for t in terms):
            return True
    return False


def _validate_pillar_coverage(blueprint: Blueprint) -> list[str]:
    """Return warning strings for pillars with no addressed_by AND no gaps declared."""
    if blueprint.pillar_coverage is None:
        return ["pillar_coverage not provided — add Well-Architected pillar coverage to the blueprint."]
    warnings: list[str] = []
    coverage = blueprint.pillar_coverage
    for pillar_name in ("operational_excellence", "security", "reliability",
                        "performance_efficiency", "cost_optimization", "sustainability"):
        pillar = getattr(coverage, pillar_name)
        if not pillar.addressed_by and not pillar.gaps:
            warnings.append(
                f"Pillar '{pillar_name}': no addressed_by nodes and no declared gaps — "
                "populate addressed_by with node IDs / decisions, or add a gap with explanation."
            )
    return warnings


def _validate_nfr_mapping(blueprint: Blueprint) -> list[str]:
    """Return unmapped NFRs: NFRs in the brief that have no entry in blueprint.nfr_mapping."""
    if not _BRIEF_FILE.exists():
        return []
    try:
        brief_data = json.loads(_BRIEF_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    brief_nfrs: list[str] = brief_data.get("non_functional_requirements", [])
    if not brief_nfrs:
        return []
    mapped_nfrs = [m.nfr for m in blueprint.nfr_mapping]
    unmapped = [
        nfr for nfr in brief_nfrs
        if not _req_soft_match(nfr, mapped_nfrs)
    ]
    return unmapped


def _validate_req_coverage(blueprint: Blueprint) -> tuple[int, int, list[str]]:
    """Return (covered_count, total_count, list_of_uncovered) for functional requirements."""
    if not _BRIEF_FILE.exists():
        return 0, 0, []
    try:
        brief_data = json.loads(_BRIEF_FILE.read_text(encoding="utf-8"))
    except Exception:
        return 0, 0, []
    func_reqs: list[str] = brief_data.get("functional_requirements", [])
    if not func_reqs:
        return 0, 0, []
    candidates: list[str] = []
    for node in blueprint.nodes:
        if node.label:
            candidates.append(node.label)
        if node.id:
            candidates.append(node.id)
    for cluster in blueprint.clusters:
        if cluster.label:
            candidates.append(cluster.label)
    candidates.extend(blueprint.key_decisions)
    covered = [req for req in func_reqs if _req_soft_match(req, candidates)]
    uncovered = [req for req in func_reqs if not _req_soft_match(req, candidates)]
    return len(covered), len(func_reqs), uncovered


def _detect_provider() -> str:
    """Read provider from architecture_analysis.json, fall back to empty string."""
    try:
        analysis = json.loads(_ARCH_ANALYSIS_FILE.read_text(encoding="utf-8"))
        return (analysis.get("provider_preference") or "").strip().lower()
    except Exception:
        return ""


def _build_render_spec(blueprint: Blueprint, provider: str) -> dict:
    """Build a compact render spec dict from an approved blueprint."""
    legend = [{"label": le.label, "flow": le.flow} for le in blueprint.legend]
    if not legend:
        _flow_labels = {
            "data": "Data Flow", "control": "Control Flow", "serving": "Serving / Inference",
            "registry": "Registry & Storage", "monitoring": "Monitoring", "security": "Security",
        }
        seen: list[str] = []
        for e in blueprint.edges:
            if e.flow and e.flow not in seen:
                seen.append(e.flow)
        legend = [{"label": _flow_labels.get(f, f.title()), "flow": f} for f in seen]
    return {
        "provider": provider,
        "pattern": blueprint.pattern,
        "density": blueprint.density,
        "presentation_style": blueprint.presentation_style,
        "layout_intent": blueprint.layout_intent,
        "slide_title": blueprint.slide_title,
        "slide_kicker": blueprint.slide_kicker,
        "brand": blueprint.brand,
        "diagram_title": blueprint.diagram_title,
        "legend": legend,
        "nodes": [
            {"id": n.id, "label": n.label, "tech": n.tech, "cluster": n.cluster, "type": n.type}
            for n in blueprint.nodes
        ],
        "clusters": [
            {"id": c.id, "label": c.label, "tier": c.tier,
             "parent": c.parent, "accent": c.accent, "number": c.number}
            for c in blueprint.clusters
        ],
        "edges": [
            {"from": e.from_, "to": e.to, "label": e.label, "protocol": e.protocol,
             "flow": e.flow, "style": e.style}
            for e in blueprint.edges
        ],
    }


def _preseed_icon_plan(blueprint: Blueprint, provider: str) -> None:
    """Run deterministic icon lookups for every node label and write icon_plan.json."""
    plan: dict[str, list[str]] = {}
    for node in blueprint.nodes:
        query = node.label or node.id
        hits = _search_icon_hits(query, provider or None, limit=5)
        plan[node.id] = [_icon_rel(h) for h in hits]
    try:
        _ICON_PLAN_FILE.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    except Exception:
        pass


@tool(parse_docstring=True)
def propose_blueprint(blueprint: Blueprint) -> str:
    """Propose the architecture blueprint for the user to review and approve.

    PAUSES for human approval. Runs deterministic validators for Well-Architected
    pillar coverage, NFR mapping, and functional requirements coverage — warnings
    are surfaced but do NOT block approval.

    When to use: AFTER the tech stack is approved, to lock the component/cluster/edge
    design before icon resolution and rendering.

    Args:
        blueprint: The full architecture blueprint (nodes, clusters, edges, pattern,
            and density) to present for approval.
    """
    if not _TECHSTACK_FILE.exists():
        return "Get the tech stack approved first by calling propose_tech_stack."
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _BLUEPRINT_FILE.write_text(
        blueprint.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
    )

    # Write compact render_spec.json so the drawer reads from disk.
    provider = _detect_provider()
    render_spec = _build_render_spec(blueprint, provider)
    _RENDER_SPEC_FILE.write_text(json.dumps(render_spec, indent=2), encoding="utf-8")

    # Pre-seed icon_plan.json so the drawer skips redundant search_icons calls.
    _preseed_icon_plan(blueprint, provider)

    # --- deterministic validators (warnings only, do not block) ---
    warnings: list[str] = []

    pillar_warns = _validate_pillar_coverage(blueprint)
    if pillar_warns:
        warnings.extend(pillar_warns)

    unmapped_nfrs = _validate_nfr_mapping(blueprint)
    if unmapped_nfrs:
        warnings.append(
            f"NFR mapping: {len(unmapped_nfrs)} NFR(s) from the brief have no nfr_mapping entry: "
            + ", ".join(f'"{n}"' for n in unmapped_nfrs[:5])
        )

    covered, total, uncovered_reqs = _validate_req_coverage(blueprint)
    coverage_line = ""
    if total > 0:
        coverage_pct = round(100 * covered / total)
        coverage_line = f"Coverage: {covered}/{total} functional requirements ({coverage_pct}%)"
        if uncovered_reqs:
            coverage_line += " — missing: " + "; ".join(f'"{r}"' for r in uncovered_reqs[:5])

    # --- density mismatch detection ---
    n = len(blueprint.nodes)
    d = blueprint.density
    if n < 10 and d == "poster":
        warnings.append(
            f"density mismatch: blueprint has only {n} nodes but density='poster'. "
            "Poster mode with <10 nodes produces a sparse wall-grid — consider "
            "density='standard' for small systems, or density='detailed' (flow-driven) "
            "if you want the default house style."
        )
    elif n >= 13 and d == "standard":
        warnings.append(
            f"density mismatch: blueprint has {n} nodes but density='standard'. "
            "Standard is for genuinely small systems (<10 components). Switch to "
            "density='detailed' (flow-driven, the house default) so the diagram "
            "shows the full architecture."
        )

    # --- report quality ---
    if len(blueprint.key_decisions) < 3:
        warnings.append(
            f"report quality: blueprint has only {len(blueprint.key_decisions)} key_decision(s) "
            "(target ≥ 3). This field feeds the executive summary, traceability, and risks sections "
            "of the PDF report — add concrete design decisions and trade-offs before approving."
        )
    if not blueprint.pillar_coverage:
        warnings.append(
            "report quality: pillar_coverage is empty. "
            "This field feeds the Well-Architected Review section of the PDF report — "
            "populate at least the 4 core pillars (security, reliability, performance_efficiency, "
            "cost_optimization) before approving."
        )

    record_report_step(
        WORKSPACE,
        "propose_blueprint",
        summary=(
            f"Approved {blueprint.pattern} blueprint with {n} nodes (density={d}), "
            f"{len(blueprint.clusters)} clusters, and {len(blueprint.edges)} edges."
            + (f" {coverage_line}." if coverage_line else "")
        ),
        data=blueprint.model_dump(by_alias=True),
    )
    reset_render_count()
    _reset_revision_count()

    result_parts = [
        f"Blueprint APPROVED (density={d}, {n} nodes). "
        "Next: write the diagram code, call render_diagram, "
        "look at the PNG and refine, call export_drawio, then finalize_diagram.",
    ]
    if coverage_line:
        result_parts.append(coverage_line)
    if warnings:
        result_parts.append(
            "Architect warnings (address before finalizing if possible):\n"
            + "\n".join(f"  ⚠ {w}" for w in warnings)
        )
    # Per-stage cross-artifact gate (advisory): now that the blueprint exists, surface
    # drift (unmapped requirement, dangling edge, missing decisions) early instead of
    # only at export. 3-outcome verdict; settled findings are filtered.
    return "\n\n".join(result_parts) + _solution_gate_note("blueprint")


@tool
def inspect_diagram(tool_call_id: Annotated[str, InjectedToolCallId]) -> ToolMessage:
    """Load the LAST rendered diagram (out.png) plus its layout audit to review it.

    Read-only — this does NOT render. Returns the rendered PNG so you can LOOK at
    it and the objective layout audit (page aspect ratio + label-bearing edges
    that strand). Call this once, then judge the diagram against the blueprint.
    """
    png = WORKSPACE / "out.png"
    if not png.exists():
        return ToolMessage(
            content="No rendered diagram (out.png) to inspect yet.",
            name="inspect_diagram",
            tool_call_id=tool_call_id,
            status="error",
        )
    audit = _layout_audit()
    text = "Here is the rendered diagram to review."
    if audit:
        text += "\n\nObjective layout audit (read this FIRST):\n" + audit
    include_image = os.getenv("RENDER_INCLUDES_IMAGE", "1").lower() not in ("0", "false", "no")
    if include_image:
        b64, mime = _inspection_image_b64(png)
        return ToolMessage(
            content_blocks=[
                {"type": "text", "text": text},
                {"type": "image", "base64": b64, "mime_type": mime},
            ],
            name="inspect_diagram",
            tool_call_id=tool_call_id,
            status="success",
        )
    return ToolMessage(
        content=text + "\n\nImage is at out.png in the workspace.",
        name="inspect_diagram",
        tool_call_id=tool_call_id,
        status="success",
    )


@tool(parse_docstring=True)
def submit_critique(findings: list[DiagramFinding]) -> str:
    """Record your diagram review as a list of concrete findings and get the verdict.

    Findings are ranked and capped; the returned text starts with `VERDICT: PASS`
    or `VERDICT: REVISE`. Return that verdict text verbatim as your final answer so
    the architect can act on it.

    When to use: once, after inspecting the rendered diagram against the blueprint.

    Args:
        findings: The list of concrete review findings; each is
            {severity, confidence, category, title, detail, fix_suggestion?,
            in_blueprint?}. Pass an empty list if the diagram is clean.
    """
    kept = prune(findings)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _CRITIQUE_FILE.write_text(
        json.dumps([f.model_dump() for f in kept], indent=2), encoding="utf-8"
    )
    critique_data = [f.model_dump() for f in kept]
    if verdict_for(kept) == "revise":
        state = _read_json_file(_REVISION_COUNT_FILE, {"count": 0})
        count = int(state.get("count", 0)) + 1
        _write_json_file(_REVISION_COUNT_FILE, {"count": count})
        _bump_tool_summary("submit_critique", critic_revisions=count)
        if count > CRITIC_REVISION_HARD_CAP:
            base = format_critique(kept)
            return (
                f"VERDICT: PASS (revision limit reached: {CRITIC_REVISION_HARD_CAP} "
                "drawer revision rounds already used — proceed to finalize and "
                "mention residual findings)\n"
                + "\n".join(base.splitlines()[1:])
            )
        reset_render_count()  # a revision round gets a fresh render/search budget
    else:
        _bump_tool_summary("submit_critique")
    verdict_text = format_critique(kept)
    record_report_step(
        WORKSPACE,
        "submit_critique",
        status="revise" if verdict_for(kept) == "revise" else "passed",
        summary=verdict_text.splitlines()[0] if verdict_text else "Critic review completed.",
        data={"findings": critique_data},
    )
    return verdict_text


class PdfReportConfig(BaseModel):
    title: str = Field("", description="Override PDF cover title; defaults to blueprint.slide_title")
    subtitle: str = Field("", description="Cover subtitle/kicker")
    brand: str = Field("", description="Brand name shown on cover; defaults to blueprint.brand")
    include_sections: list[str] = Field(
        default_factory=lambda: DEFAULT_REPORT_SECTIONS.copy(),
        description=(
            "Ordered list of sections to include. Valid names: cover, executive_summary, "
            "requirements_analysis, traceability, solution, techstack, architecture_analysis, "
            "well_architected, step_results, risks, diagram. "
            "Leave EMPTY to include ALL sections (recommended). "
            "Only pass a subset when the USER explicitly asked to omit specific sections."
        ),
    )
    reason_for_subset: str = Field(
        "",
        description=(
            "REQUIRED when include_sections is a subset of all sections: quote the user's "
            "exact words that requested omitting sections (e.g. 'user said: only blueprint and diagram'). "
            "Leave empty when calling with all sections or with no include_sections argument. "
            "If this field is empty and include_sections is shorter than the full list, "
            "the tool will auto-expand to all sections."
        ),
    )


def _epistemic_note(model, *, cap: int = 8) -> str:
    """Render the CSM's epistemic split (docx §4.2) as a compact block with entity IDs.

    Shows what is known vs. what still needs a human: confirmed facts, pending
    assumptions (flagged for customer confirmation), open decisions, and hard
    constraints. Each item is prefixed with its stable CSM id so the user can act on
    it at a gate via HITL v2 — `approve_with_assumptions` (confirm specific ASM-* ids)
    or `request_evidence` — and the confirmed/accepted state flows back into the CSM.
    """
    try:
        summ = model.epistemic_summary()
    except Exception:
        return ""

    def _ids(items, text_key):
        return [f'{it.get("id", "?")}: {it[text_key]}' for it in items]

    pending = summ.get("assumptions_needing_confirmation", [])
    must   = [a for a in pending if a.get("tier") == "must_confirm"]
    should = [a for a in pending if a.get("tier") == "should_confirm"]
    nice   = [a for a in pending if a.get("tier") == "nice_to_confirm"]

    asm_sections: list[tuple[str, list]] = []
    if must:
        asm_sections.append(("Assumptions — MUST CONFIRM (financial/deadline/compliance/SLA)", must))
    if should:
        asm_sections.append(("Assumptions — should confirm", should))
    if nice:
        asm_sections.append(("Assumptions — nice to confirm", nice))

    sections: list[tuple[str, list]] = [
        ("Known facts", _ids(summ["known_facts"], "statement")),
    ]
    for tier_title, tier_items in asm_sections:
        sections.append((tier_title + " — confirm via approve_with_assumptions",
                         _ids(tier_items, "statement")))
    sections += [
        ("Open decisions", _ids(summ["open_decisions"], "title")),
        ("Constraints",
         [f'{c.get("id", "?")}: {c["statement"]} [{c["kind"]}]' for c in summ["constraints"]]),
    ]
    lines: list[str] = []
    for title, items in sections:
        if not items:
            continue
        lines.append(f"{title}:")
        lines.extend(f"  - {it}" for it in items[:cap])
        if len(items) > cap:
            lines.append(f"  - … (+{len(items) - cap} more)")
    if not lines:
        return ""
    return "\n\nEPISTEMIC SUMMARY (confirm assumptions / request evidence at the gate):\n" + "\n".join(lines)


def _solution_gate_note(stage: str = "export", *, block: bool = False) -> str:
    """Run the cross-artifact validator + refresh trace_links.json at a pipeline gate.

    Called after a stage (`blueprint`/`wbs`, advisory) and before an export
    (`block=True`, the release gate). The validator's findings are merged into the
    persisted `findings_log.json` so a defect keeps a stable id and a `waived`/`resolved`
    status survives re-runs; findings a human already settled are dropped here, so a
    waived defect can never re-block an export (docx §4.3, §7.1). The summary's first
    line is `VALIDATION: PASS|AUTO-REPAIR|HUMAN-DECISION|WARN|BLOCK` for the three gate
    outcomes (pass / auto-repair / human-decision), plus an epistemic summary.
    """
    try:
        model = build_solution_model(WORKSPACE)   # materialize/refresh the CSM projection
        write_trace_links(WORKSPACE)
        findings, _ = validate_solution(WORKSPACE, block=block)
    except Exception:
        return ""
    # Merge compliance-pack findings (required controls missing/ungrounded, §4 P2).
    # No-op unless a pack was selected via apply_compliance_pack.
    try:
        from compliance import compliance_findings
        findings = list(findings) + compliance_findings(model)
    except Exception:
        pass
    # Persist the lifecycle and drop findings a human already waived/resolved, so the
    # gate reflects open work only. Best-effort: a store hiccup must not break the gate.
    try:
        from finding_store import active_findings, upsert_findings
        upsert_findings(findings, revision=model.revision)
        findings = active_findings(findings)
    except Exception:
        pass
    summary = format_validation(findings, block=block)
    csm_note = (
        f"\n\nSOLUTION MODEL — revision {model.revision}: "
        f"{len(model.requirements)} req, {len(model.components)} component, "
        f"{len(model.work_items)} task, {len(model.trace_links)} trace link(s) "
        "(solution_model.json)."
    )
    csm_note += _epistemic_note(model)
    if not findings:
        return csm_note
    note = csm_note + f"\n\nCROSS-ARTIFACT CHECK [{stage}] — " + summary
    if block and summary.startswith("VALIDATION: BLOCK"):
        note += (
            "\n\nRELEASE GATE: blocking contradiction(s) remain — do NOT send this to the "
            "client. Either fix the artifact and re-run, or, if it is an accepted trade-off, "
            "call waive_finding(finding_id, reason) / resolve_finding(finding_id, fix_applied) "
            "to record the decision and clear the block."
        )
    return note


def _diagram_gate_note(*, block: bool = False) -> str:
    """Lint out.drawio → SolutionFindings → persist lifecycle → 3-outcome summary.

    Mirrors _solution_gate_note() but scoped to the rendered diagram artifact.
    Findings go into findings_log.json so waive_finding/resolve_finding apply
    to diagram defects just like blueprint/WBS defects (docx §4.7).
    """
    from validate_drawio import validate_file, findings_from_validation
    from finding_store import active_findings, upsert_findings
    from solution_validator import format_validation

    drawio_path = WORKSPACE / "out.drawio"
    if not drawio_path.exists():
        return ""
    try:
        result = validate_file(str(drawio_path))
        findings = findings_from_validation(result)
    except Exception:
        return ""
    try:
        revision = "0"
        try:
            from csm_adapter import build_solution_model
            m = build_solution_model(WORKSPACE)
            revision = str(m.revision)
        except Exception:
            pass
        upsert_findings(findings, revision=revision)
        findings = active_findings(findings)
    except Exception:
        pass
    if not findings:
        return "\n\nDIAGRAM LINT: PASS — no structural errors, warnings, or style advice."
    summary = format_validation(findings, block=block)
    note = f"\n\nDIAGRAM LINT [{('blocking' if block else 'advisory')}] — {summary}"
    if block and summary.startswith("VALIDATION: BLOCK"):
        note += (
            "\n\nRELEASE GATE: diagram has blocking defect(s). Fix and re-export, or call "
            "waive_finding(finding_id, reason) / resolve_finding(finding_id, fix_applied) "
            "to record the decision and clear the block."
        )
    return note


def _impact_ids(dumps: list[dict], cap: int = 8) -> str:
    ids = [str(d.get("id") or "?") for d in dumps]
    head = ", ".join(ids[:cap])
    return head + (f" … (+{len(ids) - cap} more)" if len(ids) > cap else "")


@tool(parse_docstring=True)
def query_change_impact() -> str:
    """Compare the current CSM revision to the previous snapshot and report what changed.

    Reads solution_model.json (current) and solution_model.prev.json (previous, written
    automatically when a revision bumps), diffs them by stable CSM id, and returns a
    compact report: a greppable summary line, then added/removed/changed entities per
    type and trace-link deltas. Call this after the user revises a requirement (and the
    solution model has been refreshed) to see the blast radius of the change. Returns
    CHANGE_IMPACT: NONE when there is no previous snapshot or nothing changed.
    """
    cur_raw = _read_json_file(WORKSPACE / SOLUTION_MODEL_NAME, None)
    prev_raw = _read_json_file(WORKSPACE / SOLUTION_MODEL_PREV_NAME, None)
    if cur_raw is None:
        return "CHANGE_IMPACT: NONE — no solution model yet (run the pipeline first)."
    if prev_raw is None:
        return "CHANGE_IMPACT: NONE — no previous snapshot yet (model has not changed since first build)."
    try:
        new = SolutionModel.model_validate(cur_raw)
        old = SolutionModel.model_validate(prev_raw)
    except Exception as exc:  # noqa: BLE001
        return f"CHANGE_IMPACT: ERROR — could not parse solution model: {exc}"

    d = diff_solution_models(old, new)
    s = d["summary"]
    total_added = s["entities_added"]
    total_removed = s["entities_removed"]
    total_changed = s["entities_changed"]
    head = (f"CHANGE_IMPACT: REV {d['revision']['from']}→{d['revision']['to']} | "
            f"+{total_added} -{total_removed} ~{total_changed} entities")
    if not (total_added or total_removed or total_changed
            or s["links_added"] or s["links_removed"]):
        return f"CHANGE_IMPACT: NONE — REV {d['revision']['from']}→{d['revision']['to']}, no entity or link changes."

    return "\n".join([head] + _render_model_diff_body(d))


def _render_model_diff_body(d: dict) -> list[str]:
    """Render the per-entity-type + trace-link delta lines of a `diff_solution_models`
    result. Shared by query_change_impact (vs prev snapshot) and compare_revisions
    (vs an approved revision)."""
    lines: list[str] = []
    for label in (
        "requirements", "constraints", "assumptions", "decisions",
        "components", "risks", "work_items",
    ):
        part = d[label]
        if not (part["added"] or part["removed"] or part["changed"]):
            continue
        lines.append(f"{label}: +{len(part['added'])} -{len(part['removed'])} ~{len(part['changed'])}")
        if part["added"]:
            lines.append(f"  added:   {_impact_ids(part['added'])}")
        if part["removed"]:
            lines.append(f"  removed: {_impact_ids(part['removed'])}")
        if part["changed"]:
            lines.append(f"  changed: {_impact_ids(part['changed'])}")
    links = d["trace_links"]
    if links["added"] or links["removed"]:
        lines.append(f"trace_links: +{len(links['added'])} -{len(links['removed'])}")
    return lines


@tool(parse_docstring=True)
def compare_revisions(approved_revision: int = 0) -> str:
    """Compare the current solution model to a previously APPROVED revision (docx §8.6).

    Enterprise audit/collaboration view: diff the live CSM against the immutable snapshot
    a stakeholder signed off on (approved/REV-<n>.json, written when a gate is approved),
    so a reviewer can see exactly what changed since approval — added/removed/changed
    entities per type plus trace-link deltas. With no argument it compares against the
    most recent approved revision. Returns COMPARE: NONE when there is no approved
    snapshot or nothing changed.

    Args:
        approved_revision: The approved revision number to compare against; 0 = latest.
    """
    approved_dir = WORKSPACE / "approved"
    if not approved_dir.exists():
        return "COMPARE: NONE — no approved revision yet (approve a gate first)."
    snaps = sorted(approved_dir.glob("REV-*.json"),
                   key=lambda p: int(p.stem.split("-")[1]) if p.stem.split("-")[1].isdigit() else 0)
    if not snaps:
        return "COMPARE: NONE — no approved revision snapshots found."
    if approved_revision:
        target = approved_dir / f"REV-{approved_revision}.json"
        if not target.exists():
            avail = ", ".join(p.stem for p in snaps)
            return f"COMPARE: NONE — approved REV-{approved_revision} not found. Available: {avail}."
    else:
        target = snaps[-1]
    cur_raw = _read_json_file(WORKSPACE / SOLUTION_MODEL_NAME, None)
    old_raw = _read_json_file(target, None)
    if cur_raw is None or old_raw is None:
        return "COMPARE: NONE — missing current or approved model."
    try:
        new = SolutionModel.model_validate(cur_raw)
        old = SolutionModel.model_validate(old_raw)
    except Exception as exc:  # noqa: BLE001
        return f"COMPARE: ERROR — could not parse a model: {exc}"
    d = diff_solution_models(old, new)
    s = d["summary"]
    total = s["entities_added"] + s["entities_removed"] + s["entities_changed"]
    head = (f"COMPARE: approved {target.stem} → current REV {d['revision']['to']} | "
            f"+{s['entities_added']} -{s['entities_removed']} ~{s['entities_changed']} entities")
    if not (total or s["links_added"] or s["links_removed"]):
        return f"COMPARE: NONE — current model is unchanged from approved {target.stem}."
    return "\n".join([head] + _render_model_diff_body(d))


@tool(args_schema=PdfReportConfig)
def generate_pdf_report(
    title: str = "",
    subtitle: str = "",
    brand: str = "",
    include_sections: list[str] | None = None,
    reason_for_subset: str = "",
) -> str:
    """Generate a client-ready HTML + PDF report from approved artifacts.

    Reads the staged architecture artifacts and report_evidence.json, renders
    out.report.html, then renders out.pdf with Playwright Chromium. Call this
    AFTER finalize_diagram is approved.
    """
    auto_expanded_msg = ""
    if include_sections and len(include_sections) < len(DEFAULT_REPORT_SECTIONS) and not reason_for_subset.strip():
        auto_expanded_msg = (
            f" NOTE: include_sections had only {len(include_sections)} section(s) but no "
            "reason_for_subset was provided — auto-expanded to all sections to avoid a "
            "truncated report. Pass reason_for_subset quoting the user's request if a "
            "subset was intentional."
        )
        include_sections = None

    try:
        html_path, pdf_path, sections, unrecognized = generate_report(
            WORKSPACE,
            title=title,
            subtitle=subtitle,
            brand=brand,
            include_sections=include_sections,
        )
    except FileNotFoundError as exc:
        return str(exc)
    except ReportRenderError as exc:
        return f"PDF report generation failed: {exc}"
    _bump_tool_summary("generate_pdf_report", pdf_pages=len(sections))
    msg = f"Wrote {pdf_path} and {html_path} ({len(sections)} sections)."
    if auto_expanded_msg:
        msg += auto_expanded_msg
    if unrecognized:
        msg += (
            f" WARNING: {len(unrecognized)} unrecognized section name(s) were ignored: "
            + ", ".join(f'"{n}"' for n in unrecognized)
            + ". Valid names: cover, executive_summary, requirements_analysis, traceability, "
            "solution, techstack, architecture_analysis, well_architected, step_results, risks, diagram."
        )
    if include_sections:
        missing = [s for s in DEFAULT_REPORT_SECTIONS if s not in sections]
        if missing:
            msg += (
                f" NOTE: {len(missing)} section(s) were omitted from this run: "
                + ", ".join(missing) + "."
            )
    msg += _solution_gate_note("pdf_export", block=True)
    return msg


class PptProposalConfig(BaseModel):
    title: str = Field("", description="Override PPT cover title; defaults to blueprint.slide_title")
    subtitle: str = Field("", description="Cover subtitle/kicker")
    brand: str = Field("", description="Brand name shown on cover; defaults to blueprint.brand")
    include_sections: list[str] = Field(
        default_factory=lambda: DEFAULT_PPT_SECTIONS.copy(),
        description=(
            "Ordered list of PPT proposal sections to include. Valid names: cover, "
            "executive_summary, solution_overview, scope, architecture_diagram, "
            "technical_stack, key_decisions, delivery_plan, risks, appendix. "
            "Leave EMPTY to include ALL sections (recommended). "
            "Only pass a subset when the USER explicitly asked to omit sections."
        ),
    )
    reason_for_subset: str = Field(
        "",
        description=(
            "REQUIRED when include_sections is a subset of all sections: quote the user's "
            "exact words that requested omitting sections. Leave empty when calling with all sections."
        ),
    )


@tool(args_schema=PptProposalConfig)
def generate_ppt_proposal(
    title: str = "",
    subtitle: str = "",
    brand: str = "",
    include_sections: list[str] | None = None,
    reason_for_subset: str = "",
) -> str:
    """Generate an editable BnK PowerPoint proposal from approved artifacts.

    Reads the staged architecture artifacts and rendered diagram, then renders
    out.pptx using the BnK proposal template. Call this AFTER finalize_diagram is approved.
    """
    auto_expanded_msg = ""
    if include_sections and len(include_sections) < len(DEFAULT_PPT_SECTIONS) and not reason_for_subset.strip():
        auto_expanded_msg = (
            f" NOTE: include_sections had only {len(include_sections)} section(s) but no "
            "reason_for_subset was provided - auto-expanded to all sections to avoid a "
            "truncated proposal."
        )
        include_sections = None

    try:
        pptx_path, sections, unrecognized = generate_ppt_proposal_file(
            WORKSPACE,
            title=title,
            subtitle=subtitle,
            brand=brand,
            include_sections=include_sections,
        )
    except FileNotFoundError as exc:
        return str(exc)
    except PPTProposalError as exc:
        return f"PPT proposal generation failed: {exc}"
    _bump_tool_summary("generate_ppt_proposal", ppt_sections=len(sections))
    msg = f"Wrote {pptx_path} ({len(sections)} sections)."
    if auto_expanded_msg:
        msg += auto_expanded_msg
    if unrecognized:
        msg += (
            f" WARNING: {len(unrecognized)} unrecognized section name(s) were ignored: "
            + ", ".join(f'"{n}"' for n in unrecognized)
            + ". Valid names: "
            + ", ".join(DEFAULT_PPT_SECTIONS)
            + "."
        )
    if include_sections:
        missing = [s for s in DEFAULT_PPT_SECTIONS if s not in sections]
        if missing:
            msg += f" NOTE: {len(missing)} section(s) were omitted from this run: " + ", ".join(missing) + "."
    msg += _solution_gate_note("ppt_export", block=True)
    msg += _deck_qa_note()
    msg += _visual_audit_note(pptx_path)
    return msg


@tool(parse_docstring=True)
def create_pptx(
    title: str = "",
    subtitle: str = "",
    brand: str = "",
    include_sections: list[str] | None = None,
) -> str:
    """Write out.pptx from the approved workspace artifacts.

    Called by the ppt_generator subagent to produce the slide deck from
    context files already present in the workspace (blueprint.json,
    diagram_brief.json, tech_stack.json, out.png).  Unlike the gate tool
    generate_ppt_proposal, this tool runs silently without pausing for
    human approval — it is invoked only after the user has already agreed
    to the proposed section list.

    Args:
        title: Deck title (falls back to blueprint slide_title if empty).
        subtitle: Subtitle / kicker line.
        brand: Client brand name shown on the cover.
        include_sections: Section keys to render; leave empty for all sections.
    """
    try:
        pptx_path, sections, unrecognized = generate_ppt_proposal_file(
            WORKSPACE,
            title=title,
            subtitle=subtitle,
            brand=brand,
            include_sections=include_sections or None,
        )
    except FileNotFoundError as exc:
        return f"ERROR: {exc}"
    except PPTProposalError as exc:
        return f"ERROR: PPT generation failed: {exc}"
    _bump_tool_summary("generate_ppt_proposal", ppt_sections=len(sections))
    msg = f"Wrote {pptx_path} ({len(sections)} slides rendered)."
    if unrecognized:
        msg += f" Ignored unrecognised sections: {', '.join(unrecognized)}."
    return msg


# --- deck quality loop (docx §4.8) -------------------------------------------

def _refresh_deck_plan(title: str = "", subtitle: str = "", brand: str = ""):
    """Build/refresh deck_plan.json from the CSM + artifacts. Returns (model, plan)."""
    model = build_solution_model(WORKSPACE)
    wbs = _read_json_file(WORKSPACE / "wbs.json", {}) or {}
    brief = _read_json_file(WORKSPACE / "diagram_brief.json", {}) or {}
    has_diagram = (WORKSPACE / "out.body.png").exists() or (WORKSPACE / "out.png").exists()
    plan = build_deck_plan(
        model, wbs=wbs, brief=brief, has_diagram=has_diagram,
        title=title, subtitle=subtitle, brand=brand,
    )
    write_deck_plan(plan, WORKSPACE)
    return model, plan


def _deck_qa_note(model=None) -> str:
    """Run validate_deck + score_deck_structure over the stored plan, write deck_qa_result.json."""
    plan = load_deck_plan(WORKSPACE)
    if plan is None:
        return ""
    if model is None:
        try:
            model = build_solution_model(WORKSPACE)
        except Exception:
            return ""
    findings = validate_deck(plan, model)
    struct = score_deck_structure(plan)
    try:
        (WORKSPACE / DECK_QA_NAME).write_text(
            json.dumps({
                "deck_revision": plan.revision,
                "findings": findings,
                "structural_score": struct["score"],
                "structural_grade": struct["grade"],
                "structural_issues": struct["issues"],
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass
    grounded = sum(1 for s in plan.slides if s.source_refs)
    trace_total = sum(len(s.source_refs) for s in plan.slides)
    head = (
        f"\n\nDECK QA — storyboard revision {plan.revision}: {len(plan.slides)} slides, "
        f"{grounded} grounded in {trace_total} CSM source ref(s). "
        f"Structural score: {struct['score']}/100 [{struct['grade']}]."
    )
    parts: list[str] = []
    if findings:
        by_sev: dict[str, int] = {}
        for f in findings:
            by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
        lines = [
            f"  ⚠ [{f['severity']}/{f['dimension']}] slide {f['slide_no']}: {f['evidence']}"
            for f in findings[:8]
        ]
        extra = f"\n  … (+{len(findings) - 8} more)" if len(findings) > 8 else ""
        sev = ", ".join(f"{k}:{v}" for k, v in sorted(by_sev.items()))
        parts.append(f"{len(findings)} traceability finding(s) ({sev}):\n" + "\n".join(lines) + extra)
    else:
        parts.append("No traceability/consistency/evidence issues.")
    if struct["issues"]:
        struct_lines = [f"  ⚠ {iss}" for iss in struct["issues"][:6]]
        extra2 = f"\n  … (+{len(struct['issues']) - 6} more)" if len(struct["issues"]) > 6 else ""
        parts.append(f"Structural issues ({struct['deductions']} pts deducted):\n" + "\n".join(struct_lines) + extra2)
    return head + " " + " | ".join(parts)


def _visual_audit_note(pptx_path: str | None) -> str:
    """Run deterministic visual audit on *pptx_path*, auto-patch HIGH issues,
    write deck_visual_audit.json, and return a human-readable summary string."""
    if not pptx_path:
        return ""
    try:
        from pathlib import Path as _Path
        result = audit_pptx_deterministic(pptx_path)
        if result.high_count > 0:
            high_issues = [i for i in result.issues if i.severity == "high"]
            patched_path = patch_pptx_overflow(pptx_path, high_issues)
            result_after = audit_pptx_deterministic(patched_path)
            write_visual_audit(result_after, WORKSPACE)
            return (
                format_visual_audit(result_after)
                + f"\n  AUTO-PATCHED {len(high_issues)} HIGH issue(s) → saved as {_Path(patched_path).name}"
            )
        write_visual_audit(result, WORKSPACE)
        return format_visual_audit(result)
    except Exception as exc:  # noqa: BLE001
        return f"\n  Visual audit skipped: {exc}"


@tool(parse_docstring=True)
def audit_deck_visual() -> str:
    """Run deterministic visual audit on the rendered out.pptx.

    Checks every slide for title length, bullet density, table overflow, tiny fonts,
    and brand font drift. Writes deck_visual_audit.json. HIGH-severity issues are
    automatically patched (title truncation, bullet trimming) and saved as
    out_patched.pptx. No LLM, no rendering — reads the PPTX XML model directly.
    Call this after create_pptx or generate_ppt_proposal to get a layout QA report.
    """
    pptx_path = WORKSPACE / "out.pptx"
    if not pptx_path.exists():
        return "ERROR: out.pptx not found. Run create_pptx or generate_ppt_proposal first."
    _bump_tool_summary("audit_deck_visual")
    return _visual_audit_note(str(pptx_path))


@tool(parse_docstring=True)
def export_proposal_package(title: str = "") -> str:
    """Assemble the proposal package — manifest + all artifacts — into an export folder.

    Reads workspace stores (deck_plan.json, solution_model.json, decision_log.json,
    findings_log.json, deck_visual_audit.json) and copies the deliverable files
    (out.pptx, out.png, out.drawio, wbs_output.xlsx) into
    workspace/exports/<timestamp>/ together with a manifest.json.

    The manifest records artifact status, slide trace coverage, structure score,
    visual audit result, open findings, and HITL decision count.

    PAUSES for human review: shows the package summary and warns if HIGH findings
    or unresolved visual issues are present before the user sends to the client.

    Args:
        title: Override the project title shown on the manifest (defaults to
               diagram_brief.slide_title or the existing project title).
    """
    try:
        export_dir, manifest = _export_proposal_package(WORKSPACE, title=title)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: could not assemble package: {exc}"

    _bump_tool_summary("export_proposal_package")

    summary = format_manifest(manifest)
    summary += f"\n\nPackage written to: {export_dir}"

    if manifest.open_findings_high:
        summary += (
            "\n\n⛔ BLOCKED: there are HIGH-severity findings open. "
            "Resolve or waive them before sending to the client, "
            "or confirm you accept the risk."
        )
    elif manifest.open_findings:
        summary += (
            f"\n\n⚠ {manifest.open_findings} finding(s) still open — review before sending."
        )
    else:
        summary += "\n\nAll quality gates clear. Ready to send to client."

    return summary


@tool(parse_docstring=True)
def plan_deck(title: str = "", subtitle: str = "", brand: str = "") -> str:
    """Build the traceable BnK proposal storyboard (deck_plan.json) from the CSM.

    Assembles the fixed BnK narrative (Executive Summary -> Proposed Solution ->
    Technical Stack -> Scope -> Project Delivery/Effort/Timeline -> Risks -> Pricing),
    with every slide grounded in CSM entity ids (source_refs). Runs silently (no
    approval). Call this in the ppt_generator subagent BEFORE create_pptx, and BEFORE
    propose_deck_plan presents the storyboard for review.

    Args:
        title: Deck title (falls back to diagram_brief.slide_title).
        subtitle: Subtitle / kicker line.
        brand: Client brand name shown on the cover.
    """
    try:
        _model, plan = _refresh_deck_plan(title, subtitle, brand)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: could not build deck plan: {exc}"
    grounded = sum(1 for s in plan.slides if s.source_refs)
    return (
        f"Wrote deck_plan.json — {len(plan.slides)} slides, {grounded} grounded in the CSM "
        f"(storyboard revision {plan.revision}). Next: propose_deck_plan to approve the narrative."
    )


@tool(parse_docstring=True)
def propose_deck_plan(title: str = "", subtitle: str = "", brand: str = "") -> str:
    """Present the proposal storyboard for the user to approve BEFORE rendering the deck.

    PAUSES for human approval (docx §4.8 / §5.3: approve the narrative & trade-offs
    before the file is built). Builds/refreshes deck_plan.json from the CSM, runs
    validate_deck (traceability / coverage / consistency / evidence — advisory, does
    NOT block), writes deck_qa_result.json, and shows the storyboard outline + findings
    + epistemic summary. After approval, call create_pptx (or generate_ppt_proposal)
    to render the deck from the approved plan.

    Args:
        title: Deck title (falls back to diagram_brief.slide_title).
        subtitle: Subtitle / kicker line.
        brand: Client brand name shown on the cover.
    """
    try:
        model, plan = _refresh_deck_plan(title, subtitle, brand)
    except Exception as exc:  # noqa: BLE001
        return f"Could not build the deck plan: {exc}"

    lines: list[str] = []
    for s in plan.slides:
        refs = ""
        if s.source_refs:
            head = ", ".join(s.source_refs[:6])
            refs = f"  ⟵ {head}" + ("…" if len(s.source_refs) > 6 else "")
        lines.append(f"  {s.slide_no:>2}. [{s.narrative_role}] {s.title or '(cover)'}{refs}")

    record_report_step(
        WORKSPACE,
        "propose_deck_plan",
        summary=f"Proposed deck storyboard: {len(plan.slides)} slides (revision {plan.revision}).",
        data={"slides": [s.model_dump() for s in plan.slides]},
    )
    return (
        "DECK STORYBOARD — review the narrative & trade-offs before the file is rendered:\n"
        + "\n".join(lines)
        + _deck_qa_note(model)
        + _epistemic_note(model)
        + "\n\nApprove to render the deck from this plan, or tell me what to change in the storyboard."
    )


def _web_search_category(topic: str) -> str:
    """Map the caller's `topic` onto a budget category.

    `topic` doubles as both the Tavily recency hint and the budget bucket. Any value
    that isn't a known budget category (e.g. "news", or a stray free-text topic) falls
    into the "general" bucket so it still draws from a real sub-budget.
    """
    t = (topic or "").strip().lower()
    return t if t in WEB_SEARCH_CATEGORY_CAPS else "general"


def _web_search_budget_report(state: dict) -> dict:
    """Per-category used/cap snapshot + total remaining, for tool responses."""
    by_cat = state.get("by_category") or {}
    categories = {
        cat: {"used": int(by_cat.get(cat, 0)), "cap": cap,
              "remaining": max(0, cap - int(by_cat.get(cat, 0)))}
        for cat, cap in WEB_SEARCH_CATEGORY_CAPS.items()
    }
    total_used = int(state.get("calls", 0))
    return {
        "session_cap": WEB_SEARCH_SESSION_CAP,
        "total_used": total_used,
        "total_remaining": max(0, WEB_SEARCH_SESSION_CAP - total_used),
        "by_category": categories,
    }


@tool(parse_docstring=True)
def web_research(query: str, topic: str = "tech_stack") -> str:
    """Run ONE live web search to verify time-sensitive facts via Tavily.

    Returns a synthesized answer plus the top source URLs/snippets as JSON.
    The session has a total budget of WEB_SEARCH_SESSION_CAP searches, split into
    per-stage sub-budgets so research is spread across the pipeline instead of dumped
    into a single step. Pick the `topic` that matches WHY you are searching.

    When to use (batch related questions into ONE rich query each time):
      - "tech_stack"   — managed-service pricing, latest stable versions / EOL dates.
      - "architecture" — reference architectures / patterns for the chosen design.
      - "wbs"          — effort benchmarks / delivery norms for the estimate.
      - "evidence"     — compliance / claim grounding for a client-facing statement.
      - "general"      — anything that doesn't fit the buckets above.
      - "news"         — same as general budget, but biases Tavily toward recency.

    Args:
        query: One focused, fact-seeking question, e.g. "2026 AWS Fargate vCPU and
            RDS Postgres db.t4g.medium monthly pricing us-east-1".
        topic: Budget category AND Tavily recency hint (see list above). Defaults to
            "tech_stack".
    """
    import httpx

    state = _web_search_state()
    state.setdefault("by_category", {})
    calls = int(state.get("calls", 0))
    category = _web_search_category(topic)
    cat_used = int(state["by_category"].get(category, 0))
    cat_cap = WEB_SEARCH_CATEGORY_CAPS[category]

    # Total session budget exhausted.
    if calls >= WEB_SEARCH_SESSION_CAP:
        _bump_tool_summary("web_research_budget_exhausted")
        return json.dumps({
            "status": "BUDGET_EXHAUSTED",
            "query": query,
            "budget": _web_search_budget_report(state),
            "instruction": (
                "No web searches remain this session. Proceed with existing knowledge "
                "and results already gathered; flag any unverified pricing/version as an "
                "assumption in assumptions.confirm_with_customer."
            ),
        }, indent=2)

    # This category's sub-budget is spent, but the session still has room elsewhere.
    if cat_used >= cat_cap:
        report = _web_search_budget_report(state)
        open_cats = [c for c, info in report["by_category"].items() if info["remaining"] > 0]
        _bump_tool_summary("web_research_category_exhausted")
        return json.dumps({
            "status": "CATEGORY_EXHAUSTED",
            "query": query,
            "category": category,
            "budget": report,
            "instruction": (
                f"The '{category}' sub-budget ({cat_cap}) is spent. The session still has "
                f"searches left in: {open_cats or 'none'}. Re-issue with a topic from that "
                "list ONLY if the question genuinely belongs to that stage; otherwise "
                "proceed with existing knowledge."
            ),
        }, indent=2)

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        _bump_tool_summary("web_research_no_key")
        return json.dumps({
            "status": "NO_API_KEY",
            "instruction": "TAVILY_API_KEY not set; skip web research and proceed.",
        }, indent=2)

    # Reserve the call (total + per-category) BEFORE the network request.
    state["calls"] = calls + 1
    state["by_category"][category] = cat_used + 1
    state.setdefault("queries", []).append({"query": query, "category": category})
    _save_web_search_state(state)

    tavily_topic = "news" if (topic or "").strip().lower() == "news" else "general"
    if tavily_topic not in WEB_SEARCH_TAVILY_TOPICS:
        tavily_topic = "general"
    try:
        resp = httpx.post(
            TAVILY_SEARCH_URL,
            json={
                "api_key": api_key,
                "query": query,
                "topic": tavily_topic,
                "search_depth": "advanced",
                "include_answer": "advanced",
                "max_results": 5,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        _bump_tool_summary("web_research_error")
        return json.dumps({
            "status": "ERROR",
            "query": query,
            "error": str(exc)[:300],
            "budget": _web_search_budget_report(state),
            "instruction": "Search failed (still counted). Proceed with existing knowledge.",
        }, indent=2)

    sources = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": (r.get("content", "") or "")[:500],
        }
        for r in (data.get("results") or [])[:5]
    ]
    _bump_tool_summary("web_research", web_search_calls=state["calls"])
    report = _web_search_budget_report(state)
    return json.dumps({
        "status": "OK",
        "query": query,
        "category": category,
        "answer": data.get("answer", ""),
        "sources": sources,
        "budget": report,
        "instruction": (
            "Cite specific numbers/versions from answer/sources in the relevant "
            "artifact, AND when the claim is client-facing (pricing/version/"
            "compliance/reference-architecture) commit it with record_evidence "
            "(pass source_url + supports_entity_ids). Remaining — "
            f"total: {report['total_remaining']}, this stage ('{category}'): "
            f"{report['by_category'][category]['remaining']}."
        ),
    }, indent=2)


@tool(parse_docstring=True)
def record_evidence(
    claim: str,
    source_url: str = "",
    source_type: str = "web",
    quote_or_excerpt: str = "",
    confidence: str = "medium",
    supports_entity_ids: Optional[list[str]] = None,
    freshness_date: str = "",
    supersedes_evidence_id: Optional[str] = None,
) -> str:
    """Persist a grounded claim as a durable evidence record (docx §4.9).

    Use AFTER web_research (or reading a document) to ground a client-facing claim
    — a price, a version/EOL date, a compliance statement, a reference architecture
    — so the proposal can show *why* and an auditor can trace the source. The record
    is appended to `evidence_log.json` and folded into the solution model as an
    Evidence entity with `supports` trace links back to the entities it backs.

    When to use: right after the search/source that established the fact, while the
    URL and excerpt are at hand. Link it to the CSM entities it supports via
    `supports_entity_ids` (e.g. the decision it justifies or the component it sizes).

    Args:
        claim: The single factual statement being grounded, e.g. "AWS Fargate is
            $0.04048/vCPU-hour in us-east-1 (2026)".
        source_url: The URL (or document locator) the claim came from.
        source_type: One of web, documentation, vendor, benchmark, standard, other.
        quote_or_excerpt: A short verbatim span from the source supporting the claim.
        confidence: low, medium, or high — how strongly the source supports the claim.
        supports_entity_ids: CSM entity ids this evidence backs (DEC-/COMP-/REQ-...).
            When an id names a decision, the evidence is added to its evidence_ids.
        freshness_date: The date the source itself reflects (e.g. pricing as-of), if
            known; distinct from when it was fetched.
        supersedes_evidence_id: An older EVD-### this record refreshes/replaces.
    """
    from datetime import datetime, timezone
    from evidence import append_evidence, new_evidence_record, next_seq

    valid_types = {"web", "documentation", "vendor", "benchmark", "standard", "other"}
    stype = (source_type or "web").strip().lower()
    if stype not in valid_types:
        stype = "other"
    conf = (confidence or "medium").strip().lower()
    if conf not in {"low", "medium", "high"}:
        conf = "medium"

    record = new_evidence_record(
        claim=claim,
        seq=next_seq(WORKSPACE),
        source_url=source_url or "",
        source_type=stype,  # type: ignore[arg-type]
        fetched_at=datetime.now(timezone.utc).isoformat(),
        freshness_date=freshness_date or "",
        quote_or_excerpt=quote_or_excerpt or "",
        confidence=conf,  # type: ignore[arg-type]
        supports_entity_ids=list(supports_entity_ids or []),
        supersedes_evidence_id=supersedes_evidence_id,
    )
    append_evidence(record, WORKSPACE)
    total = next_seq(WORKSPACE) - 1
    _bump_tool_summary("record_evidence", evidence_count=total)
    linked = ", ".join(record.supports_entity_ids) or "(no entity link)"
    return (
        f"Recorded {record.id} (confidence={record.confidence}) supporting {linked}. "
        f"{total} evidence record(s) on file; folded into the solution model on next "
        f"build_solution_model."
    )


def _settle_finding(finding_id: str, status: str, note: str, *, action: str) -> str:
    """Set a finding's terminal status + record the human DecisionRecord (docx §4.3)."""
    from datetime import datetime, timezone

    from decisions import append_decision, new_decision_record, next_seq
    from finding_store import set_status

    fid = (finding_id or "").strip()
    if not fid:
        return "Pass the finding_id (SF-xxxx) shown in the CROSS-ARTIFACT CHECK output."
    now = datetime.now(timezone.utc).isoformat()
    updated = set_status(fid, status, reason=note or "", by="agent", at=now, workspace=WORKSPACE)
    if updated is None:
        return (f"No finding {fid} in findings_log.json — re-run the stage or export gate to "
                "refresh the cross-artifact check, then use a live SF-id.")
    # Audit trail: a human DecisionRecord, folded into the CSM on next build_solution_model.
    try:
        rec = new_decision_record(
            "cross_artifact_check",
            action,  # type: ignore[arg-type]
            seq=next_seq(WORKSPACE),
            approver="agent",
            timestamp=now,
            comment=note or "",
            payload={"finding_id": fid},
        )
        append_decision(rec, WORKSPACE)
    except Exception:
        pass
    _bump_tool_summary(action)
    verb = "waived" if status == "waived" else "resolved"
    return (f"Finding {fid} marked {verb}: {note or '(no note)'}. It no longer blocks an export; "
            "re-run the export gate to confirm the verdict clears.")


@tool(parse_docstring=True)
def waive_finding(finding_id: str, reason: str) -> str:
    """Accept a cross-artifact validation finding as a known trade-off (docx §4.3).

    Use when a finding from the CROSS-ARTIFACT CHECK is an intentional, accepted
    decision (a requirement is deliberately deferred, internal-only WBS work is
    expected) rather than a defect to fix. The finding's status becomes `waived` in
    findings_log.json so it stops blocking an export, and a human decision record is
    persisted for the audit trail. Prefer resolve_finding when you actually fixed the
    underlying artifact.

    Args:
        finding_id: The SF-xxxx id shown in the CROSS-ARTIFACT CHECK output.
        reason: Why this finding is accepted as-is — the trade-off being accepted.
    """
    return _settle_finding(finding_id, "waived", reason, action="waive_finding")


@tool(parse_docstring=True)
def resolve_finding(finding_id: str, fix_applied: str) -> str:
    """Mark a cross-artifact validation finding as fixed (docx §4.3).

    Use AFTER you corrected the underlying artifact (added the missing node, mapped
    the requirement, ran the rollup). The finding's status becomes `resolved` so it no
    longer blocks an export, and a human decision record is persisted. If the defect
    genuinely persists it re-appears under a NEW id on the next check.

    Args:
        finding_id: The SF-xxxx id shown in the CROSS-ARTIFACT CHECK output.
        fix_applied: What you changed to fix it.
    """
    return _settle_finding(finding_id, "resolved", fix_applied, action="resolve_finding")


@tool(parse_docstring=True)
def apply_compliance_pack(pack_name: str) -> str:
    """Activate a reusable compliance control pack for this proposal (docx §4 P2, §13.2).

    Maps a standard's controls (encryption, audit logging, access review, …) onto the
    solution: each control becomes a CSM entity linked to the work/components that
    implement it and the risks it mitigates. Required controls that have no
    implementation or no evidence then surface as `compliance` findings in the
    CROSS-ARTIFACT CHECK, so a client claim like "SOC 2 ready" is blocked until it is
    backed by evidence. Call this once the architecture and WBS exist. Available packs:
    generic_security.

    Args:
        pack_name: Name of the pack to activate (e.g. "generic_security").
    """
    from compliance import evidence_gaps, list_packs, load_pack, set_active_pack
    available = list_packs()
    if not load_pack(pack_name):
        return (f"Unknown compliance pack {pack_name!r}. "
                f"Available: {', '.join(available) or '(none)'}.")
    set_active_pack(pack_name, WORKSPACE)
    try:
        model = build_solution_model(WORKSPACE)  # rebuild so controls + findings appear now
        gaps = evidence_gaps(model)
        n_controls = len(model.controls)
    except Exception:
        n_controls, gaps = 0, []
    _bump_tool_summary("apply_compliance_pack")
    gap_note = (f" {len(gaps)} control(s) still need implementation/evidence."
                if gaps else " all controls covered.")
    return (f"Compliance pack '{pack_name}' active: {n_controls} control(s) mapped into the "
            f"solution model.{gap_note} Re-run the export gate to see compliance findings; "
            "attach proof with record_evidence or waive with rationale.")


@tool(parse_docstring=True)
def add_comment(body: str, anchor_entity_id: str = "", role: str = "reviewer") -> str:
    """Attach a review comment to a CSM entity for the audit trail (docx §8.6).

    Anchors a note to a stable entity id (REQ-/COMP-/WBS-/SLIDE-/DEC-…) instead of a
    chat message, so the review thread survives a rename and ships with the proposal
    package. Use to flag an open question, a decision rationale, or a reviewer concern
    against a specific part of the solution.

    Args:
        body: The comment text.
        anchor_entity_id: The CSM entity id the comment is about ("" for a general note).
        role: The commenter's role (architect / pm / reviewer / client).
    """
    from datetime import datetime, timezone
    from comments import append_comment, new_comment_record, next_seq

    rec = new_comment_record(
        body=body,
        seq=next_seq(WORKSPACE),
        anchor_entity_id=(anchor_entity_id or "").strip(),
        author="agent",
        role=(role or "reviewer").strip(),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    append_comment(rec, WORKSPACE)
    _bump_tool_summary("add_comment")
    anchor = f" on {rec.anchor_entity_id}" if rec.anchor_entity_id else ""
    return f"Comment {rec.id} added{anchor} (comment_log.json). Resolve it with resolve_comment({rec.id})."


@tool(parse_docstring=True)
def resolve_comment(comment_id: str) -> str:
    """Mark a review comment as resolved (docx §8.6).

    Args:
        comment_id: The CMT-xxx id of the comment to close.
    """
    from datetime import datetime, timezone
    from comments import resolve_comment as _resolve

    rec = _resolve(comment_id, resolved_by="agent",
                   resolved_at=datetime.now(timezone.utc).isoformat(), workspace=WORKSPACE)
    if rec is None:
        return f"No comment {comment_id!r} found in comment_log.json."
    _bump_tool_summary("resolve_comment")
    return f"Comment {comment_id} marked resolved."


@tool(parse_docstring=True)
def export_to_delivery(system: str, dry_run: bool = True) -> str:
    """Export the WBS work items to a delivery tracker (Jira/Linear/Confluence) (docx §8.6).

    Syncs each CSM work item to one external issue, keyed by its stable id, so a re-run
    creates new items, updates changed ones and skips unchanged ones (idempotent — never
    duplicates). PAUSES for human approval before running (explicit send gate, §12.3).
    Default `dry_run=True` writes a reviewable preview and pushes nothing; set
    `dry_run=False` to actually sync. With no tracker credentials configured a real sync
    is simulated with deterministic ids so the flow is testable.

    Args:
        system: One of jira, linear, confluence.
        dry_run: True (default) = preview only; False = perform the sync.
    """
    sys_l = (system or "").strip().lower()
    if sys_l not in ("jira", "linear", "confluence"):
        return f"Unknown delivery system {system!r}. Use jira, linear, or confluence."
    try:
        model = build_solution_model(WORKSPACE)
    except Exception as exc:  # noqa: BLE001
        return f"Could not build solution model: {exc}"
    if not model.work_items:
        return "No WBS work items to export — run the WBS pipeline first."
    from delivery_export import sync_work_items
    res = sync_work_items(model, sys_l, dry_run=dry_run, workspace=WORKSPACE)  # type: ignore[arg-type]
    _bump_tool_summary("export_to_delivery")
    c = res["counts"]
    mode = "PREVIEW (dry-run)" if res["dry_run"] else "SYNCED"
    tail = (" Preview written to delivery_export_preview.json — set dry_run=false to push."
            if res["dry_run"] else " Mapping saved to delivery_sync_log.json.")
    return (f"Delivery export to {sys_l} [{mode}]: {c['create']} create, {c['update']} update, "
            f"{c['skip']} skip (of {len(model.work_items)} work item(s)).{tail}")


@tool(parse_docstring=True)
def reality_sync(source_path: str) -> str:
    """Compare the design to a real codebase/infra and report drift (docx §5.2).

    "Reality Sync Mode": ingests a source folder (a repo, Terraform, k8s/compose YAML, or
    an OpenAPI spec) into a current-state model and diffs it against the approved design,
    so you can answer "does the proposal match what is actually built?". Writes
    current_state_model.json + drift_report.json and returns a summary: components
    designed-but-not-built, built-but-not-designed (drift), and matched. Read-only — it
    never changes the solution model.

    Args:
        source_path: Path to the repo/infra folder to ingest.
    """
    from pathlib import Path as _Path
    from reality_sync import format_drift, run_reality_sync

    src = _Path(source_path)
    if not src.exists():
        return f"Source path not found: {source_path!r}."
    try:
        report = run_reality_sync(src, WORKSPACE)
    except Exception as exc:  # noqa: BLE001
        return f"Reality sync failed: {exc}"
    _bump_tool_summary("reality_sync")
    return format_drift(report)


@tool(parse_docstring=True)
def export_adr_pack() -> str:
    """Export the decision log as a Markdown ADR pack for the proposal (docx §8.6).

    Renders every recorded decision (options, choice, rationale, approver, evidence,
    review trigger) into `adr_pack.md` so an enterprise engagement ships with an
    auditable Architecture Decision Record set. Call near finalization.
    """
    try:
        from adr_export import write_adr_pack
        path, n = write_adr_pack(WORKSPACE)
    except Exception as exc:  # noqa: BLE001
        return f"ADR export failed: {exc}"
    _bump_tool_summary("export_adr_pack")
    if n == 0:
        return "ADR pack: no decisions recorded yet — nothing to export."
    return f"ADR pack written ({n} decision record(s)) → adr_pack.md."


# ---------------------------------------------------------------------------
# edit_entity — in-place CSM entity patch (docx §5.3 HITL v2)
# ---------------------------------------------------------------------------

_PATCHABLE_FIELDS = frozenset({
    "title", "description", "source", "provenance_note", "status",
    "risk_level", "severity", "mitigation", "rationale", "owner",
    "definition_of_done", "kind", "confidence",
})

_CSM_COLLECTIONS = [
    "requirements", "constraints", "assumptions", "decisions",
    "components", "risks", "work_items", "evidence", "deliverables",
]


@tool(parse_docstring=True)
def edit_entity(entity_id: str, field: str, new_value: str) -> str:
    """Patch a single field on a CSM entity in solution_model.json.

    Reads the current solution model, locates the entity by its stable id,
    applies the field update, copies the old model to solution_model.prev.json
    (enabling query_change_impact), bumps the revision, and writes back.
    Call query_change_impact() immediately after to surface the blast radius.

    Args:
        entity_id: Stable CSM id of the entity to update
            (e.g. REQ-1, COMP-3, WBS-7, DEC-2, ASM-1).
        field: Field name to update. Patchable string fields: title, description,
            source, provenance_note, status, risk_level, severity, mitigation,
            rationale, owner, definition_of_done, kind, confidence.
        new_value: New string value for the field.
    """
    import json as _json
    from csm import SolutionModel
    from csm_adapter import SOLUTION_MODEL_NAME, SOLUTION_MODEL_PREV_NAME

    if field not in _PATCHABLE_FIELDS:
        return (
            f"EDIT_ENTITY: ERROR — field '{field}' is not patchable. "
            f"Allowed: {sorted(_PATCHABLE_FIELDS)}."
        )

    cur_path = WORKSPACE / SOLUTION_MODEL_NAME
    cur_raw = _read_json_file(cur_path, None)
    if cur_raw is None:
        return "EDIT_ENTITY: ERROR — no solution_model.json yet (run the pipeline first)."

    # Find and patch the entity in the raw dict
    old_val = None
    found = False
    for coll in _CSM_COLLECTIONS:
        for item in cur_raw.get(coll, []):
            if item.get("id") == entity_id:
                old_val = item.get(field)
                item[field] = new_value
                found = True
                break
        if found:
            break

    if not found:
        return (
            f"EDIT_ENTITY: ERROR — entity '{entity_id}' not found in solution model. "
            f"Searched collections: {_CSM_COLLECTIONS}."
        )

    # Validate the patched model before writing
    try:
        SolutionModel.model_validate(cur_raw)
    except Exception as exc:  # noqa: BLE001
        return f"EDIT_ENTITY: ERROR — validation failed after patch: {exc}"

    # Snapshot the current file as .prev (enables query_change_impact)
    prev_path = WORKSPACE / SOLUTION_MODEL_PREV_NAME
    prev_path.write_text(cur_path.read_text(encoding="utf-8"), encoding="utf-8")

    # Bump revision and write back
    cur_raw["revision"] = cur_raw.get("revision", 0) + 1
    cur_path.write_text(
        _json.dumps(cur_raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return (
        f"EDIT_ENTITY: {entity_id}.{field} updated "
        f"({repr(old_val)!s} → {repr(new_value)!s}), "
        f"revision bumped to {cur_raw['revision']}. "
        "Call query_change_impact() to see the blast radius."
    )


@tool
def quality_summary() -> str:
    """Compute and return the quality dashboard for the current workspace.

    Reads findings_log.json, decision_log.json, evidence_log.json, and
    solution_model.json, then computes a QualitySnapshot: open/waived/resolved
    findings by dimension and severity, HITL decision counts, evidence coverage
    (% of requirements grounded in at least one evidence record), assumption
    confirmation rate by confidence tier, risk mitigation rate, and a 0-100
    quality score (grade A-F).

    The snapshot is written to quality_snapshot.json in the workspace. Call this
    after any gate to see the current quality health of the solution proposal.
    """
    try:
        snap = build_quality_snapshot(WORKSPACE)
        write_snapshot(snap, WORKSPACE)
        return format_snapshot(snap)
    except Exception as exc:
        return f"QUALITY_SUMMARY: ERROR — {exc}"
