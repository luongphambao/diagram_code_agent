"""finalize_wbs runs the whole deterministic tail (rollup → timeline → team →
milestones → validate) in ONE tool call — the model no longer spends five model
turns pressing buttons through the fixed sequence."""

import contextvars
import json

import backends
from wbs_tools import (
    WBS_PLANNER_TOOLS,
    add_wbs_items,
    draft_wbs_skeleton,
    export_wbs_excel,
    finalize_wbs,
    LeafIn,
    PhaseMeta,
    ModuleMeta,
    ProjectInfo,
)


def _bind(monkeypatch, ws):
    ws.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends, "_current_workspace",
        contextvars.ContextVar("current_workspace", default=ws),
    )


def _build_minimal_wbs():
    draft_wbs_skeleton.func(
        project_info=ProjectInfo(name="Demo", project_code="DMO"),
        phases=[PhaseMeta(code="II", name="DEVELOPMENT",
                          modules=[ModuleMeta(code="II.A", name="Web Portal")])],
    )
    add_wbs_items.func(items=[
        LeafIn(phase_code="II", module_code="II.A", name="Login", be=2, fe=2),
        LeafIn(phase_code="II", module_code="II.A", name="Dashboard", be=3, fe=2),
    ])


def test_planner_toolset_is_reduced_to_four():
    names = [t.name for t in WBS_PLANNER_TOOLS]
    assert names == ["load_solution_context", "draft_wbs_skeleton",
                     "add_wbs_items", "finalize_wbs"]


def test_finalize_wbs_runs_full_tail(tmp_path, monkeypatch):
    _bind(monkeypatch, tmp_path / "ws")
    _build_minimal_wbs()

    out = finalize_wbs.func()
    for label in ("[rollup]", "[timeline]", "[team]", "[milestones]", "[validation]"):
        assert label in out, out

    wbs = json.loads((tmp_path / "ws" / "wbs.json").read_text(encoding="utf-8"))
    assert wbs["effort_totals"]["total_mandays"] > 0
    assert wbs["timeline"]["weeks"] >= 4
    assert wbs["team_composition"]
    assert [m["name"] for m in wbs["milestones"]][0] == "Contract Signoff"


def test_finalize_wbs_guards_when_no_items(tmp_path, monkeypatch):
    _bind(monkeypatch, tmp_path / "ws2")
    out = finalize_wbs.func()
    assert "add_wbs_items first" in out


def test_export_wbs_excel_missing_plan_tells_agent_to_continue(tmp_path, monkeypatch):
    _bind(monkeypatch, tmp_path / "ws_export_missing")
    out = export_wbs_excel.func()
    assert "Continue the WBS planning pipeline" in out
    assert "wbs_planner" in out
    assert "blocking error" in out


def test_draft_skeleton_resets_stale_different_project(tmp_path, monkeypatch):
    _bind(monkeypatch, tmp_path / "ws4")
    _build_minimal_wbs()  # project "Demo", 2 items

    out = draft_wbs_skeleton.func(
        project_info=ProjectInfo(name="Other Project", project_code="OTH"),
        phases=[PhaseMeta(code="II", name="DEVELOPMENT",
                          modules=[ModuleMeta(code="II.B", name="Mobile App")])],
    )
    assert "reset stale WBS files from a different project ('Demo')" in out

    wbs = json.loads((tmp_path / "ws4" / "wbs.json").read_text(encoding="utf-8"))
    assert wbs["project_info"]["name"] == "Other Project"
    assert wbs["items"] == []  # old Demo items were not merged in


def test_draft_skeleton_same_project_does_not_reset(tmp_path, monkeypatch):
    _bind(monkeypatch, tmp_path / "ws5")
    _build_minimal_wbs()  # project "Demo", 2 items

    out = draft_wbs_skeleton.func(
        project_info=ProjectInfo(name="Demo", project_code="DMO"),
        phases=[PhaseMeta(code="II", name="DEVELOPMENT",
                          modules=[ModuleMeta(code="II.A", name="Web Portal")])],
    )
    assert "reset stale WBS files" not in out


def test_draft_skeleton_ratio_scalars_override(tmp_path, monkeypatch):
    _bind(monkeypatch, tmp_path / "ws3")
    draft_wbs_skeleton.func(
        project_info=ProjectInfo(name="Demo", project_code="DMO"),
        phases=[PhaseMeta(code="II", name="DEV",
                          modules=[ModuleMeta(code="II.A", name="Web")])],
        qc_on_dev=0.2,
    )
    sk = json.loads((tmp_path / "ws3" / "wbs_skeleton.json").read_text(encoding="utf-8"))
    assert sk["ratios"]["qc_on_dev"] == 0.2
    assert sk["ratios"]["ba_on_dev"] == 0.10  # untouched default
