from __future__ import annotations

import json

from session.gate_decisions import (
    bind_pending_gate_identity,
    validate_pending_gate_identity,
)


def test_gate_identity_accepts_only_current_card(tmp_path):
    (tmp_path / "pending_gate.json").write_text(
        json.dumps({"tool": "propose_blueprint", "args": {}, "revision": 3}),
        encoding="utf-8",
    )
    revision = bind_pending_gate_identity(tmp_path, "propose_blueprint", "gate-current")
    assert revision == 3

    assert validate_pending_gate_identity(
        tmp_path,
        "propose_blueprint",
        {"gate_id": "gate-current", "gate_revision": 3},
    ) == (True, "")
    ok, reason = validate_pending_gate_identity(
        tmp_path,
        "propose_blueprint",
        {"gate_id": "gate-old", "gate_revision": 2},
    )
    assert ok is False
    assert "gate id" in reason


def test_legacy_pending_gate_without_identity_remains_resumable(tmp_path):
    (tmp_path / "pending_gate.json").write_text(
        json.dumps({"tool": "propose_blueprint", "args": {}}), encoding="utf-8"
    )
    assert validate_pending_gate_identity(tmp_path, "propose_blueprint", {}) == (True, "")


def test_new_card_fails_closed_when_identity_file_is_missing(tmp_path):
    ok, reason = validate_pending_gate_identity(
        tmp_path,
        "propose_blueprint",
        {"gate_id": "gate-1", "gate_revision": 1},
    )
    assert ok is False
    assert "unavailable" in reason
