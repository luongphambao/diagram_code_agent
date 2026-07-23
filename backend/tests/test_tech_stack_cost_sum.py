"""propose_tech_stack's total cost must be a deterministic sum of the per-layer
figures, never the LLM's own self-reported number (improvement plan §C, the
small deterministic fix: 'estimated_total_monthly_cost_usd' is free-floating
LLM prose today, easy to state inconsistently with what it wrote per layer).

Covers both places the total is surfaced:
  - the HITL approval card (session/gate_decisions._card_for) — built from the
    RAW tool-call args, BEFORE propose_tech_stack's body ever runs, since the
    tool is gated via interrupt_on. This is what the human actually approves.
  - the committed tech_stack.json (propose_tech_stack's body, post-approval) —
    read downstream by reporting.py/ppt_reporting.py.
"""

from __future__ import annotations

import contextvars
import json

import backends
import session_state as server
from session.normalize import _sum_layer_costs
from tools import propose_diagram_brief, propose_tech_stack
from tools.schemas.brief import DiagramBrief


def _use_workspace(monkeypatch, tmp_path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends,
        "_current_workspace",
        contextvars.ContextVar("current_workspace", default=tmp_path),
    )


# --- _sum_layer_costs --------------------------------------------------------


def test_sum_layer_costs_adds_min_and_max_across_layers():
    ts = {
        "backend": {"estimated_monthly_cost_usd": {"min_usd": 100, "max_usd": 200}},
        "database": {"estimated_monthly_cost_usd": {"min_usd": 50, "max_usd": 80}},
    }
    assert _sum_layer_costs(ts) == {"min_usd": 150, "max_usd": 280}


def test_sum_layer_costs_skips_layers_without_cost():
    ts = {
        "backend": {"estimated_monthly_cost_usd": {"min_usd": 100, "max_usd": 200}},
        "monitoring": {"estimated_monthly_cost_usd": None},
    }
    assert _sum_layer_costs(ts) == {"min_usd": 100, "max_usd": 200}


def test_sum_layer_costs_returns_none_when_nothing_costed():
    assert _sum_layer_costs({"backend": {"estimated_monthly_cost_usd": None}}) is None
    assert _sum_layer_costs({}) is None
    assert _sum_layer_costs(None) is None


# --- HITL card (pre-approval, raw args) --------------------------------------


def test_card_for_ignores_llm_total_and_computes_from_layers():
    """The model claims $50-$60/mo total but its own layers sum to $150-$280/mo —
    the card must show the computed figure, not the model's assertion."""
    args = {
        "tech_stack": [
            {
                "layer": "backend",
                "choice": "FastAPI",
                "estimated_monthly_cost_usd": {"min_usd": 100, "max_usd": 200},
            },
            {
                "layer": "database",
                "choice": "Postgres",
                "estimated_monthly_cost_usd": {"min_usd": 50, "max_usd": 80},
            },
        ],
        "estimated_total_monthly_cost_usd": {"min_usd": 50, "max_usd": 60},  # wrong, ignored
    }
    card, _step, delta = server._card_for(
        {"action_requests": [{"name": "propose_tech_stack", "args": args}]}, ""
    )
    assert card["estimated_total_monthly_cost_usd"] == {"min_usd": 150, "max_usd": 280}
    assert delta["tech_total_cost"] == {"min_usd": 150, "max_usd": 280}


def test_card_for_total_is_none_when_no_layer_has_cost():
    args = {
        "tech_stack": [{"layer": "backend", "choice": "FastAPI"}],
        "estimated_total_monthly_cost_usd": {"min_usd": 999, "max_usd": 999},  # ignored
    }
    card, _step, _delta = server._card_for(
        {"action_requests": [{"name": "propose_tech_stack", "args": args}]}, ""
    )
    assert card["estimated_total_monthly_cost_usd"] is None


# --- propose_tech_stack body (post-approval, stored tech_stack.json) --------


def test_propose_tech_stack_stores_computed_total_not_llm_total(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    propose_diagram_brief.func(
        brief=DiagramBrief(
            objective="test",
            functional_requirements=["req"],
            non_functional_requirements=[],
        )
    )

    from tools.schemas.tech_stack import CostRange, TechChoice

    propose_tech_stack.func(
        tech_stack=[
            TechChoice(
                layer="backend",
                choice="FastAPI",
                estimated_monthly_cost_usd=CostRange(min_usd=100, max_usd=200),
            ),
            TechChoice(
                layer="database",
                choice="Postgres",
                estimated_monthly_cost_usd=CostRange(min_usd=50, max_usd=80),
            ),
        ],
        estimated_total_monthly_cost_usd=CostRange(
            min_usd=1, max_usd=1
        ),  # deliberately wrong, must be ignored
    )

    stored = json.loads((tmp_path / "tech_stack.json").read_text(encoding="utf-8"))
    assert stored["estimated_total_monthly_cost_usd"] == {"min_usd": 150, "max_usd": 280}
