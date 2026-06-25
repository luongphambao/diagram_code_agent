"""Regression tests for mimo's non-standard tool-arg payloads on propose_tech_stack.

mimo (Xiaomi MiMo, OpenAI-compatible) emits array-typed fields as numeric-keyed
objects ({"0":…,"1":…}) or as null/{} instead of JSON arrays, occasionally emits
integer scores outside their declared range, and sometimes serializes a whole nested
object/array as a JSON-encoded string. CoercingModel + _mimo_coerce_before absorb
these so the tool validates instead of raising a ValidationError.
"""

import json

from tools import CostRange, ProposeTechStackArgs, TechCriteria


def _layer(name: str = "frontend") -> dict:
    return {
        "layer": name,
        "choice": "Chromium Browser Extension (Manifest V3)",
        "rationale": "Native browser integration for web automation.",
    }


def test_tech_stack_numeric_keyed_dict_coerced_to_list():
    args = ProposeTechStackArgs.model_validate(
        {"tech_stack": {"0": _layer("frontend"), "1": _layer("backend")}}
    )
    assert [t.layer for t in args.tech_stack] == ["frontend", "backend"]


def test_scaling_roadmap_empty_dict_and_numeric_dict():
    empty = ProposeTechStackArgs.model_validate(
        {"tech_stack": [_layer()], "scaling_roadmap": {}}
    )
    assert empty.scaling_roadmap == []

    one = ProposeTechStackArgs.model_validate(
        {
            "tech_stack": [_layer()],
            "scaling_roadmap": {"0": {"phase": "Phase 1 — MVP"}},
        }
    )
    assert len(one.scaling_roadmap) == 1
    assert one.scaling_roadmap[0].phase == "Phase 1 — MVP"


def test_out_of_range_decision_criteria_clamped():
    layer = _layer()
    layer["decision_criteria"] = {"cost": 0, "vendor_lockin": 9}
    args = ProposeTechStackArgs.model_validate({"tech_stack": [layer]})
    crit = args.tech_stack[0].decision_criteria
    assert crit.cost == 1          # clamped up to ge=1
    assert crit.vendor_lockin == 5  # clamped down to le=5


def test_tech_criteria_direct_clamp():
    crit = TechCriteria.model_validate({"cost": -3, "scalability": 12, "team_fit": 3})
    assert crit.cost == 1
    assert crit.scalability == 5
    assert crit.team_fit == 3       # in-range value untouched


def test_negative_cost_clamped_to_zero():
    cr = CostRange.model_validate({"min_usd": -5, "max_usd": 200})
    assert cr.min_usd == 0
    assert cr.max_usd == 200


def test_nested_alternatives_and_risks_numeric_dicts():
    layer = _layer()
    layer["alternatives"] = {"0": {"name": "React Native", "why_rejected": "fragile"}}
    layer["risks"] = {"0": {"risk": "OS suspends background work"}}
    args = ProposeTechStackArgs.model_validate({"tech_stack": [layer]})
    tc = args.tech_stack[0]
    assert tc.alternatives[0].name == "React Native"
    assert tc.risks[0].risk == "OS suspends background work"


def test_well_formed_payload_unchanged():
    layer = _layer()
    layer.update(
        {
            "cost_tier": "$$",
            "decision_criteria": {"cost": 2, "ops_complexity": 2, "scalability": 5,
                                  "vendor_lockin": 1, "team_fit": 4},
            "alternatives": [{"name": "React Native", "why_rejected": "fragile"}],
            "estimated_monthly_cost_usd": {"min_usd": 0, "max_usd": 80},
            "risks": [{"risk": "plugin drift", "mitigation": "pin versions"}],
        }
    )
    args = ProposeTechStackArgs.model_validate(
        {
            "tech_stack": [layer],
            "estimated_total_monthly_cost_usd": {"min_usd": 580, "max_usd": 1760},
        }
    )
    tc = args.tech_stack[0]
    assert tc.decision_criteria.scalability == 5
    assert tc.estimated_monthly_cost_usd.max_usd == 80
    assert args.estimated_total_monthly_cost_usd.min_usd == 580


def test_assumptions_passed_as_json_string():
    """mimo serialized the whole `assumptions` object as a JSON string — the exact
    failure from the bug report. It must be decoded into SolutionAssumptions."""
    assumptions = {
        "budget_tier": "$$",
        "monthly_budget_range_usd": {"min_usd": 500, "max_usd": 2000},
        "users": {"mau": 50, "dau": 20, "peak_concurrent": 10, "peak_rps": 50},
        "data": {"initial_gb": 10, "growth_gb_per_month": 5,
                 "read_write_ratio": "80:20 read-heavy"},
    }
    args = ProposeTechStackArgs.model_validate(
        {"tech_stack": [_layer()], "assumptions": json.dumps(assumptions)}
    )
    assert args.assumptions is not None
    assert args.assumptions.budget_tier == "$$"
    assert args.assumptions.monthly_budget_range_usd.min_usd == 500
    assert args.assumptions.users.mau == 50
    assert args.assumptions.data.read_write_ratio == "80:20 read-heavy"


def test_tech_stack_passed_as_json_string_of_list():
    args = ProposeTechStackArgs.model_validate(
        {"tech_stack": json.dumps([_layer("frontend"), _layer("backend")])}
    )
    assert [t.layer for t in args.tech_stack] == ["frontend", "backend"]


def test_scaling_roadmap_json_string_of_numeric_dict():
    """JSON string that decodes to a numeric-keyed dict → parsed then dict→list."""
    args = ProposeTechStackArgs.model_validate(
        {
            "tech_stack": [_layer()],
            "scaling_roadmap": json.dumps({"0": {"phase": "Phase 1 — MVP"}}),
        }
    )
    assert len(args.scaling_roadmap) == 1
    assert args.scaling_roadmap[0].phase == "Phase 1 — MVP"


def test_genuine_string_field_not_json_parsed():
    """A real str field whose value happens to look JSON-ish must be left untouched,
    not decoded — guards against over-eager parsing."""
    layer = _layer()
    layer["rationale"] = '{"looks": "like json"} but is actually prose'
    args = ProposeTechStackArgs.model_validate({"tech_stack": [layer]})
    assert args.tech_stack[0].rationale == '{"looks": "like json"} but is actually prose'
