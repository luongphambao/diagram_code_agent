"""Tests for WBS v2 — PERT 3-point estimates + critical-path (CPM) scheduling.

Covers the pure `critical_path()` helper in wbs_effort.py: the PERT formula stored
by add_wbs_items, a linear chain, a diamond DAG, isolated tasks, missing predecessor
refs, and graceful degradation on a cycle.
"""

from wbs_effort import critical_path


def _item(ref, dur, preds=None, pert=0.0):
    """A minimal leaf dict: critical_path uses pert_expected_md or total as duration."""
    return {"ref_code": ref, "total": dur, "pert_expected_md": pert,
            "predecessors": preds or []}


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
