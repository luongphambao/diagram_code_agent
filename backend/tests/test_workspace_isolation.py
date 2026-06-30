"""Tests for per-thread workspace isolation foundation (§4.10 multi-tenancy)."""

from __future__ import annotations

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
