"""Tests for the deck quality loop (deck.py).

Covers: building the fixed BnK storyboard from the CSM with grounded source_refs;
validate_deck firing the right structured finding for each seeded defect
(traceability / completeness / consistency / evidence); the deck_plan.json store
round-trip with revision bumping; and project_into_csm folding the plan into the
model as Deliverable entities + visualizes/claims trace links, deterministically.
Plus the end-to-end fold through build_solution_model.
"""

import json

from csm import (
    Component,
    Decision,
    Evidence,
    Requirement,
    Risk,
    SolutionModel,
    WorkItem,
)
from deck import (
    DeckPlan,
    SlideSpec,
    build_deck_plan,
    load_deck_plan,
    project_into_csm,
    validate_deck,
    write_deck_plan,
)


def _model() -> SolutionModel:
    return SolutionModel(
        requirements=[
            Requirement(id="REQ-1", kind="business", statement="Track daily sales"),
            Requirement(id="REQ-2", kind="functional", statement="Patient management"),
            Requirement(id="REQ-3", kind="nfr", statement="Mobile responsive"),
        ],
        components=[Component(id="COMP-api", name="API Gateway")],
        decisions=[Decision(id="DEC-1", title="Use Odoo ERP")],
        risks=[Risk(id="RISK-1", statement="Scope creep", mitigation="CR process")],
        work_items=[WorkItem(id="WBS-1", name="Build API", effort_mandays=50.0)],
        evidence=[Evidence(id="EVD-1", claim="Odoo 17 LTS", source_url="https://odoo.com")],
    )


_WBS = {
    "effort_totals": {"total_mandays": 50, "total_manmonths": 2.3},
    "items": [{"pert_p50_md": 48, "pert_p80_md": 60}],
    "timeline": {"weeks": 16, "months": 4, "sprints": 8},
}


def test_build_deck_plan_covers_roles_and_grounds_slides():
    plan = build_deck_plan(_model(), wbs=_WBS, brief={"objective": "A clinic system"},
                           has_diagram=True)
    # All required narrative roles are present.
    assert {"objective", "solution", "scope", "effort", "timeline"} <= plan.roles()
    # The exec slide is grounded in requirements; the tech-stack slide in decisions+evidence.
    tech = next(s for s in plan.slides if s.block == "tech_stack_table")
    assert "DEC-1" in tech.source_refs and "EVD-1" in tech.source_refs
    assert tech.client_facing is True
    # Every source_ref resolves to a real CSM entity (grounded by construction).
    ids = _model().ids()
    assert all(ref in ids for s in plan.slides for ref in s.source_refs)


def test_validate_clean_plan_has_no_findings():
    m = _model()
    plan = build_deck_plan(m, wbs=_WBS, brief={"objective": "A clinic system"})
    assert validate_deck(plan, m) == []


def test_validate_flags_dangling_source_ref():
    m = _model()
    plan = DeckPlan(slides=[
        SlideSpec(slide_no=1, narrative_role="solution", title="S",
                  source_refs=["COMP-api", "COMP-ghost"])])
    dims = {f["dimension"] for f in validate_deck(plan, m)}
    assert "traceability" in dims


def test_validate_flags_missing_coverage():
    m = _model()
    plan = DeckPlan(slides=[SlideSpec(slide_no=1, narrative_role="solution", title="only")])
    findings = validate_deck(plan, m)
    assert any(f["dimension"] == "completeness" for f in findings)


def test_validate_flags_effort_mismatch_not_fooled_by_p50_label():
    m = _model()  # WBS total = 50.0
    plan = DeckPlan(slides=[SlideSpec(
        slide_no=1, narrative_role="effort", title="Effort", block="delivery_effort",
        bullets=["Total Effort: 999 MD", "P50 estimate: 0 MD"])])
    findings = validate_deck(plan, m)
    # "P50" must NOT be read as the number 50 — the mismatch has to fire.
    assert any(f["dimension"] == "consistency" for f in findings)


def test_validate_flags_ungrounded_client_facing_claim():
    m = _model()
    m.evidence = []  # no grounded evidence at all
    plan = DeckPlan(slides=[SlideSpec(
        slide_no=1, narrative_role="pricing", title="PRICING | CAPEX",
        client_facing=True, source_refs=["WBS-1"])])
    findings = validate_deck(plan, m)
    assert any(f["dimension"] == "evidence" for f in findings)


def test_project_adds_deliverables_and_trace_links():
    m = _model()
    plan = build_deck_plan(m, wbs=_WBS, brief={"objective": "A clinic system"}, has_diagram=True)
    project_into_csm(m, plan)
    # One deck Deliverable + per-slide slide Deliverables.
    assert m.by_id("ART-deck") is not None
    assert any(d.kind == "slide" for d in m.deliverables)
    relations = {l.relation for l in m.trace_links}
    assert "visualizes" in relations  # SLIDE -> COMP
    assert "claims" in relations      # SLIDE -> DEC / REQ / EVD


def test_project_is_deterministic_and_idempotent():
    m1 = _model()
    plan = build_deck_plan(m1, wbs=_WBS, brief={}, has_diagram=False)
    project_into_csm(m1, plan)
    h1 = m1.content_hash()
    # Re-projecting onto an already-projected model is a no-op (defensive guard).
    project_into_csm(m1, plan)
    assert m1.content_hash() == h1


def test_write_and_load_plan_roundtrip_and_revision_bump(tmp_path):
    m = _model()
    plan = build_deck_plan(m, wbs=_WBS, brief={"slide_title": "CLINIC"}, has_diagram=False)
    write_deck_plan(plan, tmp_path)
    loaded = load_deck_plan(tmp_path)
    assert loaded is not None and len(loaded.slides) == len(plan.slides)
    assert loaded.revision == 1
    # Same content -> revision held; changed content -> revision bumps.
    write_deck_plan(build_deck_plan(m, wbs=_WBS, brief={"slide_title": "CLINIC"},
                                    has_diagram=False), tmp_path)
    assert load_deck_plan(tmp_path).revision == 1
    m.requirements.append(Requirement(id="REQ-9", kind="functional", statement="New feature"))
    write_deck_plan(build_deck_plan(m, wbs=_WBS, brief={"slide_title": "CLINIC"},
                                    has_diagram=False), tmp_path)
    assert load_deck_plan(tmp_path).revision == 2


def test_load_missing_plan_is_none(tmp_path):
    assert load_deck_plan(tmp_path) is None


def test_build_solution_model_folds_deck_plan(tmp_path):
    """End-to-end: a stored deck_plan.json shows up in the rebuilt CSM as deliverables."""
    from csm_adapter import build_solution_model

    (tmp_path / "diagram_brief.json").write_text(
        json.dumps({"functional_requirements": ["API Gateway routes requests"]}),
        encoding="utf-8")
    (tmp_path / "blueprint.json").write_text(
        json.dumps({"nodes": [{"id": "api_gw", "label": "API Gateway"}],
                    "key_decisions": ["Use a managed gateway"]}), encoding="utf-8")
    (tmp_path / "wbs.json").write_text(
        json.dumps({"items": [{"id": "1.1", "name": "API setup", "total_md": 10}],
                    "effort_totals": {"total_mandays": 10}}), encoding="utf-8")

    base = build_solution_model(tmp_path, created_at="2026-06-30T00:00:00Z")
    assert not base.deliverables

    plan = build_deck_plan(base, wbs=json.loads((tmp_path / "wbs.json").read_text()),
                           brief={"slide_title": "X"}, has_diagram=False)
    write_deck_plan(plan, tmp_path)

    rebuilt = build_solution_model(tmp_path, created_at="2026-06-30T00:00:00Z")
    assert rebuilt.by_id("ART-deck") is not None
    assert rebuilt.revision == base.revision + 1  # folding the deck is a real change
