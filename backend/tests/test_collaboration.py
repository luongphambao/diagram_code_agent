"""Tests for WS3 collaboration & audit (docx §8.6): comments, roles, ADR export."""

from __future__ import annotations

from pathlib import Path

from adr_export import render_adr_pack, write_adr_pack
from comments import (
    append_comment,
    comments_for,
    new_comment_record,
    next_seq,
    read_comments,
    resolve_comment,
)
from csm import Decision, DecisionOption, SolutionModel
from decisions import DecisionRecord
from tools import can_approve


# --- comments ----------------------------------------------------------------

def test_comment_append_and_read(tmp_path: Path):
    rec = new_comment_record("Is 500 RPS realistic?", seq=next_seq(tmp_path),
                             anchor_entity_id="REQ-3", author="alice", role="architect")
    assert rec.id == "CMT-1"
    append_comment(rec, tmp_path)
    rec2 = new_comment_record("Looks good", seq=next_seq(tmp_path), anchor_entity_id="COMP-api")
    append_comment(rec2, tmp_path)
    all_c = read_comments(tmp_path)
    assert [c.id for c in all_c] == ["CMT-1", "CMT-2"]
    assert [c.id for c in comments_for("REQ-3", tmp_path)] == ["CMT-1"]


def test_resolve_comment(tmp_path: Path):
    append_comment(new_comment_record("q", seq=1, anchor_entity_id="REQ-1"), tmp_path)
    updated = resolve_comment("CMT-1", resolved_by="bob", resolved_at="2026-06-30T00:00:00Z",
                              workspace=tmp_path)
    assert updated is not None and updated.resolved and updated.resolved_by == "bob"
    assert read_comments(tmp_path)[0].resolved is True
    # unknown id → None
    assert resolve_comment("CMT-99", workspace=tmp_path) is None


# --- role-based approval -----------------------------------------------------

def test_can_approve_policy():
    # architect may approve blueprint; pm may not
    assert can_approve("architect", "propose_blueprint") is True
    assert can_approve("pm", "propose_blueprint") is False
    # pm may approve client-facing sends
    assert can_approve("pm", "send_architecture_report_email") is True
    # empty/unknown role is permissive (back-compat)
    assert can_approve("", "propose_blueprint") is True
    # a gate with no role restriction is open to anyone
    assert can_approve("client", "propose_deck_plan") is True


def test_decision_record_carries_role():
    rec = DecisionRecord(id="DEC-h1", gate="propose_blueprint", action="accept_risk",
                         approver="a@b.com", approver_role="architect")
    assert rec.approver_role == "architect"


# --- ADR export --------------------------------------------------------------

def _seed_model(ws: Path) -> None:
    model = SolutionModel(decisions=[
        Decision(id="DEC-1", title="Use managed Kubernetes",
                 options=[DecisionOption(id="o1", title="EKS", trade_offs="ops simplicity"),
                          DecisionOption(id="o2", title="self-managed", trade_offs="cheaper, more ops")],
                 selected_option_id="o1", rationale="Lower ops burden", status="approved",
                 approver="arch@x.com", evidence_ids=["EVD-1"], risk_ids=["RISK-2"]),
    ])
    (ws / "solution_model.json").write_text(model.to_json(), encoding="utf-8")


def test_adr_pack_renders_decisions(tmp_path: Path):
    _seed_model(tmp_path)
    md, n = render_adr_pack(tmp_path)
    assert n == 1
    assert "# Architecture Decision Records" in md
    assert "DEC-1 — Use managed Kubernetes" in md
    assert "EKS ✅ (chosen)" in md
    assert "EVD-1" in md and "RISK-2" in md


def test_adr_pack_includes_approval_timeline(tmp_path: Path):
    _seed_model(tmp_path)
    from decisions import append_decision, new_decision_record
    rec = new_decision_record("propose_blueprint", "accept_risk", seq=1, approver="a@b.com",
                              approver_role="architect", timestamp="2026-06-30T10:00:00Z",
                              revision=2, comment="accepted single-region risk")
    append_decision(rec, tmp_path)
    path, n = write_adr_pack(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "Approval timeline" in text
    assert "accept_risk" in text and "a@b.com" in text


def test_adr_pack_empty_when_no_decisions(tmp_path: Path):
    md, n = render_adr_pack(tmp_path)
    assert n == 0
    assert "No architecture decisions" in md
