"""Tests for the evidence store (evidence.py).

Covers: the append-only store round-trip, stable EVD ids, and `project_into_csm`
folding records into the SolutionModel as Evidence entities + `supports` trace
links (only to entities that exist), back-filling Decision.evidence_ids, with
deterministic/idempotent re-projection. Plus the end-to-end fold through
build_solution_model.
"""

import json

from csm import Component, Decision, SolutionModel
from evidence import (
    EvidenceRecord,
    append_evidence,
    new_evidence_record,
    next_seq,
    project_into_csm,
    read_evidence,
)


def test_append_and_read_roundtrip(tmp_path):
    rec = new_evidence_record("Fargate is $0.04/vCPU-hr (2026)", seq=1,
                              source_url="https://aws.amazon.com/fargate/pricing/",
                              confidence="high", supports_entity_ids=["DEC-1"])
    append_evidence(rec, workspace=tmp_path)
    loaded = read_evidence(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].id == "EVD-1"
    assert loaded[0].confidence == "high"
    assert loaded[0].supports_entity_ids == ["DEC-1"]
    # File shape is {"evidence": [...]}.
    raw = json.loads((tmp_path / "evidence_log.json").read_text(encoding="utf-8"))
    assert "evidence" in raw and len(raw["evidence"]) == 1


def test_next_seq_and_stable_ids(tmp_path):
    assert next_seq(tmp_path) == 1
    append_evidence(new_evidence_record("c1", seq=1), workspace=tmp_path)
    assert next_seq(tmp_path) == 2
    second = new_evidence_record("c2", seq=next_seq(tmp_path))
    assert second.id == "EVD-2"


def test_read_missing_log_is_empty(tmp_path):
    assert read_evidence(tmp_path) == []


def test_project_adds_evidence_entity_and_support_link():
    model = SolutionModel(decisions=[Decision(id="DEC-1", title="Use a managed gateway")])
    rec = new_evidence_record("Managed gateway handles 10k rps", seq=1,
                              source_url="https://example.com/gw", confidence="medium",
                              quote_or_excerpt="up to 10,000 requests/second",
                              supports_entity_ids=["DEC-1"])
    project_into_csm(model, [rec])
    # The Evidence entity exists with its source captured.
    ev = model.by_id("EVD-1")
    assert ev is not None and ev.provenance == "agent"
    assert ev.source_refs and ev.source_refs[0].ref == "https://example.com/gw"
    # A supports link resolves to real entities on both ends.
    link = next(l for l in model.trace_links if l.relation == "supports")
    assert model.by_id(link.from_id) is ev
    assert model.by_id(link.to_id) is model.decisions[0]
    # The decision back-references the evidence.
    assert "EVD-1" in model.decisions[0].evidence_ids


def test_dangling_support_reference_is_dropped():
    model = SolutionModel(components=[Component(id="COMP-api", name="API")])
    rec = new_evidence_record("x", seq=1, supports_entity_ids=["DEC-nope", "COMP-api"])
    project_into_csm(model, [rec])
    targets = {l.to_id for l in model.trace_links if l.relation == "supports"}
    assert targets == {"COMP-api"}  # the non-existent DEC-nope is skipped


def test_support_link_to_non_decision_does_not_touch_evidence_ids():
    model = SolutionModel(components=[Component(id="COMP-api", name="API")])
    rec = new_evidence_record("x", seq=1, supports_entity_ids=["COMP-api"])
    project_into_csm(model, [rec])
    # Only the supports link is added; there is no decision to back-fill.
    assert any(l.to_id == "COMP-api" and l.relation == "supports" for l in model.trace_links)


def test_project_is_deterministic_and_idempotent():
    rec = new_evidence_record("c", seq=1, source_url="u", supports_entity_ids=[])
    m1 = project_into_csm(SolutionModel(), [rec])
    m2 = project_into_csm(SolutionModel(), [rec])
    assert m1.content_hash() == m2.content_hash()
    # Re-projecting onto an already-projected model does not duplicate.
    project_into_csm(m1, [rec])
    assert len(m1.evidence) == 1


def test_supersedes_is_preserved_without_deleting_old(tmp_path):
    append_evidence(new_evidence_record("price v1", seq=1, source_url="u1"), workspace=tmp_path)
    append_evidence(new_evidence_record("price v2", seq=2, source_url="u2",
                                        supersedes_evidence_id="EVD-1"), workspace=tmp_path)
    loaded = read_evidence(tmp_path)
    assert len(loaded) == 2  # append-only: the old record is still on file
    model = project_into_csm(SolutionModel(), loaded)
    assert model.by_id("EVD-2").supersedes_evidence_id == "EVD-1"
    assert model.by_id("EVD-1") is not None


def test_build_solution_model_projects_evidence_log(tmp_path):
    """End-to-end: a persisted evidence record shows up in the rebuilt CSM (+ bumps revision)."""
    from csm_adapter import build_solution_model

    (tmp_path / "diagram_brief.json").write_text(
        json.dumps({"functional_requirements": ["API Gateway routes requests"]}), encoding="utf-8")
    (tmp_path / "blueprint.json").write_text(
        json.dumps({"nodes": [{"id": "api_gw", "label": "API Gateway"}],
                    "key_decisions": ["Use a managed gateway"]}), encoding="utf-8")

    base = build_solution_model(tmp_path, created_at="2026-06-30T00:00:00Z")
    assert not base.evidence
    # The adapter mints DEC-1 from the first key decision.
    assert base.by_id("DEC-1") is not None

    append_evidence(new_evidence_record(
        "Managed gateway is $0.90/M requests (2026)", seq=1,
        source_url="https://aws.amazon.com/api-gateway/pricing/", confidence="high",
        supports_entity_ids=["DEC-1"]), workspace=tmp_path)

    rebuilt = build_solution_model(tmp_path, created_at="2026-06-30T00:00:00Z")
    assert rebuilt.by_id("EVD-1") is not None
    assert any(l.from_id == "EVD-1" and l.to_id == "DEC-1" and l.relation == "supports"
               for l in rebuilt.trace_links)
    assert "EVD-1" in rebuilt.by_id("DEC-1").evidence_ids
    assert rebuilt.revision == base.revision + 1   # new evidence is a real change


def test_epistemic_summary_surfaces_grounded_claims():
    rec = new_evidence_record("Postgres 16 is GA", seq=1, source_url="u", confidence="high")
    model = project_into_csm(SolutionModel(), [rec])
    summary = model.epistemic_summary()
    assert summary["grounded_claims"] == [
        {"id": "EVD-1", "claim": "Postgres 16 is GA", "source_url": "u", "confidence": "high"}
    ]
