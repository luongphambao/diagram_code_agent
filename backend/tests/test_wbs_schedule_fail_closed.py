"""HIGH-5 fix: a WBS's Delivery Plan must not fabricate a schedule.

Before this fix, `compute_wbs_rollup` ran CPM whenever ANY item had a PERT
3-point estimate — even with zero real dependency edges. With no edges,
`critical_path()`'s Kahn pass "succeeds" trivially (every task has indeg=0),
every `early_start` collapses to 0, `project_duration_md` becomes the single
longest task's duration dressed up as "the project duration", the critical
path is empty, and `assign_sprints()` then maps every task to sprint 1
regardless of how many sprints the timeline declares. 9 of 12 real wbs.json
artifacts audited in docs/codex/multi-agent-architecture-review-2026-07-30.md
(HIGH-5) shipped exactly this pattern as a client deliverable.

`schedule_status` ("planned" | "not_planned" | "cycle_detected") makes the
distinction explicit end to end: wbs_effort.critical_path -> compute_wbs_rollup
-> plan_timeline_and_sprints -> a blocking anomaly rule in
solution_validator.py -> export_wbs_excel's pre-write release gate.
"""

from __future__ import annotations

import contextvars
import json

import backends
from wbs_effort import critical_path
from wbs_tools import (
    LeafIn,
    ModuleMeta,
    PhaseMeta,
    ProjectInfo,
    add_wbs_items,
    compute_wbs_rollup,
    draft_wbs_skeleton,
    export_wbs_excel,
    plan_timeline_and_sprints,
)


def _bind(monkeypatch, ws):
    ws.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends,
        "_current_workspace",
        contextvars.ContextVar("current_workspace", default=ws),
    )


def _draft_skeleton():
    draft_wbs_skeleton.func(
        project_info=ProjectInfo(name="Demo", project_code="DMO"),
        phases=[
            PhaseMeta(code="II", name="DEVELOPMENT", modules=[ModuleMeta(code="II.A", name="Web Portal")])
        ],
    )


# --- wbs_effort.critical_path: the CPM-level fix -----------------------------


def test_critical_path_multiple_isolated_pert_items_is_not_planned():
    # 3 isolated tasks, each with a real 3-point PERT estimate, but NO
    # dependency edges declared — the exact shape that used to trigger CPM
    # and silently produce early_start=0 for all three.
    items = [
        {"ref_code": f"T{i}", "total": 10, "pert_expected_md": 4.0, "predecessors": [], "dependencies": []}
        for i in range(3)
    ]
    res = critical_path(items)

    assert res["schedule_status"] == "not_planned"
    assert res["project_duration_md"] is None
    assert res["critical_path_ref_codes"] == []
    for it in res["items"]:
        assert it["early_start"] is None
        assert it["critical"] is False


def test_critical_path_real_dependency_is_planned():
    items = [
        {"ref_code": "A", "total": 3, "pert_expected_md": 0, "predecessors": [], "dependencies": []},
        {"ref_code": "B", "total": 5, "pert_expected_md": 0, "predecessors": ["A"], "dependencies": []},
    ]
    res = critical_path(items)

    assert res["schedule_status"] == "planned"
    assert res["project_duration_md"] == 8.0


# --- compute_wbs_rollup / plan_timeline_and_sprints: the tool-level fix -----


def test_pert_only_no_dependencies_is_not_planned_end_to_end(tmp_path, monkeypatch):
    _bind(monkeypatch, tmp_path / "ws")
    _draft_skeleton()
    add_wbs_items.func(
        items=[
            LeafIn(phase_code="II", module_code="II.A", name="Login", be=2, fe=2, likely=4),
            LeafIn(phase_code="II", module_code="II.A", name="Dashboard", be=3, fe=2, likely=5),
            LeafIn(phase_code="II", module_code="II.A", name="Settings", be=2, fe=1, likely=3),
            # no predecessors on any item — only PERT estimates.
        ]
    )

    rollup_msg = compute_wbs_rollup.func()
    assert "Schedule NOT planned" in rollup_msg

    wbs = json.loads((tmp_path / "ws" / "wbs.json").read_text(encoding="utf-8"))
    assert wbs["schedule_status"] == "not_planned"
    assert "critical_path" not in wbs
    for it in wbs["items"]:
        assert it.get("early_start") is None
        assert it.get("assigned_sprint") is None

    timeline_msg = plan_timeline_and_sprints.func()
    assert "schedule not planned" in timeline_msg.lower()

    wbs = json.loads((tmp_path / "ws" / "wbs.json").read_text(encoding="utf-8"))
    assert wbs["timeline"]["schedule_status"] == "not_planned"
    # Sprint assignment must NOT have run — no item should carry a sprint number.
    for it in wbs["items"]:
        assert it.get("assigned_sprint") is None


def test_real_predecessors_produce_a_real_schedule_end_to_end(tmp_path, monkeypatch):
    _bind(monkeypatch, tmp_path / "ws")
    _draft_skeleton()
    add_wbs_items.func(
        items=[
            # optimistic=likely=pessimistic gives an exact PERT of 4.0 (avoids
            # the (O+4M+P)/6 weighting so the expected early_start is simple).
            LeafIn(
                phase_code="II",
                module_code="II.A",
                name="Login",
                be=2,
                fe=2,
                optimistic=4,
                likely=4,
                pessimistic=4,
            ),
            LeafIn(
                phase_code="II",
                module_code="II.A",
                name="Dashboard",
                be=3,
                fe=2,
                likely=5,
                predecessors=["DMO-1"],
            ),
        ]
    )

    rollup_msg = compute_wbs_rollup.func()
    assert "Critical path" in rollup_msg

    wbs = json.loads((tmp_path / "ws" / "wbs.json").read_text(encoding="utf-8"))
    assert wbs["schedule_status"] == "planned"
    assert "critical_path" in wbs
    assert wbs["items"][1]["early_start"] == 4.0  # starts after Login (pert 4.0) finishes

    plan_timeline_and_sprints.func()
    wbs = json.loads((tmp_path / "ws" / "wbs.json").read_text(encoding="utf-8"))
    assert wbs["timeline"]["schedule_status"] == "planned"
    assert wbs["items"][0]["assigned_sprint"] == 1


# --- solution_validator Rule 11: sprint-assignment anomaly ------------------


def test_sprint_anomaly_rule_fires_on_degenerate_all_sprint_1(monkeypatch):
    from solution_validator import evaluate_solution

    wbs = {
        "items": [{"ref_code": f"T{i}", "assigned_sprint": 1} for i in range(9)]
        + [{"ref_code": "T9", "assigned_sprint": 2}],
        "timeline": {"sprints": 5},
    }
    findings = evaluate_solution({}, {"nodes": [], "clusters": [], "edges": []}, wbs)

    titles = [f.title for f in findings]
    assert any("Sprint assignment anomaly" in t for t in titles)
    anomaly = next(f for f in findings if "Sprint assignment anomaly" in f.title)
    assert anomaly.severity == "high"


def test_sprint_anomaly_rule_does_not_fire_on_a_real_spread(monkeypatch):
    from solution_validator import evaluate_solution

    wbs = {
        "items": [{"ref_code": f"T{i}", "assigned_sprint": (i % 5) + 1} for i in range(10)],
        "timeline": {"sprints": 5},
    }
    findings = evaluate_solution({}, {"nodes": [], "clusters": [], "edges": []}, wbs)

    assert not any("Sprint assignment anomaly" in f.title for f in findings)


def test_sprint_anomaly_rule_does_not_fire_when_not_planned(monkeypatch):
    """not_planned WBS items never carry assigned_sprint at all — the rule
    must not misfire on a schedule that was correctly left un-planned."""
    from solution_validator import evaluate_solution

    wbs = {
        "items": [{"ref_code": f"T{i}", "assigned_sprint": None} for i in range(10)],
        "timeline": {"sprints": 5, "schedule_status": "not_planned"},
    }
    findings = evaluate_solution({}, {"nodes": [], "clusters": [], "edges": []}, wbs)

    assert not any("Sprint assignment anomaly" in f.title for f in findings)


# --- export_wbs_excel: the release-gate wiring ------------------------------


def _write_minimal_solution_context(ws) -> None:
    (ws / "architecture_analysis.json").write_text(
        json.dumps({"application_type": "web_application", "scale_level": "large"}), encoding="utf-8"
    )
    (ws / "diagram_brief.json").write_text(
        json.dumps({"objective": "x", "functional_requirements": []}), encoding="utf-8"
    )
    (ws / "tech_stack.json").write_text(json.dumps({}), encoding="utf-8")
    (ws / "blueprint.json").write_text(
        json.dumps(
            {
                "slide_title": "x",
                "pattern": "three_tier",
                "pattern_rationale": "x",
                "clusters": [],
                "nodes": [],
                "edges": [],
            }
        ),
        encoding="utf-8",
    )


def test_export_wbs_excel_blocked_by_sprint_anomaly_writes_no_file(tmp_path, monkeypatch):
    _bind(monkeypatch, tmp_path / "ws")
    ws = tmp_path / "ws"
    _write_minimal_solution_context(ws)
    (ws / "wbs.json").write_text(
        json.dumps(
            {
                "phases": [{"code": "II", "name": "DEV", "modules": []}],
                "items": [{"ref_code": f"T{i}", "assigned_sprint": 1} for i in range(9)]
                + [{"ref_code": "T9", "assigned_sprint": 2}],
                "timeline": {"sprints": 5},
                "effort_totals": {"total_mandays": 10},
            }
        ),
        encoding="utf-8",
    )

    result = export_wbs_excel.func()

    assert "RELEASE GATE BLOCKED" in result
    assert not (ws / "wbs_filled.xlsx").exists()
