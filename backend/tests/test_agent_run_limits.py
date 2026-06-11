import json
from pathlib import Path
from types import SimpleNamespace

from diagram_mcp import tools
from diagram_mcp.agent import DRAWER_SKILL_PATHS


def _use_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    monkeypatch.setattr(tools, "_ARCH_ANALYSIS_FILE", tmp_path / "architecture_analysis.json")
    monkeypatch.setattr(tools, "_BRIEF_FILE", tmp_path / "diagram_brief.json")
    monkeypatch.setattr(tools, "_TECHSTACK_FILE", tmp_path / "tech_stack.json")
    monkeypatch.setattr(tools, "_BLUEPRINT_FILE", tmp_path / "blueprint.json")
    monkeypatch.setattr(tools, "_CRITIQUE_FILE", tmp_path / "critique.json")
    monkeypatch.setattr(tools, "_RENDER_COUNT_FILE", tmp_path / "render_count.json")
    monkeypatch.setattr(tools, "_ICON_SEARCH_BUDGET_FILE", tmp_path / "icon_search_budget.json")
    monkeypatch.setattr(tools, "_NODE_SEARCH_BUDGET_FILE", tmp_path / "node_search_budget.json")
    monkeypatch.setattr(tools, "_REVISION_COUNT_FILE", tmp_path / "revision_count.json")
    monkeypatch.setattr(tools, "_TOOL_SUMMARY_FILE", tmp_path / "tool_budget_summary.json")
    monkeypatch.setattr(tools, "_ICON_PLAN_FILE", tmp_path / "icon_plan.json")


def test_drawer_uses_drawer_skill_paths():
    assert any("/drawer/pro-style" in path for path in DRAWER_SKILL_PATHS)
    assert any("/drawer/diagrams-as-code" in path for path in DRAWER_SKILL_PATHS)


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

    monkeypatch.setattr(tools.subprocess, "run", fail_run)

    msg = tools.render_diagram.func("print('bad')", tool_call_id="tc-1")
    assert "Render #1/6 FAILED" in msg.content
    assert json.loads((tmp_path / "render_count.json").read_text())["count"] == 1

    for i in range(2, tools.RENDER_HARD_CAP + 1):
        msg = tools.render_diagram.func("print('bad')", tool_call_id=f"tc-{i}")
        assert f"Render #{i}/6 FAILED" in msg.content

    exhausted = tools.render_diagram.func("print('bad')", tool_call_id="tc-final")
    assert "RENDER BUDGET EXHAUSTED" in exhausted.content
