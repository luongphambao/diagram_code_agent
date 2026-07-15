"""Tests for the Canonical Solution Model (csm.py) + projection adapter (csm_adapter.py).

Covers: stable IDs, idempotent content hash, the artifact->CSM projection, trace
links over CSM ids, the epistemic split, and the workspace round-trip with revision
bumping.
"""

import json

import memory.stores.csm as csm
from memory.stores.csm_adapter import build_solution_model, from_artifacts

# --- representative approved artifacts ---------------------------------------

BRIEF = {
    "functional_requirements": [
        "OCR Service extracts text from uploaded documents",
        "Provide real-time fraud scoring",
    ],
    "non_functional_requirements": ["99.9% availability"],
    "assumptions": ["Assume 500 req/s peak traffic"],
    "layout_constraints": ["Single-region deployment in eu-west"],
}
ANALYSIS = {"constraints": ["budget_sensitive", "compliance_sensitive"]}
TECH = {
    "layers": {
        "backend": {
            "choice": "AWS Lambda",
            "risks": [{"risk": "Cold start latency", "mitigation": "provisioned concurrency"}],
        },
    },
}
BLUEPRINT = {
    "nodes": [
        {"id": "api_gw", "label": "API Gateway", "cluster": "edge", "type": "gateway"},
        {"id": "ocr_svc", "label": "OCR Service", "cluster": "edge", "tech": "Tesseract"},
        {"id": "stripe", "label": "Stripe", "type": "external"},
    ],
    "clusters": [{"id": "edge", "label": "Edge", "tier": "frontend"}],
    "key_decisions": ["Use managed Kubernetes", "Event bus for async ingestion"],
}
WBS = {
    "items": [
        {"id": "1.1", "name": "OCR Service implementation", "total_md": 12},
        {"id": "9.9", "name": "Internal tooling spike"},
    ],
    "effort_totals": {"total_mandays": 12},
}


def test_mint_id_is_label_independent():
    assert csm.mint_id("component", "API GW!") == "COMP-api_gw"
    assert csm.mint_id("requirement", 3) == "REQ-3"


def test_projection_assigns_stable_ids():
    m = from_artifacts(BRIEF, BLUEPRINT, WBS)
    assert [r.id for r in m.requirements] == ["REQ-1", "REQ-2", "REQ-3"]
    comp_ids = {c.id for c in m.components}
    assert {"CLUSTER-edge", "COMP-api_gw", "COMP-ocr_svc", "COMP-stripe"} <= comp_ids
    # external node becomes an integration; node->cluster uses the cluster's CSM id
    stripe = m.by_id("COMP-stripe")
    assert stripe.kind == "integration"
    assert m.by_id("COMP-ocr_svc").cluster == "CLUSTER-edge"
    assert [d.id for d in m.decisions] == ["DEC-1", "DEC-2"]
    assert m.by_id("WBS-1_1").effort_mandays == 12.0


def test_trace_links_use_csm_ids():
    m = from_artifacts(BRIEF, BLUEPRINT, WBS)
    triples = {(l.from_id, l.relation, l.to_id) for l in m.trace_links}
    assert ("REQ-1", "satisfies", "COMP-ocr_svc") in triples
    assert ("WBS-1_1", "implements", "COMP-ocr_svc") in triples
    # every trace link endpoint resolves to a real entity
    ids = m.ids()
    for l in m.trace_links:
        assert l.from_id in ids and l.to_id in ids


def test_constraints_populated():
    m = from_artifacts(BRIEF, BLUEPRINT, WBS, analysis=ANALYSIS)
    assert m.constraints, "constraints should be populated from brief + analysis"
    assert m.by_id("CON-1").statement.startswith("Single-region")
    # a budget_sensitive analysis tag maps to kind 'budget'
    assert any(c.kind == "budget" for c in m.constraints)
    # the free-text layout constraint is sourced from the brief
    assert any(
        s.ref == "diagram_brief.json" for c in m.constraints for s in c.source_refs
    )


def test_risks_populated():
    m = from_artifacts(BRIEF, BLUEPRINT, WBS, tech_stack=TECH)
    assert [r.statement for r in m.risks] == ["Cold start latency"]
    risk = m.by_id("RISK-1")
    assert risk.mitigation == "provisioned concurrency"
    assert any(s.ref == "tech_stack.json" for s in risk.source_refs)


def test_new_relations_emitted():
    # a constraint that shares a significant word with a component fires `constrains`
    brief = {**BRIEF, "layout_constraints": ["OCR Service must stay in eu-west"]}
    m = from_artifacts(brief, BLUEPRINT, WBS, analysis=ANALYSIS, tech_stack=TECH)
    relations = {l.relation for l in m.trace_links}
    # every endpoint of every link must resolve to a real entity
    ids = m.ids()
    for l in m.trace_links:
        assert l.from_id in ids and l.to_id in ids
    assert "constrains" in relations
    assert any(l.relation == "constrains" and l.to_id == "COMP-ocr_svc" for l in m.trace_links)


def test_from_artifacts_backcompat():
    """No analysis/tech_stack kwargs -> no risks, no analysis-derived constraints."""
    legacy = from_artifacts(BRIEF, BLUEPRINT, WBS)
    assert legacy.risks == []
    # constraints come only from the brief, never from an (absent) analysis file
    assert all(
        s.ref == "diagram_brief.json" for c in legacy.constraints for s in c.source_refs
    )
    # the satisfies/implements links are unaffected by the new passes
    triples = {(l.from_id, l.relation, l.to_id) for l in legacy.trace_links}
    assert ("REQ-1", "satisfies", "COMP-ocr_svc") in triples
    assert ("WBS-1_1", "implements", "COMP-ocr_svc") in triples


def test_content_hash_is_idempotent_and_ignores_volatile_fields():
    a = from_artifacts(BRIEF, BLUEPRINT, WBS)
    b = from_artifacts(BRIEF, BLUEPRINT, WBS)
    assert a.content_hash() == b.content_hash()
    b.revision = 99
    b.created_at = "2026-06-29"
    assert a.content_hash() == b.content_hash()   # volatile fields excluded


def test_epistemic_summary_groups_by_status():
    m = from_artifacts(BRIEF, BLUEPRINT, WBS)
    summ = m.epistemic_summary()
    # assumptions default to pending -> they need confirmation
    assert any(a["statement"].startswith("Assume 500") for a in summ["assumptions_needing_confirmation"])
    # decisions default to proposed -> open decisions
    assert {d["id"] for d in summ["open_decisions"]} == {"DEC-1", "DEC-2"}


def _write_artifacts(ws):
    (ws / "diagram_brief.json").write_text(json.dumps(BRIEF), encoding="utf-8")
    (ws / "blueprint.json").write_text(json.dumps(BLUEPRINT), encoding="utf-8")
    (ws / "wbs.json").write_text(json.dumps(WBS), encoding="utf-8")


def test_build_writes_file_and_bumps_revision_only_on_change(tmp_path):
    _write_artifacts(tmp_path)

    m1 = build_solution_model(tmp_path)
    assert (tmp_path / "solution_model.json").exists()
    assert m1.revision == 1

    # Re-run over identical artifacts -> idempotent (same revision, same hash).
    m2 = build_solution_model(tmp_path)
    assert m2.revision == 1
    assert m2.content_hash() == m1.content_hash()

    # A real change bumps the revision.
    changed = dict(BLUEPRINT)
    changed["key_decisions"] = BLUEPRINT["key_decisions"] + ["Single-region first, DR in phase 2"]
    (tmp_path / "blueprint.json").write_text(json.dumps(changed), encoding="utf-8")
    m3 = build_solution_model(tmp_path)
    assert m3.revision == 2
    assert m3.content_hash() != m1.content_hash()

    written = json.loads((tmp_path / "solution_model.json").read_text(encoding="utf-8"))
    assert written["sha256"] == m3.content_hash()
    assert written["revision"] == 2


def test_work_item_predecessors_and_pert_roundtrip():
    """WBS v2 fields project through from_artifacts onto the WorkItem."""
    wbs = {
        "items": [
            {"id": "1.1", "name": "OCR Service implementation", "total_md": 12,
             "pert_expected_md": 9.0, "predecessors": ["BNK-1", "BNK-2"]},
        ],
    }
    m = from_artifacts(BRIEF, BLUEPRINT, wbs)
    wi = m.by_id("WBS-1_1")
    assert wi.pert_expected_md == 9.0
    assert wi.predecessors == ["BNK-1", "BNK-2"]
    # defaults when absent: legacy items get empty predecessors / 0 pert
    legacy = from_artifacts(BRIEF, BLUEPRINT, WBS).by_id("WBS-1_1")
    assert legacy.predecessors == [] and legacy.pert_expected_md == 0.0


def test_deliverable_entity_serializes_and_is_an_entity():
    """The Deliverable entity (docx §6.1) round-trips and joins all_entities/epistemic."""
    d = csm.Deliverable(id="ART-deck", kind="pptx", title="Proposal deck",
                        solution_revision=3, source_entity_ids=["REQ-1", "DEC-1"],
                        quality_checks={"factual": 1.0, "visual": 0.87})
    m = csm.SolutionModel(deliverables=[d])
    assert m.by_id("ART-deck") is d
    assert "ART-deck" in m.ids()
    # Survives a JSON round-trip via to_json + model_validate.
    reloaded = csm.SolutionModel.model_validate(json.loads(m.to_json()))
    assert reloaded.deliverables[0].kind == "pptx"
    assert reloaded.deliverables[0].quality_checks["visual"] == 0.87
    # Surfaces in the epistemic summary's deliverables bucket.
    bucket = m.epistemic_summary()["deliverables"]
    assert bucket == [{"id": "ART-deck", "kind": "pptx", "title": "Proposal deck",
                       "quality_checks": {"factual": 1.0, "visual": 0.87}}]


def test_build_writes_prev_snapshot_only_on_change(tmp_path):
    _write_artifacts(tmp_path)

    # First build: no prior model -> no snapshot.
    build_solution_model(tmp_path)
    assert not (tmp_path / "solution_model.prev.json").exists()

    # Idempotent re-run: still no snapshot (content unchanged).
    build_solution_model(tmp_path)
    assert not (tmp_path / "solution_model.prev.json").exists()

    # Real change -> the prior model is snapshotted as the change-impact "before".
    changed = dict(BLUEPRINT)
    changed["key_decisions"] = BLUEPRINT["key_decisions"] + ["Single-region first, DR in phase 2"]
    (tmp_path / "blueprint.json").write_text(json.dumps(changed), encoding="utf-8")
    build_solution_model(tmp_path)
    prev = tmp_path / "solution_model.prev.json"
    assert prev.exists()
    assert json.loads(prev.read_text(encoding="utf-8"))["revision"] == 1  # the prior rev
