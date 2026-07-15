"""Tests for score_deck_structure() in deck.py."""

import pytest

from memory.stores.csm import SolutionModel
from memory.stores.csm_adapter import from_artifacts
from domain.deck.deck import DeckPlan, SlideSpec, build_deck_plan, score_deck_structure


def _minimal_model() -> SolutionModel:
    return from_artifacts(
        brief={
            "objective": "Test platform",
            "functional_requirements": ["User login", "Dashboard"],
            "non_functional_requirements": ["99.9% uptime"],
        },
        blueprint={
            "nodes": [{"id": "api", "label": "API", "cluster": "svc"}],
            "clusters": [{"id": "svc", "label": "Service"}],
            "key_decisions": ["Use FastAPI"],
        },
        wbs={
            "items": [{"id": "1.1", "name": "Setup", "total_md": 10}],
            "effort_totals": {"total_mandays": 10, "total_manmonths": 0.5},
            "timeline": {"weeks": 4, "months": 1, "sprints": 2},
        },
    )


def test_clean_plan_scores_high():
    model = _minimal_model()
    plan = build_deck_plan(model, brief={"objective": "A platform"})
    result = score_deck_structure(plan)
    assert result["score"] >= 60.0  # clean plan should be at least C grade
    assert result["grade"] in ("A", "B", "C")


def test_long_title_penalized():
    plan = DeckPlan(slides=[
        SlideSpec(slide_no=1, title="A" * 100, layout="Detail-01", block="bullets",
                  bullets=["bullet one"], source_refs=["REQ-1"], narrative_role="solution"),
        SlideSpec(slide_no=2, title="Short", layout="Detail-01", block="bullets",
                  bullets=["x"], source_refs=["REQ-1"], narrative_role="objective"),
        SlideSpec(slide_no=3, title="Scope", layout="Detail-01", block="bullets",
                  bullets=["scope item"], source_refs=["REQ-1"], narrative_role="scope"),
        SlideSpec(slide_no=4, title="Effort", layout="Detail-01", block="bullets",
                  bullets=["effort"], source_refs=["WBS-1"], narrative_role="effort"),
        SlideSpec(slide_no=5, title="Timeline", layout="Detail-01", block="bullets",
                  bullets=["timeline"], source_refs=["WBS-1"], narrative_role="timeline"),
    ])
    result = score_deck_structure(plan)
    assert any("title too long" in iss for iss in result["issues"])
    assert result["score"] < 100.0


def test_too_many_bullets_penalized():
    plan = DeckPlan(slides=[
        SlideSpec(slide_no=1, title="Overview", layout="Detail-01", block="bullets",
                  bullets=[f"b{i}" for i in range(10)],  # 10 > _MAX_BULLETS=8
                  source_refs=["REQ-1"], narrative_role="solution"),
        SlideSpec(slide_no=2, title="Obj", layout="Detail-01", block="bullets",
                  bullets=["x"], source_refs=["REQ-1"], narrative_role="objective"),
        SlideSpec(slide_no=3, title="Scope", layout="Detail-01", block="bullets",
                  bullets=["x"], source_refs=["REQ-1"], narrative_role="scope"),
        SlideSpec(slide_no=4, title="Effort", layout="Detail-01", block="bullets",
                  bullets=["x"], source_refs=["WBS-1"], narrative_role="effort"),
        SlideSpec(slide_no=5, title="Timeline", layout="Detail-01", block="bullets",
                  bullets=["x"], source_refs=["WBS-1"], narrative_role="timeline"),
    ])
    result = score_deck_structure(plan)
    assert any("too many bullets" in iss for iss in result["issues"])


def test_client_facing_without_source_refs_penalized():
    plan = DeckPlan(slides=[
        SlideSpec(slide_no=1, title="Pricing", layout="Detail-01", block="bullets",
                  bullets=["$100/month"], source_refs=[],  # client-facing, no source_refs
                  narrative_role="pricing", client_facing=True),
        SlideSpec(slide_no=2, title="Obj", layout="Detail-01",
                  bullets=["x"], source_refs=["REQ-1"], narrative_role="objective"),
        SlideSpec(slide_no=3, title="Sol", layout="Detail-01",
                  bullets=["x"], source_refs=["COMP-1"], narrative_role="solution"),
        SlideSpec(slide_no=4, title="Scope", layout="Detail-01",
                  bullets=["x"], source_refs=["REQ-1"], narrative_role="scope"),
        SlideSpec(slide_no=5, title="Effort", layout="Detail-01",
                  bullets=["x"], source_refs=["WBS-1"], narrative_role="effort"),
        SlideSpec(slide_no=6, title="Timeline", layout="Detail-01",
                  bullets=["x"], source_refs=["WBS-1"], narrative_role="timeline"),
    ])
    result = score_deck_structure(plan)
    assert any("client-facing" in iss and "source_refs" in iss for iss in result["issues"])
    assert result["score"] < 100.0


def test_missing_required_roles_penalized():
    plan = DeckPlan(slides=[
        SlideSpec(slide_no=1, title="Overview", narrative_role="solution",
                  bullets=["x"], source_refs=["COMP-1"]),
        SlideSpec(slide_no=2, title="Context", narrative_role="context",
                  bullets=["x"], source_refs=["REQ-1"]),
        # missing: objective, scope, effort, timeline
    ])
    result = score_deck_structure(plan)
    missing_issues = [iss for iss in result["issues"] if "missing required" in iss]
    assert len(missing_issues) >= 3  # at least objective, scope, effort or timeline missing


def test_too_few_slides_penalized():
    plan = DeckPlan(slides=[
        SlideSpec(slide_no=1, title="Only slide", narrative_role="solution",
                  bullets=["x"], source_refs=["COMP-1"]),
    ])
    result = score_deck_structure(plan)
    assert any("too few" in iss for iss in result["issues"])
    assert result["score"] < 100.0


def test_grade_derived_from_score():
    result = score_deck_structure(DeckPlan(slides=[]))
    # Empty plan: 10 (too few slides) + 5 * 8 (missing required roles) = 50 deduction
    # Score = 100 - 50 = 50.0 → grade D
    assert result["grade"] == "D"
    assert result["score"] == 50.0
