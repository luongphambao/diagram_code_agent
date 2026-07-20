"""BPMN swimlane builder — ported from drawio-ai-kit/src/bpmn.mjs + catalog/bpmn.json.

Covers: the pool/lane/phase primitive (already ported in layout_engine.py)
wired to the 19 BPMN stencils, the process render_spec branch in topology.py
(never composes with the architecture/refined paths), the "bpmn" scorecard
profile (no icon/zone/ratio bar), and the catalog-pollution guard that keeps
generic architecture searches from resolving to a BPMN shape.
"""

from __future__ import annotations

import domain.diagram.drawio_catalog as dc
import domain.validation.validate_drawio as vd
from prettygraph.native import bpmn
from prettygraph.native.topology import build_drawio_from_spec, build_tree


def _order_process(*, second_branch: bool = True) -> dict:
    """Order-management swimlane: Customer/Sales/Warehouse x Order/Fulfill/Ship."""
    steps = [
        {"id": "s", "kind": "start", "type": "none", "lane": 0, "col": 0, "label": "Order placed"},
        {"id": "g", "kind": "gateway", "type": "exclusive", "lane": 1, "col": 0, "label": "In stock?"},
        {"id": "t1", "kind": "user_task", "lane": 1, "col": 1, "label": "Approve order"},
        {"id": "t2", "kind": "service_task", "lane": 2, "col": 1, "label": "Pick items"},
        {"id": "e", "kind": "end", "type": "none", "lane": 2, "col": 2, "label": "Shipped"},
    ]
    flows = [
        {"from": "s", "to": "g", "kind": "sequence"},
        {"from": "g", "to": "t1", "kind": "sequence", "label": "in stock"},
        {"from": "t1", "to": "t2", "kind": "message"},
        {"from": "t2", "to": "e", "kind": "sequence"},
    ]
    if second_branch:
        steps.append({"id": "e2", "kind": "end", "type": "cancel", "lane": 1, "col": 2,
                      "label": "Out of stock"})
        flows.append({"from": "g", "to": "e2", "kind": "sequence", "label": "out of stock"})
    return {"process": {
        "label": "Order Management",
        "lanes": ["Customer", "Sales", "Warehouse"],
        "phases": ["Order", "Fulfill", "Ship"],
        "steps": steps,
        "flows": flows,
    }}


# --------------------------------------------------------------------------- #
# bpmn.py creators
# --------------------------------------------------------------------------- #

def test_creators_resolve_every_catalog_stencil():
    """All 19 catalog stencils are reachable through the creators (no KeyError)."""
    nodes = [
        bpmn.start("s1"), bpmn.start("s2", type="message"), bpmn.start("s3", type="timer"),
        bpmn.intermediate("i1"), bpmn.intermediate("i2", type="timer"),
        bpmn.intermediate("i3", type="link"),
        bpmn.end("e1"), bpmn.end("e2", type="terminate"), bpmn.end("e3", type="error"),
        bpmn.end("e4", type="cancel"),
        bpmn.gateway("g1"), bpmn.gateway("g2", type="parallel"),
        bpmn.gateway("g3", type="inclusive"), bpmn.gateway("g4", type="event"),
        bpmn.user_task("t1"), bpmn.service_task("t2"), bpmn.manual_task("t3"),
        bpmn.script_task("t4"), bpmn.business_rule_task("t5"),
    ]
    assert len(nodes) == 19
    for n in nodes:
        assert n["kind"] == "box"
        assert "style" in n and "mxgraph.bpmn." in n["style"]


def test_task_and_sub_process_are_composed_not_stenciled():
    t = bpmn.task("t")
    sp = bpmn.sub_process("sp")
    assert "style" not in t and t["round"] is True
    assert "style" not in sp and sp["round"] is True
    assert sp["w"] > t["w"] and sp["h"] > t["h"]


def test_unknown_stencil_name_raises():
    import pytest
    with pytest.raises(KeyError):
        bpmn._look("bpmn_does_not_exist")


# --------------------------------------------------------------------------- #
# topology.py process branch
# --------------------------------------------------------------------------- #

def test_process_spec_builds_pool_with_lanes_and_phases():
    xml, stats = build_drawio_from_spec(_order_process(), "Order Management")
    assert 'shape=mxgraph.bpmn.event' in xml
    assert 'shape=mxgraph.bpmn.gateway2' in xml
    assert 'shape=mxgraph.bpmn.task2' in xml
    for lane in ("Customer", "Sales", "Warehouse"):
        assert lane in xml
    for phase in ("Order", "Fulfill", "Ship"):
        assert phase in xml
    assert "Order Management" in xml


def test_process_branch_never_reaches_refined_or_cluster_logic():
    """A spec with BOTH process and style_preset=refined must still render as
    BPMN — process short-circuits before the refined dispatch in build_tree."""
    spec = _order_process()
    spec["style_preset"] = "refined"
    d, tree = build_tree(spec)
    assert tree["kind"] == "pool"
    xml = d.mxfile("t")
    assert "tab_zone_" not in xml  # refined page-template chrome never appears
    assert "mxgraph.bpmn." in xml


def test_process_diagram_validates_clean_and_scores_pass(tmp_path):
    xml, _ = build_drawio_from_spec(_order_process(), "Order Management")
    p = tmp_path / "bpmn.drawio"
    p.write_text(xml, encoding="utf-8")
    report = vd.validate_file(str(p))
    assert report["error_count"] == 0
    assert report["collision_count"] == 0
    sc = vd.production_scorecard(report, {
        "edges": 5, "style_preset": "bpmn",
        "semantic": {"node_recall": 1.0, "edge_recall": 1.0}})
    assert sc["pass"], sc["breakdown"]
    assert sc["style_preset"] == "bpmn"
    # No icon/zone/ratio bar for a pool — both dimensions score full marks.
    assert sc["breakdown"]["iconography"] == 10.0
    assert sc["breakdown"]["composition"] == 10.0


def test_single_branch_gateway_flagged_and_penalized(tmp_path):
    """A gateway with only 1 outgoing flow doesn't split — audit_bpmn should
    flag it, and the bpmn scorecard profile should pay for it."""
    xml, _ = build_drawio_from_spec(_order_process(second_branch=False), "t")
    p = tmp_path / "bpmn.drawio"
    p.write_text(xml, encoding="utf-8")
    report = vd.validate_file(str(p))
    assert any("gateway" in a.lower() and "split" in a.lower() for a in report["advice"])
    sc = vd.production_scorecard(report, {
        "edges": 4, "style_preset": "bpmn",
        "semantic": {"node_recall": 1.0, "edge_recall": 1.0}})
    assert sc["breakdown"]["connector_readability"] < 15.0


def test_pool_bands_do_not_false_positive_as_sibling_overlaps(tmp_path):
    """Regression: lane bands/labels/phase headers are siblings (same parent=
    pool) of every step placed in their cell — that overlap is by design and
    must not surface as a structural warning."""
    xml, _ = build_drawio_from_spec(_order_process(), "t")
    p = tmp_path / "bpmn.drawio"
    p.write_text(xml, encoding="utf-8")
    report = vd.validate_file(str(p))
    assert not any("overlap" in w for w in report["warnings"])


# --------------------------------------------------------------------------- #
# catalog pollution guard
# --------------------------------------------------------------------------- #

def test_generic_queries_never_resolve_to_bpmn_stencils():
    cat = dc.load_catalog()
    for query in ("gateway", "task", "user", "service"):
        hits = dc.search_icon(cat, query, limit=8)
        assert not any(h["name"].startswith("bpmn_") for h in hits), (query, hits)


def test_bpmn_prefixed_query_can_still_reach_bpmn_stencils():
    cat = dc.load_catalog()
    hits = dc.search_icon(cat, "bpmn gateway", limit=8)
    assert any(h["name"].startswith("bpmn_") for h in hits)


def test_bpmn_category_filter_reaches_bpmn_stencils():
    cat = dc.load_catalog()
    hits = dc.search_icon(cat, "task", category="BPMN", limit=8)
    assert hits and all(h["name"].startswith("bpmn_") for h in hits)


def test_catalog_has_all_19_bpmn_stencils():
    cat = dc.load_catalog()
    names = [n for n in cat.valid_names if n.startswith("bpmn_")]
    assert len(names) == 19
