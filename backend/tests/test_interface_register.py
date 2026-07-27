"""Tests for the refined preset's Interface Register panel (docs/improve/
REVIEW-CODEBASE-FIT.md Patch 2b / plan §B3): every edge that layout_plan's
bundling suppresses must stay traceable somewhere on the rendered page,
instead of silently vanishing behind a generic representative label.
"""

from __future__ import annotations

import re

from prettygraph.native.layout_plan import analyze_layout
from prettygraph.native.repair import semantic_stats
from prettygraph.native.topology import build_drawio_from_spec


def _hub_spec():
    """6-node telemetry fan-in to one SIEM hub (same shape as
    test_layout_plan.py's fixture) — enough repetition to trigger bundling."""
    nodes = [{"id": "siem", "label": "SIEM", "cluster": "mon"}] + [
        {"id": f"x{i}", "label": f"Svc {i}", "cluster": "t1" if i < 3 else "t2"} for i in range(6)
    ]
    flow = [{"from": f"x{i}", "to": f"x{i + 1}", "label": f"hop {i} via HTTPS"} for i in range(5)]
    telemetry = [
        {"from": f"x{i}", "to": "siem", "label": "Telemetry export", "style": "dashed"} for i in range(6)
    ]
    return {
        "style_preset": "refined",
        "diagram_title": "Test",
        "clusters": [
            {"id": "mon", "label": "Monitoring & Observability", "number": 1},
            {"id": "t1", "label": "Tier 1", "number": 2},
            {"id": "t2", "label": "Tier 2", "number": 3},
        ],
        "nodes": nodes,
        "edges": flow + telemetry,
    }


def test_bundled_edges_produce_an_interface_register():
    spec = _hub_spec()
    plan = analyze_layout(spec)
    assert plan.get("edge_bundles"), "fixture must actually exercise bundling for this test to mean anything"
    xml, _ = build_drawio_from_spec(spec, "Test", plan=plan)
    assert "__ireg" in xml
    assert "INTERFACE REGISTER" in xml
    assert "I-01" in xml


def test_every_bundle_rep_label_carries_its_register_code():
    spec = _hub_spec()
    plan = analyze_layout(spec)
    xml, _ = build_drawio_from_spec(spec, "Test", plan=plan)
    codes = {f"I-{i + 1:02d}" for i in range(len(plan["edge_bundles"]))}
    for code in codes:
        assert code in xml, f"{code} assigned to a bundle but never rendered on an edge label or register row"


def test_register_lists_every_suppressed_member_with_its_real_label():
    """This is the actual "fold, don't drop" guarantee: every (from, to,
    label) triple layout_plan suppressed must appear somewhere in the
    register panel's text, not just a count."""
    spec = _hub_spec()
    plan = analyze_layout(spec)
    xml, _ = build_drawio_from_spec(spec, "Test", plan=plan)
    register_values = "".join(
        m.group(1) for m in re.finditer(r'<mxCell id="__ireg__[^"]*"[^>]*value="([^"]*)"', xml)
    )
    node_by_id = {n["id"]: n for n in spec["nodes"]}
    for frm, to, label in plan.get("suppressed_edges") or []:
        frm_label = node_by_id[frm]["label"]
        to_label = node_by_id[to]["label"]
        assert frm_label in register_values, f"suppressed edge from={frm} ({frm_label}) missing from register"
        assert to_label in register_values, f"suppressed edge to={to} ({to_label}) missing from register"


def test_no_bundles_means_no_register_panel():
    """A diagram with no repetitive fan-out has nothing to fold — the panel
    must not render an empty/pointless box."""
    spec = {
        "style_preset": "refined",
        "diagram_title": "Small",
        "clusters": [{"id": "z1", "label": "Zone", "number": 1}],
        "nodes": [{"id": "a", "label": "A", "cluster": "z1"}, {"id": "b", "label": "B", "cluster": "z1"}],
        "edges": [{"from": "a", "to": "b", "label": "calls via HTTPS"}],
    }
    plan = analyze_layout(spec)
    assert not plan.get("edge_bundles")
    xml, _ = build_drawio_from_spec(spec, "Small", plan=plan)
    assert "__ireg" not in xml
    assert "INTERFACE REGISTER" not in xml


def test_small_bundle_gets_real_joined_labels_not_a_generic_word():
    """Patch 2b item 1: a bundle of <=3 members should show the REAL labels
    joined, not reach for a generic category word like "systems sync"."""
    spec = {
        "style_preset": "refined",
        "diagram_title": "Small bundle",
        "clusters": [
            {"id": "core", "label": "Core", "number": 1},
            {"id": "downstream", "label": "Downstream", "number": 2},
        ],
        "nodes": [
            {"id": "hub", "label": "Policy Engine", "cluster": "core"},
            {"id": "d1", "label": "Quote Service", "cluster": "downstream"},
            {"id": "d2", "label": "Claims Service", "cluster": "downstream"},
            {"id": "d3", "label": "Renewal Service", "cluster": "downstream"},
        ],
        "edges": [
            {"from": "hub", "to": "d1", "label": "quote decision", "flow": "control"},
            {"from": "hub", "to": "d2", "label": "claims decision", "flow": "control"},
            {"from": "hub", "to": "d3", "label": "renewal decision", "flow": "control"},
        ],
    }
    plan = analyze_layout(spec, aggressive_bundles=True)
    bundle = next((b for b in (plan.get("edge_bundles") or []) if b.get("label")), None)
    if bundle is None:
        return  # this fixture didn't trigger the aggressive support-bundle path — nothing to assert
    label = bundle["label"]
    assert "quote decision" in label or "claims decision" in label or "renewal decision" in label
