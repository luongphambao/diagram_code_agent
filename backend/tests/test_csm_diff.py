"""Tests for the change-impact diff (csm_diff.py).

Covers diff_entities (add/remove/change keyed by id), diff_trace_links (by triple),
and diff_solution_models summary counts incl. the no-change (idempotent) case.
"""

from memory.stores.csm import Requirement, SolutionModel, TraceLink, WorkItem
from memory.stores.csm_diff import diff_entities, diff_solution_models, diff_trace_links


def _req(i, statement, status="pending"):
    return Requirement(id=f"REQ-{i}", statement=statement, status=status)


# --- diff_entities ----------------------------------------------------------

def test_diff_entities_add_remove_change():
    old = [_req(1, "A"), _req(2, "B"), _req(3, "C")]
    new = [_req(1, "A"), _req(2, "B-edited"), _req(4, "D")]   # REQ-3 removed, REQ-4 added, REQ-2 changed
    d = diff_entities(old, new)
    assert {e["id"] for e in d["added"]} == {"REQ-4"}
    assert {e["id"] for e in d["removed"]} == {"REQ-3"}
    assert [c["id"] for c in d["changed"]] == ["REQ-2"]
    assert d["changed"][0]["old"]["statement"] == "B"
    assert d["changed"][0]["new"]["statement"] == "B-edited"


def test_diff_entities_no_change_is_empty():
    old = [_req(1, "A"), _req(2, "B")]
    new = [_req(1, "A"), _req(2, "B")]
    d = diff_entities(old, new)
    assert d == {"added": [], "removed": [], "changed": []}


def test_rename_is_a_change_not_add_remove():
    # Same stable id, different statement -> reported once as changed.
    d = diff_entities([_req(1, "Old name")], [_req(1, "New name")])
    assert not d["added"] and not d["removed"]
    assert [c["id"] for c in d["changed"]] == ["REQ-1"]


# --- diff_trace_links -------------------------------------------------------

def test_diff_trace_links_by_triple():
    old = [TraceLink(from_id="REQ-1", to_id="COMP-a", relation="satisfies")]
    new = [
        TraceLink(from_id="REQ-1", to_id="COMP-a", relation="satisfies"),   # unchanged
        TraceLink(from_id="WBS-1", to_id="COMP-a", relation="implements"),  # added
    ]
    d = diff_trace_links(old, new)
    assert len(d["added"]) == 1 and d["added"][0]["from_id"] == "WBS-1"
    assert d["removed"] == []


def test_diff_trace_links_ignores_confidence_change():
    # Same endpoints+relation, only confidence differs -> not reported.
    old = [TraceLink(from_id="REQ-1", to_id="COMP-a", relation="satisfies", confidence=0.5)]
    new = [TraceLink(from_id="REQ-1", to_id="COMP-a", relation="satisfies", confidence=0.9)]
    d = diff_trace_links(old, new)
    assert d["added"] == [] and d["removed"] == []


# --- diff_solution_models ---------------------------------------------------

def _model(reqs, work_items=None, links=None, revision=1):
    return SolutionModel(revision=revision, requirements=reqs,
                         work_items=work_items or [], trace_links=links or [])


def test_diff_solution_models_summary_counts():
    old = _model([_req(1, "A"), _req(2, "B")], revision=1)
    new = _model(
        [_req(1, "A"), _req(2, "B-edited")],
        work_items=[WorkItem(id="WBS-1", name="New task")],
        revision=2,
    )
    d = diff_solution_models(old, new)
    assert d["revision"] == {"from": 1, "to": 2}
    s = d["summary"]
    assert s["entities_added"] == 1       # WBS-1
    assert s["entities_removed"] == 0
    assert s["entities_changed"] == 1     # REQ-2
    assert d["requirements"]["changed"][0]["id"] == "REQ-2"
    assert d["work_items"]["added"][0]["id"] == "WBS-1"


def test_diff_solution_models_identical_has_no_phantom_changes():
    old = _model([_req(1, "A")], work_items=[WorkItem(id="WBS-1", name="T")])
    new = _model([_req(1, "A")], work_items=[WorkItem(id="WBS-1", name="T")], revision=2)
    s = diff_solution_models(old, new)["summary"]
    assert s == {"entities_added": 0, "entities_removed": 0, "entities_changed": 0,
                 "links_added": 0, "links_removed": 0}


def test_workitem_predecessors_change_is_detected():
    old = _model([], work_items=[WorkItem(id="WBS-2", name="T", predecessors=[])])
    new = _model([], work_items=[WorkItem(id="WBS-2", name="T", predecessors=["BNK-1"])])
    d = diff_solution_models(old, new)
    assert d["work_items"]["changed"][0]["id"] == "WBS-2"
    assert d["summary"]["entities_changed"] == 1
