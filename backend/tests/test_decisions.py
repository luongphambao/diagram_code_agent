"""Tests for HITL v2 decision records (decisions.py).

Covers: the append-only store round-trip, stable human-distinct ids, and
`project_into_csm` folding each action into the SolutionModel (accepted risk,
confirmed assumptions, evidence request) with resolvable `accepts` trace links.
"""

import json

from memory.stores.csm import Assumption, SolutionModel
from memory.stores.decisions import (
    DecisionRecord,
    append_decision,
    new_decision_record,
    next_seq,
    project_into_csm,
    read_decisions,
)


def test_append_and_read_roundtrip(tmp_path):
    rec = new_decision_record("propose_blueprint", "approve", seq=1,
                              approver="alice", timestamp="2026-06-29T00:00:00Z")
    append_decision(rec, workspace=tmp_path)
    loaded = read_decisions(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].id == "DEC-h1"
    assert loaded[0].approver == "alice"
    # File shape is {"decisions": [...]}.
    raw = json.loads((tmp_path / "decision_log.json").read_text(encoding="utf-8"))
    assert "decisions" in raw and len(raw["decisions"]) == 1


def test_next_seq_and_human_ids_dont_collide(tmp_path):
    assert next_seq(tmp_path) == 1
    append_decision(new_decision_record("g", "approve", seq=1), workspace=tmp_path)
    assert next_seq(tmp_path) == 2
    second = new_decision_record("g", "reject", seq=next_seq(tmp_path))
    assert second.id == "DEC-h2"  # never collides with ordinal DEC-1/DEC-2


def test_read_missing_log_is_empty(tmp_path):
    assert read_decisions(tmp_path) == []


def test_project_accept_risk_adds_risk_and_link():
    model = SolutionModel()
    rec = new_decision_record("propose_blueprint", "accept_risk", seq=1, approver="bob",
                              payload={"statement": "Vendor quota backlog", "owner": "bob",
                                       "mitigation": "request quota bump", "impact": "high"})
    project_into_csm(model, [rec])
    # A human Decision entity exists.
    dec = model.by_id("DEC-h1")
    assert dec is not None and dec.provenance == "human" and dec.status == "approved"
    # A Risk was created and carries the owner/mitigation/impact.
    assert len(model.risks) == 1
    risk = model.risks[0]
    assert risk.owner == "bob" and risk.mitigation == "request quota bump" and risk.impact == "high"
    # The accepts link resolves to real entities on both ends.
    link = next(l for l in model.trace_links if l.relation == "accepts")
    assert model.by_id(link.from_id) is not None
    assert model.by_id(link.to_id) is risk


def test_project_approve_with_assumptions_confirms():
    model = SolutionModel(assumptions=[Assumption(id="ASM-1", statement="500 req/s peak")])
    rec = new_decision_record("propose_tech_stack", "approve_with_assumptions", seq=1,
                              approver="cara", payload={"assumption_ids": ["ASM-1"]})
    project_into_csm(model, [rec])
    assert model.by_id("ASM-1").status == "confirmed"
    assert model.by_id("ASM-1").provenance == "human"
    assert any(l.to_id == "ASM-1" and l.relation == "accepts" for l in model.trace_links)


def test_project_request_evidence_adds_pending_assumption():
    model = SolutionModel()
    rec = new_decision_record("propose_blueprint", "request_evidence", seq=1,
                              payload={"claim": "Kafka scales to 1M msg/s"})
    project_into_csm(model, [rec])
    pend = [a for a in model.assumptions if a.status == "pending"]
    assert len(pend) == 1 and "Evidence requested" in pend[0].statement


def test_project_is_deterministic_and_idempotent():
    rec = new_decision_record("g", "accept_risk", seq=1, payload={"statement": "x", "owner": "o"})
    m1 = project_into_csm(SolutionModel(), [rec])
    m2 = project_into_csm(SolutionModel(), [rec])
    assert m1.content_hash() == m2.content_hash()
    # Re-projecting onto an already-projected model does not duplicate.
    project_into_csm(m1, [rec])
    assert sum(1 for _ in m1.decisions) == 1


# --- HITL v2 payload -> decision mapping (session_state) ----------------------

def test_rich_actions_map_onto_approve_reject():
    import session_state as ss
    assert ss._decision_from_payload({"action": "accept_risk"}, "propose_blueprint")["type"] == "approve"
    assert ss._decision_from_payload({"action": "approve_with_assumptions"}, "propose_wbs")["type"] == "approve"
    ev = ss._decision_from_payload({"action": "request_evidence", "claim": "Kafka scales"}, "propose_blueprint")
    assert ev["type"] == "reject" and "evidence" in ev["message"].lower()
    alt = ss._decision_from_payload({"action": "request_alternative"}, "propose_wbs")
    assert alt["type"] == "reject" and "alternative" in alt["message"].lower()


def test_legacy_payload_is_back_compatible():
    import session_state as ss
    assert ss._decision_from_payload({"approved": True}, "propose_wbs")["type"] == "approve"
    assert ss._decision_from_payload({"approved": False, "modifications": "x"}, "propose_wbs")["type"] == "reject"
    assert ss._decision_from_payload({"satisfied": True}, "finalize_diagram")["type"] == "approve"
    assert ss._decision_from_payload({"satisfied": False}, "finalize_diagram")["type"] == "reject"


def test_build_solution_model_projects_decision_log(tmp_path):
    """End-to-end: a persisted decision shows up in the rebuilt CSM (+ bumps revision)."""
    import json as _json

    from memory.stores.csm_adapter import build_solution_model

    # Minimal artifacts so from_artifacts has something to project.
    (tmp_path / "diagram_brief.json").write_text(
        _json.dumps({"functional_requirements": ["API Gateway routes requests"]}), encoding="utf-8")
    (tmp_path / "blueprint.json").write_text(
        _json.dumps({"nodes": [{"id": "api_gw", "label": "API Gateway"}],
                     "key_decisions": ["Use a managed gateway"]}), encoding="utf-8")

    base = build_solution_model(tmp_path, created_at="2026-06-29T00:00:00Z")
    assert not any(d.provenance == "human" for d in base.decisions)

    append_decision(new_decision_record(
        "propose_blueprint", "accept_risk", seq=1, approver="alice",
        payload={"statement": "Vendor quota backlog", "owner": "alice"}), workspace=tmp_path)

    rebuilt = build_solution_model(tmp_path, created_at="2026-06-29T00:00:00Z")
    assert any(d.provenance == "human" for d in rebuilt.decisions)
    assert any(r.statement == "Vendor quota backlog" for r in rebuilt.risks)
    assert rebuilt.revision == base.revision + 1   # a human decision is a real change


def test_record_builder_only_for_rich_actions():
    import session_state as ss
    assert ss.decision_record_from_payload({"approved": True}, "propose_wbs", seq=1) is None
    rec = ss.decision_record_from_payload(
        {"action": "accept_risk", "owner": "bob", "statement": "quota"},
        "propose_blueprint", seq=1, approver="alice", timestamp="t")
    assert rec is not None and rec.action == "accept_risk" and rec.payload["owner"] == "bob"
    # routing keys are stripped from the persisted payload
    assert "action" not in rec.payload and "approved" not in rec.payload
