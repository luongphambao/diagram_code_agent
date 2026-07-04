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


def test_per_thread_filesystem_backend_isolates_threads(tmp_path, monkeypatch):
    """The deep agent's own built-in read_file/write_file must not leak across
    threads — this is the backend behind read_file/write_file/edit_file/ls/glob/grep
    for every agent (main + subagents), not just the router-side JSON stores above."""
    from backends import PerThreadFilesystemBackend

    a, b = tmp_path / "ta", tmp_path / "tb"
    backend = PerThreadFilesystemBackend(root_dir=str(tmp_path), virtual_mode=False)

    _bind(monkeypatch, a)
    write_res = backend.write("foo.txt", "from-a")
    assert write_res.error is None
    assert (a / "foo.txt").read_text(encoding="utf-8") == "from-a"
    assert not (b / "foo.txt").exists()

    _bind(monkeypatch, b)
    read_res = backend.read("foo.txt")
    assert read_res.error is not None  # not found — no leak from thread A
    write_res = backend.write("foo.txt", "from-b")
    assert write_res.error is None
    assert (b / "foo.txt").read_text(encoding="utf-8") == "from-b"
    assert (a / "foo.txt").read_text(encoding="utf-8") == "from-a"  # thread A untouched


def test_default_route_absolute_path_does_not_leak_to_shared_workspace(tmp_path, monkeypatch):
    """Regression test: an absolute path (e.g. echoed back by the model from a
    stale ls()/read() result under a different thread's cwd) must not bypass
    the per-thread `cwd` and land in the shared WORKSPACE. virtual_mode=False
    (deepagents' legacy default) treats absolute paths as real filesystem paths,
    ignoring `cwd` entirely — the production default route now sets
    virtual_mode=True (see make_local_backend), which re-roots even
    absolute-looking paths under whatever thread is currently bound."""
    from backends import PerThreadFilesystemBackend

    a, b = tmp_path / "ta", tmp_path / "tb"
    backend = PerThreadFilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)

    _bind(monkeypatch, a)
    write_res = backend.write("icon_plan.json", "from-a")
    assert write_res.error is None

    # Model echoes back a POSIX-style absolute path it saw while thread A's
    # workspace happened to be bound (e.g. from an `ls` result) — this mirrors
    # the real container path "/app/backend/agent_space/workspace/icon_plan.json".
    # Built as a plain string (not via tmp_path) so the leading "/" is preserved
    # across platforms instead of becoming a Windows drive-absolute path.
    _bind(monkeypatch, b)
    leaked = "/app/backend/agent_space/workspace/icon_plan.json"
    write_res = backend.write(leaked, "from-b-absolute")
    assert write_res.error is None
    # Re-rooted under thread B's own cwd — never touches thread A's file or any
    # literal host path outside the bound thread's directory.
    assert (b / "app" / "backend" / "agent_space" / "workspace" / "icon_plan.json").read_text(
        encoding="utf-8"
    ) == "from-b-absolute"
    assert (a / "icon_plan.json").read_text(encoding="utf-8") == "from-a"


def test_make_local_backend_default_route_uses_virtual_mode(monkeypatch, tmp_path):
    """make_local_backend()'s default route (read_file/write_file/edit_file/ls/
    glob/grep for render_spec.json, icon_plan.json, etc.) must use
    virtual_mode=True — flipping this back to False reopens the absolute-path
    leak covered above."""
    monkeypatch.setattr(backends, "MEMORIES_DIR", tmp_path / "memories")
    monkeypatch.setattr(backends, "WORKSPACE", tmp_path / "workspace")
    monkeypatch.setattr(backends, "OUTPUTS_DIR", tmp_path / "outputs")

    backend = backends.make_local_backend()
    assert backend.default.virtual_mode is True


def test_per_thread_memories_subdir_isolates_threads(tmp_path, monkeypatch):
    """The per-thread /memories/ route (subdir="memories") must not collapse onto
    the default route, and must isolate the same way as the default route."""
    from backends import PerThreadFilesystemBackend

    a, b = tmp_path / "ta", tmp_path / "tb"
    backend = PerThreadFilesystemBackend(root_dir=str(tmp_path), subdir="memories", virtual_mode=True)

    _bind(monkeypatch, a)
    write_res = backend.write("/AGENTS.md", "notes-a")
    assert write_res.error is None
    assert (a / "memories" / "AGENTS.md").read_text(encoding="utf-8") == "notes-a"

    _bind(monkeypatch, b)
    assert backend.read("/AGENTS.md").error is not None
    assert not (b / "memories").exists() or not (b / "memories" / "AGENTS.md").exists()


def test_global_memory_route_resolves_to_memories_dir(tmp_path, monkeypatch):
    """Regression test for Bug D: /global-memories/ used to be rooted one directory
    level too high (AGENT_SPACE instead of AGENT_SPACE/memories), so the durable
    shared-memory file was never actually found."""
    monkeypatch.setattr(backends, "MEMORIES_DIR", tmp_path / "memories")
    monkeypatch.setattr(backends, "WORKSPACE", tmp_path / "workspace")
    monkeypatch.setattr(backends, "OUTPUTS_DIR", tmp_path / "outputs")
    (tmp_path / "memories").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memories" / "AGENTS.md").write_text("global notes", encoding="utf-8")

    backend = backends.make_local_backend()
    result = backend.read("/global-memories/AGENTS.md")
    assert result.error is None
    assert "global notes" in result.file_data["content"]


def test_skills_dir_route_resolves_regardless_of_bound_thread_workspace(tmp_path, monkeypatch):
    """Regression test: deepagents' SkillsMiddleware calls backend.ls()/read() with
    the real absolute SKILLS_DIR path (see agent.py's *_SKILL_PATHS, e.g.
    WBS_PLANNER_SKILL_PATHS). Without a dedicated route, that absolute path falls
    to the per-thread default route and gets re-rooted under whatever thread's
    workspace happens to be bound — producing "path_not_found" for every
    subagent's skill load, regardless of which thread is running."""
    _bind(monkeypatch, tmp_path / "some-thread-workspace")

    backend = backends.make_local_backend()
    # Mirrors agent.py's *_SKILL_PATHS construction (Path.as_posix(), not str()) —
    # str(Path) uses backslashes on Windows, which would never match the
    # forward-slash route prefix CompositeBackend expects.
    skill_dir = (backends.SKILLS_DIR / "wbs-planning").as_posix()

    ls_result = backend.ls(skill_dir)
    assert ls_result.error is None, ls_result.error
    names = [e["path"] for e in (ls_result.entries or [])]
    assert any("SKILL.md" in n for n in names), names

    read_result = backend.read(f"{skill_dir}/SKILL.md")
    assert read_result.error is None, read_result.error
    assert "wbs-planning" in read_result.file_data["content"]


def test_requirements_md_lands_in_per_thread_workspace(tmp_path, monkeypatch):
    """Regression test: requirements.md must never be written to the shared
    WORKSPACE root for a real (non-default) thread_id."""
    monkeypatch.setattr(backends, "WORKSPACES_DIR", tmp_path / "workspaces")
    monkeypatch.setattr(backends, "WORKSPACE", tmp_path / "workspace")

    ws = resolve_workspace("thread-real-user")
    req_file = ws / "requirements.md"
    req_file.write_text("some uploaded requirement doc", encoding="utf-8")

    assert req_file.exists()
    assert not (backends.WORKSPACE / "requirements.md").exists()
    assert str(tmp_path / "workspaces") in str(req_file)
