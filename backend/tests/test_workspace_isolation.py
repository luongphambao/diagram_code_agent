"""Tests for per-thread workspace isolation foundation (§4.10 multi-tenancy)."""

from __future__ import annotations

import json

import backends
from backends import (
    WORKSPACE,
    current_workspace,
    resolve_workspace,
    set_current_workspace,
)


def test_two_threads_get_separate_dirs():
    a = resolve_workspace("thread-alice")
    b = resolve_workspace("thread-bob")
    assert a != b
    assert a.exists() and b.exists()
    # Writes in one thread's workspace do not appear in the other's.
    (a / "solution_model.json").write_text("{}", encoding="utf-8")
    assert not (b / "solution_model.json").exists()


def test_default_thread_uses_shared_workspace():
    assert resolve_workspace(None) == WORKSPACE
    assert resolve_workspace("") == WORKSPACE
    assert resolve_workspace("thread-default") == WORKSPACE


def test_hostile_thread_id_cannot_escape():
    # A traversal attempt is sanitised to a plain name under WORKSPACES_DIR.
    ws = resolve_workspace("../../etc/evil")
    resolved = ws.resolve()
    assert str(backends.WORKSPACES_DIR.resolve()) in str(resolved)


def test_current_workspace_contextvar_default_and_override():
    assert current_workspace() == WORKSPACE
    other = resolve_workspace("thread-ctx")
    token = set_current_workspace(other)
    try:
        assert current_workspace() == other
    finally:
        backends._current_workspace.reset(token)
    assert current_workspace() == WORKSPACE


import contextvars  # noqa: E402


def _bind(monkeypatch, ws):
    """Bind ``ws`` as the current workspace; monkeypatch auto-restores afterwards."""
    ws.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends, "_current_workspace",
        contextvars.ContextVar("current_workspace", default=ws),
    )


def test_stage_marker_proxy_follows_current_workspace(tmp_path, monkeypatch):
    """A WorkspaceFile proxy resolves against whatever workspace is bound at call time."""
    from tools.constants import _BRIEF_FILE

    a, b = tmp_path / "ta", tmp_path / "tb"
    _bind(monkeypatch, a)
    _BRIEF_FILE.write_text('{"thread": "a"}', encoding="utf-8")
    assert (a / "diagram_brief.json").exists()
    assert not (b / "diagram_brief.json").exists()

    # Rebinding to another thread re-points the SAME proxy object — no leak.
    _bind(monkeypatch, b)
    assert not _BRIEF_FILE.exists()
    _BRIEF_FILE.write_text('{"thread": "b"}', encoding="utf-8")
    assert (b / "diagram_brief.json").exists()
    assert json.loads((a / "diagram_brief.json").read_text())["thread"] == "a"


def test_store_writes_into_current_workspace(tmp_path, monkeypatch):
    """A router-side store (decision_log) lands in the bound thread's workspace."""
    from decisions import DecisionRecord, append_decision, next_seq, read_decisions

    a, b = tmp_path / "da", tmp_path / "db"
    _bind(monkeypatch, a)
    assert next_seq() == 1  # empty log in this thread
    append_decision(DecisionRecord(id="DR-1", action="accept_risk"))  # no workspace arg
    assert (a / "decision_log.json").exists()
    assert len(read_decisions()) == 1

    # A different thread starts with an empty, independent log.
    _bind(monkeypatch, b)
    assert read_decisions() == []
    assert not (b / "decision_log.json").exists()
