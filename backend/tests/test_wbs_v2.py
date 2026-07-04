"""Tests for WBS v2 — PERT 3-point estimates + critical-path (CPM) scheduling.

Covers: the PERT formula, a linear chain, a diamond DAG, isolated tasks, missing
predecessor refs, cycle degradation, plus WBS v2 features: pert_percentile P50/P80,
assign_sprints, CPM with lag (FS), SS/FF relationship types, DoD fields on LeafIn/
DependencyEdge defaults.
"""

from wbs_effort import critical_path, pert_percentile, assign_sprints
from wbs_tools import LeafIn


def _item(ref, dur, preds=None, pert=0.0):
    """A minimal leaf dict: critical_path uses pert_expected_md or total as duration."""
    return {"ref_code": ref, "total": dur, "pert_expected_md": pert,
            "predecessors": preds or [], "dependencies": []}


def _item_v2(ref, dur, deps=None, preds=None, pert=0.0):
    """Leaf with rich dependency edges (WBS v2)."""
    return {"ref_code": ref, "total": dur, "pert_expected_md": pert,
            "predecessors": preds or [], "dependencies": deps or []}


def _by_ref(result):
    return {it["ref_code"]: it for it in result["items"]}


# --- PERT formula -----------------------------------------------------------

def test_pert_formula_expected_value():
    # (O + 4M + P) / 6
    assert round((2 + 4 * 5 + 14) / 6, 4) == 6.0      # classic textbook example
    assert round((1 + 4 * 2 + 3) / 6, 4) == 2.0
    assert round((3 + 4 * 6 + 9) / 6, 4) == 6.0


def test_pert_expected_md_used_as_duration_over_total():
    # When a 3-point estimate is present, it drives the schedule, not `total`.
    items = [_item("A", dur=99, pert=6.0)]
    res = critical_path(items)
    assert res["project_duration_md"] == 6.0


# --- linear chain A -> B -> C ----------------------------------------------

def test_linear_chain_all_critical():
    items = [
        _item("A", 3),
        _item("B", 5, preds=["A"]),
        _item("C", 2, preds=["B"]),
    ]
    res = critical_path(items)
    assert res["project_duration_md"] == 10.0
    assert res["critical_path_ref_codes"] == ["A", "B", "C"]
    b = _by_ref(res)
    assert b["A"]["early_start"] == 0 and b["A"]["early_finish"] == 3
    assert b["B"]["early_start"] == 3 and b["B"]["early_finish"] == 8
    assert b["C"]["early_finish"] == 10
    assert all(b[r]["float_md"] == 0 for r in ("A", "B", "C"))


# --- diamond A -> {B, C} -> D ----------------------------------------------

def test_diamond_critical_path_follows_longer_branch():
    items = [
        _item("A", 2),
        _item("B", 5, preds=["A"]),   # long branch
        _item("C", 1, preds=["A"]),   # short branch -> has float
        _item("D", 3, preds=["B", "C"]),
    ]
    res = critical_path(items)
    assert res["project_duration_md"] == 10.0          # 2 + 5 + 3
    assert res["critical_path_ref_codes"] == ["A", "B", "D"]
    b = _by_ref(res)
    assert b["C"]["float_md"] == 4.0                   # 5 - 1 slack on the short branch
    assert b["C"]["critical"] is False
    assert b["B"]["float_md"] == 0 and b["B"]["critical"] is True


# --- isolated tasks ---------------------------------------------------------

def test_isolated_task_has_no_float():
    items = [_item("A", 3), _item("B", 5, preds=["A"]), _item("X", 4)]  # X is standalone
    res = critical_path(items)
    b = _by_ref(res)
    assert b["X"]["float_md"] is None
    assert b["X"]["critical"] is False
    # the dependent chain still resolves
    assert res["critical_path_ref_codes"] == ["A", "B"]


# --- missing predecessor refs ----------------------------------------------

def test_missing_predecessor_ref_is_ignored():
    items = [_item("A", 3, preds=["GHOST"]), _item("B", 2, preds=["A"])]
    res = critical_path(items)              # GHOST does not exist -> dropped, no crash
    assert res["project_duration_md"] == 5.0
    assert res["critical_path_ref_codes"] == ["A", "B"]


# --- cycle degrades gracefully ---------------------------------------------

def test_cycle_does_not_raise():
    items = [_item("A", 3, preds=["B"]), _item("B", 5, preds=["A"])]
    res = critical_path(items)             # A<->B cycle
    assert res["critical_path_ref_codes"] == []
    b = _by_ref(res)
    assert b["A"]["float_md"] is None and b["B"]["float_md"] is None
    # project duration falls back to the longest single task
    assert res["project_duration_md"] == 5.0


def test_empty_items():
    res = critical_path([])
    assert res["project_duration_md"] == 0.0
    assert res["items"] == [] and res["critical_path_ref_codes"] == []


# --- pert_percentile ---------------------------------------------------------

def test_pert_p50_equals_mean():
    # P50: q=0, result = mu = (O + 4M + P) / 6 = (2 + 20 + 14) / 6 = 6.0
    assert pert_percentile(2, 5, 14, 0.0) == 6.0


def test_pert_p80():
    # mu=6.0, sigma=(14-2)/6=2.0, P80=6+0.842*2=7.684
    o, m, p = 2, 5, 14
    expected = round((o + 4 * m + p) / 6 + 0.842 * (p - o) / 6, 4)
    assert pert_percentile(o, m, p, 0.842) == expected


# --- assign_sprints ----------------------------------------------------------

def test_assign_sprints_sprint1_when_es0():
    items = [{"early_start": 0}]
    assign_sprints(items, 1.0)
    assert items[0]["assigned_sprint"] == 1


def test_assign_sprints_none_when_no_es():
    items = [{"ref_code": "X"}]
    assign_sprints(items, 1.0)
    assert items[0]["assigned_sprint"] is None


# --- CPM with lag (FS + lag_days) --------------------------------------------

def test_cpm_fs_with_lag():
    # A(3d) -FS+2-> B(5d): ES(B) = EF(A) + lag = 3 + 2 = 5
    items = [
        _item_v2("A", 3),
        _item_v2("B", 5, deps=[{"predecessor_ref": "A", "lag_days": 2.0, "relationship": "FS"}]),
    ]
    res = critical_path(items)
    b = {it["ref_code"]: it for it in res["items"]}
    assert b["B"]["early_start"] == 5.0
    assert b["B"]["early_finish"] == 10.0
    assert res["project_duration_md"] == 10.0


# --- CPM SS relationship -----------------------------------------------------

def test_cpm_ss_relationship():
    # A(10d) -SS+1-> B(5d): ES(B) = ES(A) + lag = 0 + 1 = 1, EF(B) = 6
    items = [
        _item_v2("A", 10),
        _item_v2("B", 5, deps=[{"predecessor_ref": "A", "lag_days": 1.0, "relationship": "SS"}]),
    ]
    res = critical_path(items)
    b = {it["ref_code"]: it for it in res["items"]}
    assert b["B"]["early_start"] == 1.0
    assert b["B"]["early_finish"] == 6.0


# --- CPM FF relationship -----------------------------------------------------

def test_cpm_ff_relationship():
    # A(10d) -FF+0-> B(5d): EF(B) >= EF(A) = 10, so ES(B) >= 10 - 5 = 5
    items = [
        _item_v2("A", 10),
        _item_v2("B", 5, deps=[{"predecessor_ref": "A", "lag_days": 0.0, "relationship": "FF"}]),
    ]
    res = critical_path(items)
    b = {it["ref_code"]: it for it in res["items"]}
    assert b["B"]["early_start"] == 5.0
    assert b["B"]["early_finish"] == 10.0


# --- DoD fields ---------------------------------------------------------------

def test_leaf_in_acceptance_criteria():
    leaf = LeafIn(phase_code="I", module_code="I.A", name="Login",
                  acceptance_criteria=["Tests pass", "PR reviewed"])
    assert len(leaf.acceptance_criteria) == 2
    assert leaf.acceptance_criteria[0] == "Tests pass"


def test_leaf_in_acceptance_criteria_default_empty():
    leaf = LeafIn(phase_code="I", module_code="I.A", name="Login")
    assert leaf.acceptance_criteria == []


def test_leaf_in_has_no_rich_dependency_field():
    """DependencyEdge was removed from the model-facing schema (mimo stringify
    surface); the planner supplies plain predecessors only. CPM still reads a
    dependencies key from old wbs.json files."""
    assert "dependencies" not in LeafIn.model_fields


# ─── level_resources (§4.6 Resource leveling) ────────────────────────────────

from wbs_effort import level_resources, MANDAYS_PER_WEEK  # noqa: E402


def _sprint_item(sprint, be=0, fe_mobile=0, ba=0, qc=0, pm=0):
    return {"assigned_sprint": sprint, "be": be, "fe_mobile": fe_mobile,
            "ba": ba, "qc": qc, "pm": pm}


def test_level_resources_no_overload():
    """2 dev FTE × 2-week sprint = 10 MD capacity; 8 MD demand → no overload."""
    items = [_sprint_item(1, be=4, fe_mobile=4)]
    result = level_resources(items, role_fte={"dev": 2.0, "ba": 1.0, "qc": 1.0, "pm": 1.0})
    assert result["overloads"] == []
    assert result["by_sprint"]["1"]["dev"] == 8.0


def test_level_resources_overload_when_demand_exceeds_capacity():
    """1 dev FTE × 2-week sprint = 10 MD capacity; 30 MD demand → overflow."""
    items = [_sprint_item(1, be=30)]
    result = level_resources(items, role_fte={"dev": 1.0, "ba": 0.5, "qc": 0.5, "pm": 0.5})
    overload = next((o for o in result["overloads"] if o["role"] == "dev"), None)
    assert overload is not None
    assert overload["sprint"] == 1
    assert overload["overflow_md"] == 30.0 - 1.0 * 2 * MANDAYS_PER_WEEK


def test_level_resources_capacity_math():
    """capacity = fte × weeks_per_sprint × MANDAYS_PER_WEEK."""
    result = level_resources([], role_fte={"dev": 3.0, "ba": 1.0, "qc": 1.0, "pm": 1.0},
                             weeks_per_sprint=2)
    assert result["capacity"]["dev"] == 3.0 * 2 * MANDAYS_PER_WEEK


def test_level_resources_empty_items():
    result = level_resources([], role_fte={"dev": 2.0, "ba": 1.0, "qc": 1.0, "pm": 1.0})
    assert result["overloads"] == []
    assert result["by_sprint"] == {}
    assert result["peak_util"] == {"dev": None, "ba": None, "qc": None, "pm": None}


def test_level_resources_skips_items_without_sprint():
    """Items with assigned_sprint=None must be ignored (isolated CPM tasks)."""
    items = [
        {"assigned_sprint": None, "be": 50, "fe_mobile": 0, "ba": 0, "qc": 0, "pm": 0},
        _sprint_item(1, be=5),
    ]
    result = level_resources(items, role_fte={"dev": 2.0, "ba": 1.0, "qc": 1.0, "pm": 1.0})
    assert result["overloads"] == []  # only 5 MD in sprint 1, within 10 MD cap


def test_level_resources_multi_sprint_aggregation():
    """Demand aggregates per sprint; only the overloaded sprint reports."""
    items = [
        _sprint_item(1, be=15),  # over 10 MD cap (1 FTE × 2 weeks)
        _sprint_item(2, be=5),   # under cap
    ]
    result = level_resources(items, role_fte={"dev": 1.0, "ba": 1.0, "qc": 1.0, "pm": 1.0})
    overloads = result["overloads"]
    assert len(overloads) == 1
    assert overloads[0]["sprint"] == 1
    assert result["by_sprint"]["2"]["dev"] == 5.0
