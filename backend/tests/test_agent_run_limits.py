import contextvars
import json
from pathlib import Path
from types import SimpleNamespace

import backends
import tools
import tools.rendering_tools as rendering_tools
from agent import DRAWER_SKILL_PATHS


def _use_workspace(monkeypatch, tmp_path: Path) -> None:
    """Bind ``tmp_path`` as the current-thread workspace for the duration of the test.

    Stage files are now resolved lazily against ``backends.current_workspace()`` (the
    WorkspaceFile proxies in tools.constants), so a single context-var swap isolates the
    whole tool suite; monkeypatch auto-restores the ContextVar after the test, so no
    state leaks to other tests.
    """
    monkeypatch.setattr(
        backends, "_current_workspace",
        contextvars.ContextVar("current_workspace", default=tmp_path),
    )


def test_drawer_uses_drawer_skill_paths():
    # drawer + main now share one canonical copy (the drawer/* duplicates were
    # consolidated to remove drift) — the drawer still gets both diagram skills.
    normalized = [Path(path).as_posix() for path in DRAWER_SKILL_PATHS]
    assert any(path.endswith("/pro-style") for path in normalized)
    assert any(path.endswith("/diagrams-as-code") for path in normalized)
    assert not any("/drawer/" in path for path in normalized)


def test_search_icons_reuses_cached_result(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)

    first = json.loads(tools.search_icons.func("redis", "aws"))
    second = json.loads(tools.search_icons.func("redis", "aws"))
    state = json.loads((tmp_path / "icon_search_budget.json").read_text())

    assert first["status"] in {"FOUND", "NOT_FOUND"}
    assert second["cached"] is True
    assert state["total_calls"] == 1


def test_failed_render_counts_toward_hard_cap(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    (tmp_path / "blueprint.json").write_text("{}", encoding="utf-8")

    def fail_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=1, stderr="boom", stdout="")

    monkeypatch.setattr(rendering_tools.subprocess, "run", fail_run)

    msg = tools.render_diagram.func("print('bad')", tool_call_id="tc-1")
    assert "Render #1/6 FAILED" in msg.content
    assert json.loads((tmp_path / "render_count.json").read_text())["count"] == 1

    for i in range(2, tools.RENDER_HARD_CAP + 1):
        msg = tools.render_diagram.func("print('bad')", tool_call_id=f"tc-{i}")
        assert f"Render #{i}/6 FAILED" in msg.content

    exhausted = tools.render_diagram.func("print('bad')", tool_call_id="tc-final")
    assert "RENDER BUDGET EXHAUSTED" in exhausted.content
