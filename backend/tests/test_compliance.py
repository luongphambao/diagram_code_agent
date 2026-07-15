"""Tests for compliance packs (docx §4 P2): Control entity projection + findings."""

from __future__ import annotations

from pathlib import Path

import pytest

from compliance import (
    apply_pack,
    compliance_findings,
    evidence_gaps,
    get_active_pack,
    list_packs,
    load_pack,
    project_into_csm,
    set_active_pack,
)
from memory.stores.csm import Component, Evidence, Risk, SolutionModel, WorkItem


def _model_with_auth_work() -> SolutionModel:
    return SolutionModel(
        components=[Component(id="COMP-api_gw", name="API Gateway",
                              purpose="public auth boundary with oauth tokens")],
        work_items=[WorkItem(id="WBS-1", name="Implement audit logging and SIEM export")],
        risks=[Risk(id="RISK-1", statement="Unauthorized access via public api")],
    )


def test_generic_security_pack_loads():
    assert "generic_security" in list_packs()
    pack = load_pack("generic_security")
    assert pack and pack["name"] == "generic_security"
    assert any(c["key"] == "authn_boundary" for c in pack["controls"])


def test_unknown_pack_returns_none():
    assert load_pack("does_not_exist") is None


def test_apply_pack_mints_controls_and_is_idempotent():
    m = _model_with_auth_work()
    apply_pack(m, "generic_security")
    n_controls = len(m.controls)
    n_links = len(m.trace_links)
    assert n_controls == 7  # one per pack control
    # auth control should be marked implemented (matched the API gateway component)
    auth = m.by_id("CTRL-generic_security_authn_boundary")
    assert auth is not None and auth.implemented_by_ids == ["COMP-api_gw"]
    assert auth.status == "implemented"
    # audit control matched the WBS work item
    audit = m.by_id("CTRL-generic_security_audit_logging")
    assert "WBS-1" in audit.implemented_by_ids
    # re-applying must not duplicate controls or links
    apply_pack(m, "generic_security")
    assert len(m.controls) == n_controls
    assert len(m.trace_links) == n_links


def test_implements_and_mitigates_links_created():
    m = _model_with_auth_work()
    apply_pack(m, "generic_security")
    links = {(t.from_id, t.to_id, t.relation) for t in m.trace_links}
    assert ("COMP-api_gw", "CTRL-generic_security_authn_boundary", "implements") in links
    # the auth control mitigates the unauthorized-access risk (keyword match)
    assert ("CTRL-generic_security_authn_boundary", "RISK-1", "mitigates") in links


def test_evidence_gaps_and_findings():
    m = _model_with_auth_work()
    apply_pack(m, "generic_security")
    gaps = evidence_gaps(m)
    # every control lacks evidence → all are gaps
    assert len(gaps) == len(m.controls)
    findings = compliance_findings(m)
    assert findings
    dims = {f.dimension for f in findings}
    assert dims == {"compliance"}
    # implemented-but-unproven control → request_evidence (medium)
    auth_f = [f for f in findings if "CTRL-generic_security_authn_boundary" in f.entity_ids]
    assert auth_f and auth_f[0].repair_strategy == "request_evidence"
    # missing control (no impl, no evidence) → human_decision (high)
    dr_f = [f for f in findings if "CTRL-generic_security_backup_dr" in f.entity_ids]
    assert dr_f and dr_f[0].repair_strategy == "human_decision" and dr_f[0].severity == "high"


def test_evidence_closes_the_gap():
    m = _model_with_auth_work()
    m.evidence.append(Evidence(id="EVD-1", claim="TLS 1.3 enforced on all transit endpoints"))
    apply_pack(m, "generic_security")
    enc = m.by_id("CTRL-generic_security_encryption_in_transit")
    assert "EVD-1" in enc.evidence_ids
    # that control is no longer a finding (grounded)
    findings = compliance_findings(m)
    assert not any("CTRL-generic_security_encryption_in_transit" in f.entity_ids for f in findings)


def test_active_pack_marker(tmp_path: Path):
    assert get_active_pack(tmp_path) is None
    set_active_pack("generic_security", tmp_path)
    assert get_active_pack(tmp_path) == "generic_security"
    # project_into_csm uses the marker
    m = _model_with_auth_work()
    project_into_csm(m, tmp_path)
    assert len(m.controls) == 7


def test_waived_control_not_a_finding():
    m = _model_with_auth_work()
    apply_pack(m, "generic_security")
    ctrl = m.controls[0]
    ctrl.status = "waived"
    findings = compliance_findings(m)
    assert not any(ctrl.id in f.entity_ids for f in findings)
