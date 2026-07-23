"""Technology-stack proposal schemas: TechChoice, SolutionAssumptions, and friends."""

from __future__ import annotations

import re
from typing import Optional

from pydantic import AliasChoices, Field, model_validator

from .coercion import CoercingModel


def _cost_range_from_scalar(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        n = max(0, int(value))
        return {"min_usd": n, "max_usd": n}
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    numbers: list[int] = []
    for raw, suffix in re.findall(r"(\d+(?:\.\d+)?)\s*([kKmM]?)", text.replace(",", "")):
        n = float(raw)
        if suffix.lower() == "k":
            n *= 1_000
        elif suffix.lower() == "m":
            n *= 1_000_000
        numbers.append(max(0, int(n)))
    if not numbers:
        return None
    return {"min_usd": min(numbers), "max_usd": max(numbers)}


def _first_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if not isinstance(value, str):
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*([kKmM]?)", value.replace(",", ""))
    if not match:
        return None
    n = float(match.group(1))
    suffix = match.group(2).lower()
    if suffix == "k":
        n *= 1_000
    elif suffix == "m":
        n *= 1_000_000
    return max(0, int(n))


class TechCriteria(CoercingModel):
    """1–5 scoring dimensions for a technology choice."""

    cost: int = Field(3, ge=1, le=5, description="1=very low cost, 5=very high cost")
    ops_complexity: int = Field(3, ge=1, le=5, description="1=simple to operate, 5=high operational burden")
    scalability: int = Field(3, ge=1, le=5, description="1=limited, 5=highly scalable")
    vendor_lockin: int = Field(3, ge=1, le=5, description="1=fully portable, 5=deeply vendor-locked")
    team_fit: int = Field(3, ge=1, le=5, description="1=unfamiliar to team, 5=strong team expertise")

    @model_validator(mode="before")
    @classmethod
    def _coerce_scorecard_list(cls, values):
        if not isinstance(values, list):
            return values
        out: dict[str, int] = {}
        for item in values:
            if not isinstance(item, dict):
                continue
            criterion = str(item.get("criterion") or item.get("name") or "").lower()
            score = _first_int(item.get("score"))
            if score is None:
                continue
            if "cost" in criterion:
                out["cost"] = score
            elif "ops" in criterion or "operation" in criterion or "simplicity" in criterion:
                out["ops_complexity"] = score
            elif "scal" in criterion or "capacity" in criterion:
                out["scalability"] = score
            elif "lock" in criterion or "vendor" in criterion or "portable" in criterion:
                out["vendor_lockin"] = score
            elif "team" in criterion or "skill" in criterion or "expertise" in criterion:
                out["team_fit"] = score
        return out


class TechAlternative(CoercingModel):
    """An alternative technology with rejection rationale and optional scoring."""

    name: str = Field(description="technology name")
    why_rejected: str = Field(
        "", description="one sentence: why this alternative was not chosen for this context"
    )
    criteria: Optional[TechCriteria] = Field(
        default=None, description="optional 1-5 scores for this alternative"
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_shorthand(cls, values):
        if isinstance(values, str):
            return {"name": values}
        if isinstance(values, dict) and not values.get("name"):
            for alias in ("technology", "choice", "alternative", "title", "label"):
                if values.get(alias):
                    return {**values, "name": values[alias]}
            return {**values, "name": "Alternative"}
        return values


class CostRange(CoercingModel):
    """Assumption-based monthly cost estimate in USD (always a range)."""

    min_usd: int = Field(0, ge=0, validation_alias=AliasChoices("min_usd", "min"))
    max_usd: int = Field(0, ge=0, validation_alias=AliasChoices("max_usd", "max"))

    @model_validator(mode="before")
    @classmethod
    def _coerce_scalar_range(cls, values):
        return _cost_range_from_scalar(values)


class UserScaleAssumptions(CoercingModel):
    mau: Optional[int] = None
    dau: Optional[int] = None
    peak_concurrent: Optional[int] = None
    peak_rps: Optional[int] = None
    growth_rate_yoy_pct: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_shorthand(cls, values):
        if isinstance(values, str):
            return {"peak_concurrent": _first_int(values)}
        return values


class DataAssumptions(CoercingModel):
    initial_gb: Optional[int] = None
    growth_gb_per_month: Optional[int] = None
    read_write_ratio: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_shorthand(cls, values):
        if isinstance(values, str):
            return {"initial_gb": _first_int(values)}
        return values


class TeamAssumptions(CoercingModel):
    size: Optional[int] = None
    skill_level: str = ""
    devops_maturity: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_shorthand(cls, values):
        if isinstance(values, str):
            return {"size": _first_int(values), "skill_level": values}
        return values


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

    @model_validator(mode="before")
    @classmethod
    def _coerce_provider_aliases(cls, values):
        if not isinstance(values, dict):
            return values
        out = dict(values)
        if isinstance(out.get("users"), str):
            out["users"] = {"peak_concurrent": _first_int(out["users"])}
        if out.get("users") is None and out.get("peak_rps") is not None:
            out["users"] = {}
        if isinstance(out.get("users"), dict) and out.get("peak_rps") is not None:
            out["users"].setdefault("peak_rps", _first_int(out.get("peak_rps")))
        if out.get("data") is None and out.get("data_volume") is not None:
            out["data"] = out.get("data_volume")
        if out.get("team") is None and out.get("team_size") is not None:
            out["team"] = out.get("team_size")
        return out


class TechRisk(CoercingModel):
    risk: str = Field(
        validation_alias=AliasChoices("risk", "description"),
        description="the risk itself, e.g. 'vendor lock-in on managed DB'",
    )
    mitigation: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_shorthand(cls, values):
        if isinstance(values, str):
            return {"risk": values}
        if isinstance(values, dict) and not values.get("risk") and not values.get("description"):
            for alias in ("title", "name", "issue"):
                if values.get(alias):
                    return {**values, "risk": values[alias]}
        return values


class ScalingPhase(CoercingModel):
    phase: str
    trigger: str = ""
    changes: list[str] = Field(default_factory=list)
    est_monthly_cost_usd: Optional[CostRange] = None


class TechChoice(CoercingModel):
    """One layer of the recommended technology stack."""

    layer: str = Field(
        description="e.g. frontend|backend|database|auth|infra|monitoring|networking|security|cache|queue|cdn|search|storage|ci_cd|analytics|ai_ml|integration"
    )
    choice: str = Field(description="the specific technology chosen for this layer")
    rationale: str = Field("", description="1-2 sentence reason tied to the requirements")
    cost_tier: str = Field("$$", description="relative cost: $=low, $$=medium, $$$=high")
    decision_criteria: Optional[TechCriteria] = Field(
        default=None, description="1-5 scores on cost/ops_complexity/scalability/vendor_lockin/team_fit"
    )
    alternatives: list[TechAlternative] = Field(
        default_factory=list, description="rejected alternatives with why_rejected"
    )
    estimated_monthly_cost_usd: Optional[CostRange] = Field(
        default=None, description="USD/month cost range for this layer"
    )
    capacity_sizing: str = Field(
        "",
        description="instance type/count with sizing math, e.g. '2× Fargate 0.5vCPU autoscale 2-6 for ~150 RPS'",
    )
    performance_target: str = Field("", description="measurable NFR target, e.g. 'p99 ≤ 120ms at 150 RPS'")
    risks: list[TechRisk] = Field(default_factory=list, description="1-2 risks with mitigation")


class ProposeTechStackArgs(CoercingModel):
    """Args wrapper for propose_tech_stack."""

    tech_stack: list[TechChoice] = Field(
        description="one entry per layer; cover the core layers (frontend, backend, "
        "database, auth, infra, monitoring, networking, security)",
    )
    assumptions: Optional[SolutionAssumptions] = Field(
        default=None,
        description="sizing basis: budget, user scale, data, team, compliance",
    )
    scaling_roadmap: Optional[list[ScalingPhase]] = Field(
        default=None,
        description="2-3 phase roadmap with measurable triggers",
    )
    estimated_total_monthly_cost_usd: Optional[CostRange] = Field(
        default=None,
        description="ignored — always computed as the deterministic sum of each "
        "layer's estimated_monthly_cost_usd; no need to fill this in",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_wrapped_stack(cls, values):
        if not isinstance(values, dict):
            return values
        stack = values.get("tech_stack")
        if isinstance(stack, dict) and "layers" in stack:
            stack = stack.get("layers")
        if isinstance(stack, dict):
            items = []
            for layer, info in stack.items():
                if isinstance(info, dict):
                    item = dict(info)
                    item.setdefault("layer", str(layer))
                    items.append(item)
                else:
                    items.append({"layer": str(layer), "choice": str(info)})
            values = {**values, "tech_stack": items}
        total = values.get("estimated_total_monthly_cost_usd")
        coerced_total = _cost_range_from_scalar(total)
        if coerced_total is not total:
            values = {**values, "estimated_total_monthly_cost_usd": coerced_total}
        return values
