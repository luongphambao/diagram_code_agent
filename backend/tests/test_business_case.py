"""Deterministic ROI/TCO/payback calculator + propose_business_case gate
(improvement plan §C, S3). Covers the pure math, the auto-pull-from-file
helpers, the tool body, and the HITL approval card (which computes the SAME
figures from raw args before the tool body ever runs — interrupt_on fires
first, same architecture as the tech-stack cost-sum fix)."""

from __future__ import annotations

import contextvars
import json

import backends
import session_state as server
from domain.reporting.business_case import (
    BusinessCaseInputs,
    auto_implementation_cost_usd,
    auto_operating_cost_usd,
    compute_business_case,
)
from tools import propose_business_case


def _use_workspace(monkeypatch, tmp_path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends,
        "_current_workspace",
        contextvars.ContextVar("current_workspace", default=tmp_path),
    )


# --- compute_business_case ---------------------------------------------------


def test_compute_business_case_hand_verified_example():
    """implementation=$100k, opex=$20k/yr, benefit=$80k/yr, 3yr horizon —
    hand-computed: net/yr = $60k, payback partway through year 2, ROI 50%."""
    result = compute_business_case(
        BusinessCaseInputs(
            implementation_cost_usd=100_000,
            annual_operating_cost_usd=20_000,
            annual_benefit_usd=80_000,
            analysis_horizon_years=3,
        )
    )
    assert result["total_cost_usd"] == 160_000
    assert result["total_benefit_usd"] == 240_000
    assert result["net_benefit_usd"] == 80_000
    assert result["roi_pct"] == 50.0
    assert result["payback_period_years"] == 1.67
    assert result["cash_flow_by_year"] == [
        {"year": 0, "net_cash_flow_usd": -100_000, "cumulative_usd": -100_000},
        {"year": 1, "net_cash_flow_usd": 60_000.0, "cumulative_usd": -40_000.0},
        {"year": 2, "net_cash_flow_usd": 60_000.0, "cumulative_usd": 20_000.0},
        {"year": 3, "net_cash_flow_usd": 60_000.0, "cumulative_usd": 80_000.0},
    ]


def test_compute_business_case_never_pays_back_within_horizon():
    """Opex exceeds benefit — cumulative cash flow never recovers. payback must
    be None, not a fabricated number."""
    result = compute_business_case(
        BusinessCaseInputs(
            implementation_cost_usd=50_000,
            annual_operating_cost_usd=30_000,
            annual_benefit_usd=20_000,
            analysis_horizon_years=2,
        )
    )
    assert result["payback_period_years"] is None
    assert result["net_benefit_usd"] < 0
    assert result["roi_pct"] < 0


def test_compute_business_case_applies_ramp():
    """50%% then 100%% ramp over a 2-year horizon must scale the benefit, not
    the opex, per year."""
    result = compute_business_case(
        BusinessCaseInputs(
            implementation_cost_usd=10_000,
            annual_operating_cost_usd=1_000,
            annual_benefit_usd=10_000,
            analysis_horizon_years=2,
            benefit_ramp_pct_by_year=(0.5, 1.0),
        )
    )
    assert result["cash_flow_by_year"][1]["net_cash_flow_usd"] == 4_000.0  # 10000*0.5 - 1000
    assert result["cash_flow_by_year"][2]["net_cash_flow_usd"] == 9_000.0  # 10000*1.0 - 1000
    assert result["total_benefit_usd"] == 15_000.0  # 5000 + 10000


def test_compute_business_case_ramp_shorter_than_horizon_pads_with_last_value():
    result = compute_business_case(
        BusinessCaseInputs(
            implementation_cost_usd=0,
            annual_operating_cost_usd=0,
            annual_benefit_usd=1_000,
            analysis_horizon_years=3,
            benefit_ramp_pct_by_year=(0.5,),
        )
    )
    assert result["benefit_ramp_pct_by_year"] == [0.5, 0.5, 0.5]


def test_compute_business_case_zero_cost_has_no_roi_division_by_zero():
    result = compute_business_case(
        BusinessCaseInputs(
            implementation_cost_usd=0,
            annual_operating_cost_usd=0,
            annual_benefit_usd=0,
            analysis_horizon_years=1,
        )
    )
    assert result["roi_pct"] is None  # total_cost is 0 — no ratio to compute


# --- auto-pull helpers --------------------------------------------------------


def test_auto_implementation_cost_reads_wbs_effort_totals(tmp_path):
    (tmp_path / "wbs.json").write_text(
        json.dumps({"effort_totals": {"total_cost_usd": 42_000}}), encoding="utf-8"
    )
    cost, source = auto_implementation_cost_usd(tmp_path)
    assert cost == 42_000
    assert "wbs.json" in source


def test_auto_implementation_cost_none_when_missing(tmp_path):
    assert auto_implementation_cost_usd(tmp_path) == (None, "")


def test_auto_implementation_cost_none_on_malformed_json(tmp_path):
    (tmp_path / "wbs.json").write_text("{not valid", encoding="utf-8")
    assert auto_implementation_cost_usd(tmp_path) == (None, "")


def test_auto_operating_cost_reads_tech_stack_monthly_times_12(tmp_path):
    (tmp_path / "tech_stack.json").write_text(
        json.dumps({"estimated_total_monthly_cost_usd": {"min_usd": 100, "max_usd": 500}}),
        encoding="utf-8",
    )
    cost, source = auto_operating_cost_usd(tmp_path)
    assert cost == 6_000  # 500 * 12
    assert "tech_stack.json" in source


def test_auto_operating_cost_none_when_missing(tmp_path):
    assert auto_operating_cost_usd(tmp_path) == (None, "")


# --- propose_business_case tool body -----------------------------------------


def test_propose_business_case_auto_pulls_cost_from_workspace_files(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    (tmp_path / "wbs.json").write_text(
        json.dumps({"effort_totals": {"total_cost_usd": 100_000}}), encoding="utf-8"
    )
    (tmp_path / "tech_stack.json").write_text(
        json.dumps({"estimated_total_monthly_cost_usd": {"min_usd": 1000, "max_usd": 1667}}),
        encoding="utf-8",
    )

    out = propose_business_case.func(
        annual_benefit_usd=80_000,
        benefit_basis="Manual review time eliminated, per stakeholder interview.",
        analysis_horizon_years=3,
    )
    assert "ROI 50.0%" in out
    assert "payback 1.67 years" in out

    stored = json.loads((tmp_path / "business_case.json").read_text(encoding="utf-8"))
    assert stored["assumptions"]["implementation_cost_usd"] == 100_000
    assert stored["assumptions"]["implementation_cost_source"] == "wbs.json effort_totals.total_cost_usd"
    assert stored["assumptions"]["annual_operating_cost_usd"] == 20_004  # 1667*12
    assert stored["roi_pct"] is not None


def test_propose_business_case_explicit_cost_overrides_auto_pull(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    (tmp_path / "wbs.json").write_text(
        json.dumps({"effort_totals": {"total_cost_usd": 999_999}}), encoding="utf-8"
    )

    propose_business_case.func(
        annual_benefit_usd=10_000,
        benefit_basis="test",
        implementation_cost_usd=5_000,
        analysis_horizon_years=1,
    )
    stored = json.loads((tmp_path / "business_case.json").read_text(encoding="utf-8"))
    assert stored["assumptions"]["implementation_cost_usd"] == 5_000
    assert stored["assumptions"]["implementation_cost_source"] == "explicit"


def test_propose_business_case_fails_clearly_without_cost_source(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    out = propose_business_case.func(annual_benefit_usd=10_000, benefit_basis="test")
    assert "Cannot compute a business case" in out
    assert not (tmp_path / "business_case.json").exists()


def test_propose_business_case_defaults_opex_to_zero_when_no_tech_stack(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    propose_business_case.func(
        annual_benefit_usd=10_000,
        benefit_basis="test",
        implementation_cost_usd=1_000,
        analysis_horizon_years=1,
    )
    stored = json.loads((tmp_path / "business_case.json").read_text(encoding="utf-8"))
    assert stored["assumptions"]["annual_operating_cost_usd"] == 0.0
    assert "defaulted" in stored["assumptions"]["annual_operating_cost_source"]


def test_propose_business_case_registered_as_gate():
    from tools import GATE_TOOL_NAMES, MAIN_TOOLS, ROLE_GATE_PERMISSIONS, allowed_decisions_for

    assert "propose_business_case" in GATE_TOOL_NAMES
    assert "propose_business_case" in [t.name for t in MAIN_TOOLS]
    assert "approve" in allowed_decisions_for("propose_business_case")
    assert "reject" in allowed_decisions_for("propose_business_case")
    assert "architect" in ROLE_GATE_PERMISSIONS["propose_business_case"]


def test_propose_business_case_survives_the_tool_selector():
    """Regression test: found live — a gate tool not in
    _MAIN_TOOL_SELECTOR_ALWAYS_INCLUDE can be silently dropped by the separate
    LLM-driven tool-selection pass, making the gate unreachable even though it's
    registered in MAIN_TOOLS/GATE_TOOL_NAMES."""
    from agent.constants import _MAIN_TOOL_SELECTOR_ALWAYS_INCLUDE

    assert "propose_business_case" in _MAIN_TOOL_SELECTOR_ALWAYS_INCLUDE


def test_propose_business_case_survives_the_phase_tool_filter():
    """Regression test: found live — PhaseToolFilterMiddleware statically trims
    MAIN_TOOLS down to a per-phase allowlist (_PHASE_TOOLS) BEFORE the LLM
    tool-selector even runs. A tool missing from every phase's set is stripped
    out of every model call regardless of always_include, and the model reports
    the tool as simply "not available" this session. Must appear in every phase
    where a business case is plausible (blueprint onward — not "intake", too
    early for any cost figures to exist)."""
    from agent.middleware.phase_filter import _PHASE_TOOLS

    for phase in ("blueprint", "draw", "wbs", "ppt", "report"):
        assert "propose_business_case" in _PHASE_TOOLS[phase], phase


# --- follow-up detection + workspace preservation ----------------------------


def test_is_business_case_followup_detection():
    from session.followups import _is_business_case_followup

    assert _is_business_case_followup("I need a business case for this")
    assert _is_business_case_followup("what's the ROI on this?")
    assert _is_business_case_followup("tính payback period giúp tôi")
    assert _is_business_case_followup("cần phân tích ROI cho khách hàng")
    assert not _is_business_case_followup("please add redis to the diagram")


def test_business_case_preserve_keeps_artifacts_when_solution_exists():
    from session.followups import _business_case_preserve

    assert (
        _business_case_preserve(
            "I need a business case (ROI/TCO/payback)", solution_exists=True, attached=False
        )
        is True
    )


def test_business_case_preserve_does_not_fire_without_solution_or_with_attachment():
    from session.followups import _business_case_preserve

    # No upstream solution yet -> nothing to preserve.
    assert _business_case_preserve("I need a business case", solution_exists=False, attached=False) is False
    # A freshly attached document is new-project intake, never a business-case follow-up.
    assert _business_case_preserve("I need a business case", solution_exists=True, attached=True) is False
    # Unrelated message never preserves via this path.
    assert _business_case_preserve("add redis to the diagram", solution_exists=True, attached=False) is False


# --- HITL card (pre-approval, computed from raw args) -------------------------


def test_card_for_computes_business_case_before_approval(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    (tmp_path / "wbs.json").write_text(
        json.dumps({"effort_totals": {"total_cost_usd": 100_000}}), encoding="utf-8"
    )
    args = {
        "annual_benefit_usd": 80_000,
        "benefit_basis": "test",
        "annual_operating_cost_usd": 20_000,
        "analysis_horizon_years": 3,
    }
    card, step, delta = server._card_for(
        {"action_requests": [{"name": "propose_business_case", "args": args}]}, ""
    )
    assert step == "awaiting_business_case"
    assert card["type"] == "business_case_approval"
    assert card["implementation_cost_usd"] == 100_000
    assert card["implementation_cost_source"] == "wbs.json effort_totals.total_cost_usd"
    assert card["computed"]["roi_pct"] == 50.0
    assert card["computed"]["payback_period_years"] == 1.67
    assert delta["business_case_computed"]["roi_pct"] == 50.0


def test_card_for_business_case_computed_is_none_without_cost_source(tmp_path, monkeypatch):
    _use_workspace(monkeypatch, tmp_path)
    args = {"annual_benefit_usd": 80_000, "benefit_basis": "test"}
    card, _step, _delta = server._card_for(
        {"action_requests": [{"name": "propose_business_case", "args": args}]}, ""
    )
    assert card["computed"] is None
    assert card["implementation_cost_usd"] is None
