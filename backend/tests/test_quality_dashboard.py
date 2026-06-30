"""Tests for quality_dashboard.py — QualitySnapshot, scoring, and format."""

import json
from pathlib import Path

import pytest

from csm import Assumption, Constraint, Decision, Requirement, Risk, SolutionModel
from quality_dashboard import (
    QualitySnapshot,
    build_quality_snapshot,
    format_snapshot,
    load_snapshot,
    write_snapshot,
    _grade,
    _compute_score,
)


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_empty_workspace(tmp_path):
    snap = build_quality_snapshot(tmp_path)
    assert snap.total_findings == 0
    assert snap.total_decisions == 0
    assert snap.total_evidence == 0
    assert snap.quality_grade in ("A", "B", "C", "D", "F")


def test_grade_boundaries():
    assert _grade(90) == "A"
    assert _grade(89.9) == "B"
    assert _grade(75) == "B"
    assert _grade(74.9) == "C"
    assert _grade(60) == "C"
    assert _grade(59.9) == "D"
    assert _grade(45) == "D"
    assert _grade(44.9) == "F"


def test_findings_breakdown(tmp_path):
    findings_data = {
        "findings": [
            {"finding_id": "SF-1", "status": "open", "severity": "high", "dimension": "traceability"},
            {"finding_id": "SF-2", "status": "open", "severity": "medium", "dimension": "completeness"},
            {"finding_id": "SF-3", "status": "waived", "severity": "low", "dimension": "style"},
            {"finding_id": "SF-4", "status": "resolved", "severity": "low", "dimension": "style"},
        ]
    }
    _write_json(tmp_path / "findings_log.json", findings_data)
    snap = build_quality_snapshot(tmp_path)
    assert snap.total_findings == 4
    assert snap.findings_open == 2
    assert snap.findings_waived == 1
    assert snap.findings_resolved == 1
    assert snap.findings_by_severity == {"high": 1, "medium": 1}
    assert snap.findings_by_dimension == {"traceability": 1, "completeness": 1}


def test_score_penalizes_open_findings(tmp_path):
    findings_data = {
        "findings": [
            {"finding_id": f"SF-{i}", "status": "open", "severity": "high", "dimension": "x"}
            for i in range(5)
        ]
    }
    _write_json(tmp_path / "findings_log.json", findings_data)
    snap = build_quality_snapshot(tmp_path)
    assert snap.quality_score < 70.0  # base penalized by 5 high findings * 5 pts


def test_decisions_breakdown(tmp_path):
    dec_data = {
        "decisions": [
            {"id": "DEC-h1", "gate": "propose_blueprint", "action": "approve"},
            {"id": "DEC-h2", "gate": "propose_blueprint", "action": "request_evidence"},
            {"id": "DEC-h3", "gate": "propose_tech_stack", "action": "approve_with_assumptions"},
        ]
    }
    _write_json(tmp_path / "decision_log.json", dec_data)
    snap = build_quality_snapshot(tmp_path)
    assert snap.total_decisions == 3
    assert snap.decisions_by_gate["propose_blueprint"] == 2
    assert snap.decisions_by_action["approve"] == 1


def test_evidence_confidence_breakdown(tmp_path):
    ev_data = {
        "evidence": [
            {"id": "EVD-1", "claim": "x", "source_url": "http://a.com", "confidence": "high"},
            {"id": "EVD-2", "claim": "y", "source_url": "http://b.com", "confidence": "medium"},
            {"id": "EVD-3", "claim": "z", "source_url": "http://c.com", "confidence": "low"},
        ]
    }
    _write_json(tmp_path / "evidence_log.json", ev_data)
    snap = build_quality_snapshot(tmp_path)
    assert snap.total_evidence == 3
    assert snap.evidence_by_confidence == {"high": 1, "medium": 1, "low": 1}


def test_assumptions_by_tier_from_solution_model(tmp_path):
    sm = SolutionModel(assumptions=[
        Assumption(id="ASM-1", statement="Budget is $5000/month",
                   confidence_tier="must_confirm", status="pending"),
        Assumption(id="ASM-2", statement="Team uses best practices",
                   confidence_tier="nice_to_confirm", status="pending"),
        Assumption(id="ASM-3", statement="Use AWS as cloud provider",
                   confidence_tier="should_confirm", status="confirmed"),
    ])
    _write_json(tmp_path / "solution_model.json", json.loads(sm.to_json()))
    snap = build_quality_snapshot(tmp_path)
    assert snap.total_assumptions == 3
    assert snap.assumptions_confirmed == 1
    assert snap.assumptions_pending == 2
    assert snap.assumptions_by_tier.get("must_confirm", 0) == 1
    assert snap.assumptions_by_tier.get("nice_to_confirm", 0) == 1


def test_write_and_load_snapshot(tmp_path):
    snap = build_quality_snapshot(tmp_path)
    write_snapshot(snap, tmp_path)
    loaded = load_snapshot(tmp_path)
    assert loaded is not None
    assert loaded.quality_score == snap.quality_score
    assert loaded.quality_grade == snap.quality_grade


def test_format_snapshot_contains_key_fields(tmp_path):
    snap = build_quality_snapshot(tmp_path)
    rendered = format_snapshot(snap)
    assert "QUALITY DASHBOARD" in rendered
    assert "/100" in rendered
    assert "Findings:" in rendered
    assert "Evidence:" in rendered


def test_must_confirm_pending_penalizes_score(tmp_path):
    sm = SolutionModel(assumptions=[
        Assumption(id="ASM-1", statement="Budget is $5000/month",
                   confidence_tier="must_confirm", status="pending"),
    ])
    _write_json(tmp_path / "solution_model.json", json.loads(sm.to_json()))
    snap_with_must = build_quality_snapshot(tmp_path)

    sm2 = SolutionModel(assumptions=[
        Assumption(id="ASM-1", statement="Budget is $5000/month",
                   confidence_tier="must_confirm", status="confirmed"),
    ])
    _write_json(tmp_path / "solution_model.json", json.loads(sm2.to_json()))
    snap_confirmed = build_quality_snapshot(tmp_path)

    # confirmed must_confirm gets the bonus (score higher)
    assert snap_confirmed.quality_score > snap_with_must.quality_score
