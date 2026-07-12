"""Technology-stack proposal schemas: TechChoice, SolutionAssumptions, and friends."""

from __future__ import annotations

from typing import Optional

from pydantic import AliasChoices, BaseModel, Field

from .coercion import CoercingModel


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
    risk: str = Field(
        validation_alias=AliasChoices("risk", "description"),
        description="the risk itself, e.g. 'vendor lock-in on managed DB'",
    )
    mitigation: str = ""


class ScalingPhase(CoercingModel):
    phase: str
    trigger: str = ""
    changes: list[str] = Field(default_factory=list)
    est_monthly_cost_usd: Optional[CostRange] = None


class TechChoice(CoercingModel):
    """One layer of the recommended technology stack."""
    layer: str = Field(description="e.g. frontend|backend|database|auth|infra|monitoring|networking|security|cache|queue|cdn|search|storage|ci_cd|analytics|ai_ml|integration")
    choice: str = Field(description="the specific technology chosen for this layer")
    rationale: str = Field("", description="1-2 sentence reason tied to the requirements")
    cost_tier: str = Field("$$", description="relative cost: $=low, $$=medium, $$$=high")
    decision_criteria: Optional[TechCriteria] = Field(default=None, description="1-5 scores on cost/ops_complexity/scalability/vendor_lockin/team_fit")
    alternatives: list[TechAlternative] = Field(default_factory=list, description="rejected alternatives with why_rejected")
    estimated_monthly_cost_usd: Optional[CostRange] = Field(default=None, description="USD/month cost range for this layer")
    capacity_sizing: str = Field("", description="instance type/count with sizing math, e.g. '2× Fargate 0.5vCPU autoscale 2-6 for ~150 RPS'")
    performance_target: str = Field("", description="measurable NFR target, e.g. 'p99 ≤ 120ms at 150 RPS'")
    risks: list[TechRisk] = Field(default_factory=list, description="1-2 risks with mitigation")


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
