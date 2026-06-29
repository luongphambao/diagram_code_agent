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
from csm_adapter import build_solution_model
from findings import DiagramFinding, format_critique, prune, verdict_for
from solution_validator import validate_solution
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
    return "\n\n".join(result_parts)


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
    """Render the CSM's epistemic split (docx §4.2) as a compact, display-only block.

    Shows what is known vs. what still needs a human: confirmed facts, pending
    assumptions (flagged for customer confirmation), open decisions, and hard
    constraints. Empty sections are omitted. This is surfacing only — there is no
    accept/risk interrupt tool yet (HITL v2 is out of scope).
    """
    try:
        summ = model.epistemic_summary()
    except Exception:
        return ""
    sections = [
        ("Known facts", [f["statement"] for f in summ["known_facts"]]),
        ("Assumptions (needs customer confirmation)",
         [a["statement"] for a in summ["assumptions_needing_confirmation"]]),
        ("Open decisions", [d["title"] for d in summ["open_decisions"]]),
        ("Constraints", [f'{c["statement"]} [{c["kind"]}]' for c in summ["constraints"]]),
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
    return "\n\nEPISTEMIC SUMMARY (display-only):\n" + "\n".join(lines)


def _solution_gate_note() -> str:
    """Run the cross-artifact validator + refresh trace_links.json before an export.

    Warnings-first: never blocks the export, but appends any cross-artifact
    contradictions (unmapped requirement, dangling edge, zero-effort WBS, orphan
    task, missing decisions) plus an epistemic summary so the agent/user sees drift
    and open assumptions before the deck/report leaves the building. Promote to
    blocking by passing block=True once the rules have proven stable in real runs.
    """
    try:
        model = build_solution_model(WORKSPACE)   # materialize/refresh the CSM projection
        write_trace_links(WORKSPACE)
        findings, summary = validate_solution(WORKSPACE, block=False)
    except Exception:
        return ""
    csm_note = (
        f"\n\nSOLUTION MODEL — revision {model.revision}: "
        f"{len(model.requirements)} req, {len(model.components)} component, "
        f"{len(model.work_items)} task, {len(model.trace_links)} trace link(s) "
        "(solution_model.json)."
    )
    csm_note += _epistemic_note(model)
    if not findings:
        return csm_note
    return csm_note + "\n\nCROSS-ARTIFACT CHECK — " + summary


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
    msg += _solution_gate_note()
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
    msg += _solution_gate_note()
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
            "artifact (rationale, cost estimate, evidence record). Remaining — "
            f"total: {report['total_remaining']}, this stage ('{category}'): "
            f"{report['by_category'][category]['remaining']}."
        ),
    }, indent=2)
