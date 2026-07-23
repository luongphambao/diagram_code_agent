"""propose_business_case: the deterministic ROI/TCO/payback gate (improvement
plan §C, S3). See domain.reporting.business_case for the calculation and why
this is a plain Python function, not a code-interpreter (run_python) call."""

from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import tool

from backends import current_workspace
from domain.reporting.business_case import (
    BusinessCaseInputs,
    auto_implementation_cost_usd,
    auto_operating_cost_usd,
    compute_business_case,
)
from domain.reporting.reporting import record_report_step
from ..schemas.business_case import BusinessCaseAssumptions

_BUSINESS_CASE_FILENAME = "business_case.json"


@tool(args_schema=BusinessCaseAssumptions)
def propose_business_case(
    annual_benefit_usd: float,
    benefit_basis: str,
    implementation_cost_usd: Optional[float] = None,
    annual_operating_cost_usd: Optional[float] = None,
    analysis_horizon_years: int = 3,
    benefit_ramp_pct_by_year: Optional[list[float]] = None,
) -> str:
    """Propose the business case (ROI/TCO/payback) for the user to review and approve.

    Only call this when the user actually wants a financial justification — not on
    every diagram/WBS request. PAUSES for human approval: these figures feed a
    client-facing decision, so a human signs off before they're referenced in a
    report/deck.

    The ROI/TCO/payback ARITHMETIC is always deterministic (domain.reporting.
    business_case.compute_business_case) — you never compute these yourself, only
    state cost/benefit assumptions:

    `implementation_cost_usd` auto-pulls from wbs.json's effort_totals.total_cost_usd
    if omitted — finalize the WBS first, or pass this explicitly to override.
    `annual_operating_cost_usd` auto-pulls from tech_stack.json's
    estimated_total_monthly_cost_usd × 12 if omitted — pass a higher figure if there
    are other recurring costs beyond infrastructure.
    `annual_benefit_usd` and `benefit_basis` are NOT auto-derivable — state a
    grounded estimate (ideally backed by record_evidence), never a guess.
    """
    ws = current_workspace()

    impl_cost = implementation_cost_usd
    impl_source = "explicit"
    if impl_cost is None:
        impl_cost, impl_source = auto_implementation_cost_usd(ws)
    if impl_cost is None:
        return (
            "Cannot compute a business case — no implementation_cost_usd given and no "
            "wbs.json effort_totals to auto-pull it from. Either pass "
            "implementation_cost_usd explicitly, or finalize the WBS first "
            "(wbs_planner: draft_wbs_skeleton -> add_wbs_items -> finalize_wbs)."
        )

    op_cost = annual_operating_cost_usd
    op_source = "explicit"
    if op_cost is None:
        op_cost, op_source = auto_operating_cost_usd(ws)
    if op_cost is None:
        op_cost, op_source = 0.0, "no tech_stack.json cost found — defaulted to $0/yr"

    inputs = BusinessCaseInputs(
        implementation_cost_usd=float(impl_cost),
        annual_operating_cost_usd=float(op_cost),
        annual_benefit_usd=float(annual_benefit_usd),
        analysis_horizon_years=analysis_horizon_years,
        benefit_ramp_pct_by_year=tuple(benefit_ramp_pct_by_year) if benefit_ramp_pct_by_year else None,
    )
    result = compute_business_case(inputs)

    payload = {
        "assumptions": {
            "implementation_cost_usd": impl_cost,
            "implementation_cost_source": impl_source,
            "annual_operating_cost_usd": op_cost,
            "annual_operating_cost_source": op_source,
            "annual_benefit_usd": annual_benefit_usd,
            "benefit_basis": benefit_basis,
            "analysis_horizon_years": result["analysis_horizon_years"],
        },
        **result,
    }
    ws.mkdir(parents=True, exist_ok=True)
    (ws / _BUSINESS_CASE_FILENAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    record_report_step(
        ws,
        "propose_business_case",
        summary=f"Business case: ROI {result['roi_pct']}%, payback "
        f"{result['payback_period_years'] if result['payback_period_years'] is not None else 'N/A'} yr",
        data=payload,
    )

    payback_text = (
        f"{result['payback_period_years']} years"
        if result["payback_period_years"] is not None
        else f"does not pay back within {result['analysis_horizon_years']} years"
    )
    return (
        f"Business case computed — implementation ${impl_cost:,.0f} ({impl_source}), "
        f"opex ${op_cost:,.0f}/yr ({op_source}), benefit ${annual_benefit_usd:,.0f}/yr "
        f"({benefit_basis}).\n"
        f"Over {result['analysis_horizon_years']} years: total cost "
        f"${result['total_cost_usd']:,.0f}, total benefit ${result['total_benefit_usd']:,.0f}, "
        f"net ${result['net_benefit_usd']:,.0f}, ROI {result['roi_pct']}%, payback {payback_text}.\n"
        "Business case APPROVED — safe to reference these figures in a report/deck."
    )
