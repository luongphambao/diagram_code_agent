"""Deterministic ROI / TCO / payback calculator (improvement plan §C, S3).

Audit finding this closes: there was no ROI/payback/TCO computation anywhere in
the repo — business-case figures (savings, ROI multiples, payback periods) were
pure LLM prose, free to state a plausible-looking number independent of the
cost/benefit assumptions stated alongside it (the same class of bug the
tech-stack cost-sum fix closed for `estimated_total_monthly_cost_usd`).

Scope: this module is ONLY the arithmetic. The underlying BUSINESS ASSUMPTIONS
(implementation cost, recurring opex, expected annual benefit) still come from
the agent — `annual_benefit_usd` in particular is inherently not derivable from
the diagram/WBS and should be a grounded estimate (ideally backed by
`record_evidence`), not invented. What this module guarantees is that once
those assumptions are stated, the ROI/TCO/payback figures connecting them can
never be miscounted or drift from what the assumptions actually imply.

Deliberately NOT a code-interpreter (`run_python`) use case — the input is a
handful of scalars, not a dataset needing filter/scale/reshape, so a plain
unit-tested Python function (same pattern as `domain.wbs.wbs_effort`) is the
right tool, not sandboxed code execution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class BusinessCaseInputs:
    """Cost/benefit assumptions for one business-case calculation."""

    implementation_cost_usd: float
    annual_operating_cost_usd: float
    annual_benefit_usd: float
    analysis_horizon_years: int = 3
    # e.g. (0.5, 0.8, 1.0) for a 3-year horizon where the benefit only ramps to
    # full realization by year 3. Defaults to 100% every year when omitted.
    benefit_ramp_pct_by_year: Optional[tuple[float, ...]] = None


def compute_business_case(inputs: BusinessCaseInputs) -> dict:
    """Compute the year-by-year cash flow, TCO, total benefit, ROI%, and payback
    period for ``inputs``. Pure function — same inputs always produce the same
    output, no I/O, no randomness.

    ``payback_period_years`` is ``None`` when cumulative cash flow never crosses
    zero within the horizon (the investment does not pay back in the given
    timeframe) — never a fabricated number for an investment that doesn't pay off.
    """
    horizon = max(1, int(inputs.analysis_horizon_years))
    ramp = list(inputs.benefit_ramp_pct_by_year) if inputs.benefit_ramp_pct_by_year else [1.0] * horizon
    if len(ramp) < horizon:
        ramp = ramp + [ramp[-1] if ramp else 1.0] * (horizon - len(ramp))
    ramp = ramp[:horizon]

    cash_flow_by_year: list[dict] = []
    cumulative = -inputs.implementation_cost_usd
    cash_flow_by_year.append(
        {
            "year": 0,
            "net_cash_flow_usd": round(-inputs.implementation_cost_usd, 2),
            "cumulative_usd": round(cumulative, 2),
        }
    )

    payback_period_years: float | None = None
    prev_cumulative = cumulative
    for year_idx, pct in enumerate(ramp, start=1):
        benefit = inputs.annual_benefit_usd * pct
        net = benefit - inputs.annual_operating_cost_usd
        cumulative += net
        cash_flow_by_year.append(
            {"year": year_idx, "net_cash_flow_usd": round(net, 2), "cumulative_usd": round(cumulative, 2)}
        )
        if payback_period_years is None and prev_cumulative < 0 <= cumulative:
            # Linear interpolation within this year's cash flow to find the
            # fractional crossing point, rather than rounding to a whole year.
            frac = (-prev_cumulative / net) if net else 0.0
            payback_period_years = round((year_idx - 1) + frac, 2)
        prev_cumulative = cumulative

    total_operating_cost = inputs.annual_operating_cost_usd * horizon
    total_cost = inputs.implementation_cost_usd + total_operating_cost
    total_benefit = sum(inputs.annual_benefit_usd * p for p in ramp)
    net_benefit = total_benefit - total_cost
    roi_pct = (net_benefit / total_cost * 100) if total_cost > 0 else None

    return {
        "cash_flow_by_year": cash_flow_by_year,
        "total_cost_usd": round(total_cost, 2),
        "total_benefit_usd": round(total_benefit, 2),
        "net_benefit_usd": round(net_benefit, 2),
        "roi_pct": round(roi_pct, 1) if roi_pct is not None else None,
        "payback_period_years": payback_period_years,
        "analysis_horizon_years": horizon,
        "benefit_ramp_pct_by_year": ramp,
    }


def auto_implementation_cost_usd(workspace: Path) -> tuple[Optional[float], str]:
    """Pull the one-time implementation cost from an already-finalized wbs.json,
    so the agent never has to restate a number that's already been computed
    (same principle as the WBS re-estimate / tech-stack cost-sum fixes: don't
    make the model retype a figure that already exists in a file)."""
    path = Path(workspace) / "wbs.json"
    if not path.exists():
        return None, ""
    try:
        wbs = json.loads(path.read_text(encoding="utf-8"))
        total = (wbs.get("effort_totals") or {}).get("total_cost_usd")
        if total:
            return float(total), "wbs.json effort_totals.total_cost_usd"
    except Exception:  # noqa: BLE001
        pass
    return None, ""


def auto_operating_cost_usd(workspace: Path) -> tuple[Optional[float], str]:
    """Pull recurring annual opex from an already-approved tech_stack.json
    (monthly cost × 12, conservative max_usd figure)."""
    path = Path(workspace) / "tech_stack.json"
    if not path.exists():
        return None, ""
    try:
        ts = json.loads(path.read_text(encoding="utf-8"))
        total = ts.get("estimated_total_monthly_cost_usd")
        if isinstance(total, dict) and total.get("max_usd") is not None:
            return float(
                total["max_usd"]
            ) * 12, "tech_stack.json estimated_total_monthly_cost_usd.max_usd × 12"
    except Exception:  # noqa: BLE001
        pass
    return None, ""
