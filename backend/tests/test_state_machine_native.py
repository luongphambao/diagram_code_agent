"""State Machine Diagram — improvement plan MVP-3 phase 4.

Covers: the StateMachineSpec schema, the native renderer
(prettygraph.native.state_machine), its registration into
prettygraph.native.registry + dispatch through topology.build_tree, the
state-machine structural linter (proposal §5's highest-value checks), the
transition-table CSV export, the code-first `StateMachine` DSL
(prettygraph.state_machine_dsl), and render_typed_diagram end to end — same
code-first shape as Sequence/ERD (phases 2-3).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import backends
from prettygraph.native.registry import RENDERERS
from prettygraph.native.state_machine import build_state_machine_tree, state_machine_semantic_ids
from prettygraph.native.topology import build_drawio_from_spec, build_tree
from prettygraph.state_machine_dsl import StateMachine
from tools.analysis.state_machine_tools import (
    _build_state_machine_render_spec,
    lint_state_machine,
    transition_table_csv,
)
from tools.rendering_tools import render_typed_diagram
from tools.schemas.state_machine import StateMachineSpec


def _lifecycle_dict() -> dict:
    """The proposal §5 supplier-order-lifecycle example as a render_spec dict."""
    return {
        "kind": "state_machine",
        "title": "Supplier Order Lifecycle",
        "states": [
            {"id": "start", "label": "start", "kind": "initial"},
            {"id": "pending", "label": "Pending", "kind": "normal"},
            {"id": "enriched", "label": "Enriched", "kind": "normal"},
            {"id": "supplier_accepted", "label": "Supplier Accepted", "kind": "normal"},
            {"id": "closed", "label": "Closed", "kind": "final"},
        ],
        "transitions": [
            {"from": "start", "to": "pending", "event": "created", "actor": "system"},
            {
                "from": "pending",
                "to": "enriched",
                "event": "enrich_success",
                "guard": "data valid",
                "actor": "system",
            },
            {
                "from": "enriched",
                "to": "supplier_accepted",
                "event": "confirm_demo",
                "guard": "permission: demo.confirm",
                "actor": "supplier",
            },
            {"from": "supplier_accepted", "to": "closed", "event": "close", "actor": "admin"},
        ],
    }


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #


def test_schema_from_alias_and_defaults():
    spec = StateMachineSpec(
        states=[{"id": "a", "label": "A", "kind": "initial"}],
        transitions=[{"from": "a", "to": "a", "event": "loop"}],
    )
    assert spec.kind == "state_machine"
    assert spec.transitions[0].from_ == "a"


def test_render_spec_projection_shape():
    spec = StateMachineSpec(**_lifecycle_dict())
    render_spec = _build_state_machine_render_spec(spec)
    assert render_spec["kind"] == "state_machine"
    assert render_spec["states"][0]["kind"] == "initial"
    assert render_spec["transitions"][0]["from"] == "start"


# --------------------------------------------------------------------------- #
# registry dispatch
# --------------------------------------------------------------------------- #


def test_state_machine_registered_as_native_renderer():
    entry = RENDERERS.get("state_machine")
    assert entry is not None
    assert entry.backend == "native"
    assert entry.tree_builder is build_state_machine_tree
    assert entry.lint_kind == "state_machine"


def test_build_tree_dispatches_to_state_machine_for_registered_kind():
    d, root = build_tree(_lifecycle_dict())
    assert root["kind"] == "state_machine"
    assert "start" in root["states"]


# --------------------------------------------------------------------------- #
# renderer geometry
# --------------------------------------------------------------------------- #


def test_renders_semantic_shapes_and_valid_xml():
    xml, stats = build_drawio_from_spec(_lifecycle_dict(), "Supplier Order Lifecycle")
    assert stats["style_preset"] == "state_machine"
    root = ET.fromstring(xml)
    assert root.tag == "mxfile"
    ids = {c.get("id") for c in root.iter("mxCell")}
    assert "start" in ids  # initial
    assert "closed" in ids and "closed_dot" in ids  # final = outer ring + inner dot


def test_states_layer_by_bfs_distance_from_initial():
    d, _ = build_state_machine_tree(_lifecycle_dict())
    assert d.R["start"]["x"] < d.R["pending"]["x"] < d.R["enriched"]["x"]
    assert d.R["enriched"]["x"] < d.R["supplier_accepted"]["x"] < d.R["closed"]["x"]


def test_retry_loop_back_edge_does_not_inflate_layering():
    """Regression for a real bug: a rework/retry loop back to an upstream
    state (e.g. a rejected review returning to an earlier state, not the
    initial one) is a valid pattern lint_state_machine allows — but the old
    `_layer_states` relaxed layers along the cycle for `len(ids)+1` passes
    without excluding the back-edge, inflating every state on the cycle's
    layer by roughly the cycle length per pass instead of converging, which
    blew the page out to tens of thousands of px wide. Excluding back-edges
    (found via DFS) from the layering pass keeps it a bounded, readable DAG
    rank while the actual back-edge is still drawn as a real transition."""
    spec = {
        "kind": "state_machine",
        "title": "Retry Loop",
        "states": [
            {"id": "start", "label": "start", "kind": "initial"},
            {"id": "received", "label": "Received", "kind": "normal"},
            {"id": "reviewed", "label": "Reviewed", "kind": "normal"},
            {"id": "disputed", "label": "Disputed", "kind": "normal"},
            {"id": "posted", "label": "Posted", "kind": "final"},
        ],
        "transitions": [
            {"from": "start", "to": "received", "event": "received"},
            {"from": "received", "to": "reviewed", "event": "reviewed", "actor": "accountant"},
            {"from": "reviewed", "to": "posted", "event": "approved", "actor": "accountant"},
            {"from": "reviewed", "to": "disputed", "event": "rejected", "actor": "accountant"},
            {"from": "disputed", "to": "received", "event": "corrected", "actor": "supplier"},
        ],
    }
    d, _ = build_state_machine_tree(spec)
    # A clean DAG rank of 5 states should never need more than a few hundred
    # px per layer; the pre-fix version landed "received" past x=20000.
    max_x = max(r["x"] for r in d.R.values() if "x" in r)
    assert max_x < 2000
    assert d.R["start"]["x"] < d.R["received"]["x"] < d.R["reviewed"]["x"] < d.R["disputed"]["x"]


def test_semantic_ids_cover_states_and_transition_pairs():
    ids, edges = state_machine_semantic_ids(_lifecycle_dict())
    assert set(ids) == {"start", "pending", "enriched", "supplier_accepted", "closed"}
    assert ("start", "pending") in edges


def test_final_state_registered_geometry_matches_emitted_xml_geometry():
    """Same class of regression as Sequence's actor fix / ERD's table anchor
    check: the final state's OUTER ring is the id message routing keys off,
    and its geometry in d.R must match what actually got emitted."""
    d, _ = build_state_machine_tree(_lifecycle_dict())
    xml = d.mxfile("Supplier Order Lifecycle")
    root = ET.fromstring(xml)
    cell = next(c for c in root.iter("mxCell") if c.get("id") == "closed")
    geom = cell.find("mxGeometry")
    r = d.R["closed"]
    assert float(geom.get("height")) == r["h"]
    assert float(geom.get("y")) == r["y"]


# --------------------------------------------------------------------------- #
# transition-table CSV export (proposal §5's table, deterministic)
# --------------------------------------------------------------------------- #


def test_transition_table_csv_matches_declared_transitions():
    csv_text = transition_table_csv(_lifecycle_dict())
    lines = csv_text.strip().splitlines()
    assert lines[0] == "current_state,event,guard,actor,next_state"
    assert len(lines) == 5  # header + 4 transitions
    assert "Pending,enrich_success,data valid,system,Enriched" in lines


# --------------------------------------------------------------------------- #
# structural lint (proposal §5's validation list)
# --------------------------------------------------------------------------- #


def test_lint_clean_spec_has_no_errors():
    report = lint_state_machine(_lifecycle_dict())
    assert not report.has_errors


def test_lint_catches_no_initial_state():
    spec = _lifecycle_dict()
    spec["states"][0]["kind"] = "normal"
    report = lint_state_machine(spec)
    assert any(f.code == "no_initial_state" for f in report.errors)


def test_lint_catches_unreachable_state():
    spec = _lifecycle_dict()
    spec["states"].append({"id": "orphan", "label": "Orphan", "kind": "normal"})
    report = lint_state_machine(spec)
    assert any(f.code == "unreachable_state" and f.ref == "orphan" for f in report.errors)


def test_lint_catches_dead_end_state():
    spec = _lifecycle_dict()
    spec["states"].append({"id": "dead_end", "label": "Dead End", "kind": "normal"})
    spec["transitions"].append({"from": "pending", "to": "dead_end", "event": "sidetrack", "actor": "system"})
    report = lint_state_machine(spec)
    assert any(f.code == "dead_end_state" and f.ref == "dead_end" for f in report.findings)


def test_lint_catches_final_state_with_outgoing_transition():
    spec = _lifecycle_dict()
    spec["transitions"].append({"from": "closed", "to": "pending", "event": "reopen", "actor": "admin"})
    report = lint_state_machine(spec)
    assert any(f.code == "terminal_with_outgoing" and f.ref == "closed" for f in report.errors)


def test_lint_catches_ambiguous_transition():
    spec = _lifecycle_dict()
    spec["transitions"].append(
        {"from": "pending", "to": "closed", "event": "enrich_success", "guard": "data valid", "actor": "system"}
    )
    report = lint_state_machine(spec)
    assert any(f.code == "ambiguous_transition" for f in report.errors)


def test_lint_catches_missing_actor():
    spec = _lifecycle_dict()
    spec["transitions"][0]["actor"] = ""
    report = lint_state_machine(spec)
    assert any(f.code == "missing_actor" for f in report.findings)


def test_lint_catches_exitless_loop():
    spec = {
        "kind": "state_machine",
        "states": [
            {"id": "start", "label": "start", "kind": "initial"},
            {"id": "a", "label": "A", "kind": "normal"},
            {"id": "b", "label": "B", "kind": "normal"},
        ],
        "transitions": [
            {"from": "start", "to": "a", "event": "go", "actor": "system"},
            {"from": "a", "to": "b", "event": "next", "actor": "system"},
            {"from": "b", "to": "a", "event": "back", "actor": "system"},
        ],
    }
    report = lint_state_machine(spec)
    assert any(f.code == "exitless_loop" for f in report.findings)


def test_lint_catches_duplicate_state_id():
    spec = _lifecycle_dict()
    spec["states"].append({"id": "pending", "label": "Pending again", "kind": "normal"})
    report = lint_state_machine(spec)
    assert any(f.code == "duplicate_state" for f in report.errors)


# --------------------------------------------------------------------------- #
# StateMachine() DSL — code-first authoring surface (no sandbox)
# --------------------------------------------------------------------------- #


def test_dsl_writes_spec_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sm = StateMachine(title="Supplier Order Lifecycle")
    sm.initial("start")
    sm.state("pending", "Pending")
    sm.final("closed", "Closed")
    sm.transition("start", "pending", event="created", actor="system")
    sm.transition("pending", "closed", event="close", actor="admin")
    sm.render("out")

    spec = json.loads((tmp_path / "out.typed_spec.json").read_text())
    assert spec["kind"] == "state_machine"
    assert spec["states"][0]["kind"] == "initial"
    assert spec["states"][2]["kind"] == "final"
    assert spec["transitions"][0]["from"] == "start"


def test_dsl_spec_round_trips_through_validation_and_lint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sm = StateMachine()
    sm.initial("s0")
    sm.final("s1")
    sm.transition("s0", "s1", event="go", actor="system")
    sm.render("out")

    raw = json.loads((tmp_path / "out.typed_spec.json").read_text())
    validated = StateMachineSpec(**raw)
    render_spec = _build_state_machine_render_spec(validated)
    report = lint_state_machine(render_spec)
    assert not report.has_errors


# --------------------------------------------------------------------------- #
# render_typed_diagram tool, end to end (real sandbox subprocess)
# --------------------------------------------------------------------------- #

_LIFECYCLE_SCRIPT = """
from prettygraph.state_machine_dsl import StateMachine

sm = StateMachine(title="Supplier Order Lifecycle")
sm.initial("start")
sm.state("pending", "Pending")
sm.state("enriched", "Enriched")
sm.state("supplier_accepted", "Supplier Accepted")
sm.final("closed", "Closed")

sm.transition("start", "pending", event="created", actor="system")
sm.transition("pending", "enriched", event="enrich_success", guard="data valid", actor="system")
sm.transition("enriched", "supplier_accepted", event="confirm_demo", guard="permission: demo.confirm", actor="supplier")
sm.transition("supplier_accepted", "closed", event="close", actor="admin")

sm.render("out")
"""


def test_render_typed_diagram_state_machine_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVIDER", "local")
    monkeypatch.setenv("APP_ENV", "development")
    token = backends.set_current_workspace(tmp_path)
    try:
        (tmp_path / "diagram_brief.json").write_text("{}", encoding="utf-8")
        result = render_typed_diagram.func(kind="state_machine", code=_LIFECYCLE_SCRIPT)
        assert "Rendered state_machine diagram" in result, result
        assert (tmp_path / "out.drawio").exists()
        assert (tmp_path / "transition_table.csv").exists()
        csv_text = (tmp_path / "transition_table.csv").read_text()
        assert "Pending,enrich_success,data valid,system,Enriched" in csv_text
        stats = json.loads((tmp_path / "out.native_stats.json").read_text())
        assert stats["style_preset"] == "state_machine"
        assert stats["semantic"]["node_recall"] == 1.0
        assert stats["semantic"]["edge_recall"] == 1.0
        assert stats["lint"]["errors"] == []
    finally:
        backends.reset_current_workspace(token)


def test_render_typed_diagram_state_machine_surfaces_lint_findings_without_blocking(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVIDER", "local")
    monkeypatch.setenv("APP_ENV", "development")
    token = backends.set_current_workspace(tmp_path)
    try:
        (tmp_path / "diagram_brief.json").write_text("{}", encoding="utf-8")
        script = (
            "from prettygraph.state_machine_dsl import StateMachine\n"
            "sm = StateMachine()\n"
            "sm.state('a', 'A')\n"  # no initial state declared
            "sm.render('out')\n"
        )
        result = render_typed_diagram.func(kind="state_machine", code=script)
        assert "Rendered state_machine diagram" in result, result
        assert "no_initial_state" in result or "No state declared with kind='initial'" in result
        assert (tmp_path / "out.drawio").exists()
    finally:
        backends.reset_current_workspace(token)
