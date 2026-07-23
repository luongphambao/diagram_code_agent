"""propose_business_case args schema (improvement plan §C, S3)."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from .coercion import CoercingModel


class BusinessCaseAssumptions(CoercingModel):
    """Cost/benefit assumptions for a deterministic ROI/TCO/payback calculation.

    Only `annual_benefit_usd` and `benefit_basis` are genuinely up to the agent to
    estimate — the cost figures auto-pull from wbs.json/tech_stack.json when omitted,
    and the ROI/TCO/payback ARITHMETIC connecting all of these is always computed by
    domain.reporting.business_case.compute_business_case, never asserted by the model.
    """

    annual_benefit_usd: float = Field(
        ge=0,
        description="Estimated yearly benefit/savings/revenue uplift in USD — a "
        "grounded business estimate, ideally backed by record_evidence, NOT a guess.",
    )
    benefit_basis: str = Field(
        description="1-2 sentences: what this benefit represents and where the "
        "estimate comes from, e.g. 'X hours/week manual review eliminated at "
        "$Y/hour, per stakeholder interview'.",
    )
    implementation_cost_usd: Optional[float] = Field(
        default=None,
        ge=0,
        description="One-time build cost. Omit to auto-pull from wbs.json's "
        "effort_totals.total_cost_usd (finalize the WBS first) — only pass this "
        "explicitly to override.",
    )
    annual_operating_cost_usd: Optional[float] = Field(
        default=None,
        ge=0,
        description="Recurring yearly opex. Omit to auto-pull from tech_stack.json's "
        "estimated_total_monthly_cost_usd × 12 — pass a higher figure if there are "
        "other recurring costs (support staff, licenses) beyond infrastructure.",
    )
    analysis_horizon_years: int = Field(default=3, ge=1, le=10)
    benefit_ramp_pct_by_year: list[float] = Field(
        default_factory=list,
        description="Optional phased ramp-up, e.g. [0.5, 0.8, 1.0] for a 3-year "
        "horizon where the benefit is only 50% realized in year 1. Defaults to 100% "
        "every year when omitted.",
    )
