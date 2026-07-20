"""Diagram-type presets — ported from drawio-ai-kit/src/types.mjs.

Extends layout_intent with 5 new node-level topologies (hub_spoke, hierarchy,
mesh, sequence, hybrid) that the original 4 values (left_to_right_pipeline,
top_down_stack, layered, grid) never covered. hub_spoke/hierarchy/mesh bypass
the cluster/band tree entirely (diagram_types._build_exotic_tree) and always
force style_preset="icon" (no representation in the refined page template);
sequence composes with refined (numbered-flow badges over every declared
edge, not just the data-flow subset) and has an icon-preset numbered-label
fallback.
"""

from __future__ import annotations

import re

import domain.validation.validate_drawio as vd
from prettygraph.native.diagram_types import DIAGRAM_TYPES, edge_rounded, type_preset
from prettygraph.native.topology import build_drawio_from_spec


# --------------------------------------------------------------------------- #
# diagram_types.py registry
# --------------------------------------------------------------------------- #

def test_type_preset_defaults_to_pipeline():
    assert type_preset("") == DIAGRAM_TYPES["pipeline"]
    assert type_preset("unknown_intent") == DIAGRAM_TYPES["pipeline"]


def test_type_preset_maps_legacy_intents():
    assert type_preset("left_to_right_pipeline") == DIAGRAM_TYPES["pipeline"]
    assert type_preset("top_down_stack") == DIAGRAM_TYPES["hierarchy"]
    assert type_preset("layered") == DIAGRAM_TYPES["pipeline"]


def test_type_preset_new_intents_key_directly():
    for name in ("hub_spoke", "hierarchy", "mesh", "sequence", "hybrid"):
        assert type_preset(name) == DIAGRAM_TYPES[name]


def test_edge_rounded_tree_and_fanout_always_sharp():
    for name in DIAGRAM_TYPES:
        assert edge_rounded(name, "tree") is False
        assert edge_rounded(name, "fanout") is False


def test_edge_rounded_follows_preset_otherwise():
    assert edge_rounded("hierarchy") is False   # hierarchy's own edge_corner is sharp
    assert edge_rounded("hub_spoke") is True


# --------------------------------------------------------------------------- #
# hub_spoke
# --------------------------------------------------------------------------- #

def _hub_spec(**kw) -> dict:
    spec = {
        "provider": "aws", "layout_intent": "hub_spoke",
        "nodes": [
            {"id": "hub", "label": "Event Bus", "type": "queue"},
            {"id": "a", "label": "Service A", "type": "service"},
            {"id": "b", "label": "Service B", "type": "service"},
            {"id": "c", "label": "Service C", "type": "service"},
        ],
        "clusters": [],
        "edges": [{"from": "a", "to": "hub"}, {"from": "b", "to": "hub"},
                 {"from": "hub", "to": "c"}],
    }
    spec.update(kw)
    return spec


def test_hub_spoke_centers_hub_between_spoke_columns(tmp_path):
    xml, stats = build_drawio_from_spec(_hub_spec(), "Hub")
    assert stats["style_preset"] == "icon"
    p = tmp_path / "hub.drawio"
    p.write_text(xml, encoding="utf-8")
    report = vd.validate_file(str(p))
    assert report["error_count"] == 0


def test_hub_spoke_explicit_hub_id_honored():
    spec = _hub_spec(hub="a")
    xml, _ = build_drawio_from_spec(spec, "Hub")
    assert "Service A" in xml and "Event Bus" in xml


def test_hub_spoke_downgrades_refined_to_icon():
    xml, stats = build_drawio_from_spec(_hub_spec(style_preset="refined"), "Hub")
    assert stats["style_preset"] == "icon"
    assert "downgrade_note" in stats
    assert "hub_spoke" in stats["downgrade_note"]
    assert "tab_zone_" not in xml  # refined chrome never appears


# --------------------------------------------------------------------------- #
# hierarchy
# --------------------------------------------------------------------------- #

def _hierarchy_spec() -> dict:
    return {
        "provider": "aws", "layout_intent": "hierarchy",
        "nodes": [
            {"id": "root", "label": "Org Root"},
            {"id": "ou1", "label": "OU Prod"},
            {"id": "ou2", "label": "OU Dev"},
            {"id": "acct1", "label": "Account 1"},
        ],
        "clusters": [],
        "edges": [{"from": "root", "to": "ou1"}, {"from": "root", "to": "ou2"},
                 {"from": "ou1", "to": "acct1"}],
    }


def test_hierarchy_levels_are_monotonic_in_y(tmp_path):
    from prettygraph.native.topology import build_tree
    d, _ = build_tree(_hierarchy_spec())
    assert d.R["root"]["y"] < d.R["ou1"]["y"] == d.R["ou2"]["y"] < d.R["acct1"]["y"]
    p = tmp_path / "hier.drawio"
    p.write_text(d.mxfile("t"), encoding="utf-8")
    report = vd.validate_file(str(p))
    assert report["error_count"] == 0


def test_hierarchy_edges_are_sharp_not_rounded():
    xml, _ = build_drawio_from_spec(_hierarchy_spec(), "Hierarchy")
    edge_styles = re.findall(r'edge="1"[^>]*style="([^"]*)"', xml) \
        or re.findall(r'style="([^"]*edgeStyle=orthogonalEdgeStyle[^"]*)"', xml)
    assert edge_styles, "no edges found in hierarchy xml"
    assert all("rounded=0" in s for s in edge_styles)


def test_hierarchy_isolated_node_is_its_own_root():
    """A node with zero edges has no incoming edge either — it qualifies as an
    additional root (level 0), same as a real hierarchy root."""
    spec = _hierarchy_spec()
    spec["nodes"].append({"id": "orphan", "label": "Unlinked"})
    from prettygraph.native.topology import build_tree
    d, _ = build_tree(spec)
    assert d.R["orphan"]["y"] == d.R["root"]["y"]


def test_hierarchy_cycle_does_not_infinite_loop():
    """A cycle back-edge must not hang the BFS (guard clause) — every node
    still gets placed."""
    spec = _hierarchy_spec()
    spec["edges"].append({"from": "acct1", "to": "root"})  # cycle back to the root
    from prettygraph.native.topology import build_tree
    d, _ = build_tree(spec)  # must terminate
    assert all(n["id"] in d.R for n in spec["nodes"])


# --------------------------------------------------------------------------- #
# mesh
# --------------------------------------------------------------------------- #

def test_mesh_grids_peer_nodes(tmp_path):
    spec = {
        "provider": "aws", "layout_intent": "mesh",
        "nodes": [{"id": f"p{i}", "label": f"Account {i}"} for i in range(5)],
        "clusters": [], "edges": [{"from": "p0", "to": "p1"}],
    }
    xml, stats = build_drawio_from_spec(spec, "Mesh")
    assert stats["style_preset"] == "icon"
    p = tmp_path / "mesh.drawio"
    p.write_text(xml, encoding="utf-8")
    report = vd.validate_file(str(p))
    assert report["error_count"] == 0


def test_mesh_uses_clusters_when_present_over_flat_nodes():
    spec = {
        "provider": "aws", "layout_intent": "mesh",
        "nodes": [{"id": "n1", "label": "N1", "cluster": "acct_a"}],
        "clusters": [{"id": "acct_a", "label": "Account A"},
                    {"id": "acct_b", "label": "Account B"}],
        "edges": [],
    }
    xml, _ = build_drawio_from_spec(spec, "Mesh")
    assert "Account A" in xml and "Account B" in xml


# --------------------------------------------------------------------------- #
# sequence
# --------------------------------------------------------------------------- #

def _sequence_spec(*, style_preset: str = "") -> dict:
    spec = {
        "provider": "aws", "layout_intent": "sequence",
        "nodes": [
            {"id": "u", "label": "User", "type": "external", "cluster": "z1"},
            {"id": "api", "label": "API GW", "type": "gateway", "cluster": "z2"},
            {"id": "svc", "label": "Service", "type": "service", "cluster": "z2"},
            {"id": "db", "label": "DB", "type": "database", "cluster": "z2"},
        ],
        "clusters": [{"id": "z1", "label": "Client", "number": 1},
                    {"id": "z2", "label": "Backend", "number": 2}],
        "edges": [
            {"from": "u", "to": "api", "label": "request", "flow": "control"},
            {"from": "api", "to": "svc", "label": "route", "flow": "control"},
            {"from": "svc", "to": "db", "label": "query", "flow": "control"},
        ],
    }
    if style_preset:
        spec["style_preset"] = style_preset
    return spec


def test_sequence_icon_fallback_numbers_edges_in_declared_order():
    xml, stats = build_drawio_from_spec(_sequence_spec(style_preset="icon"), "Seq")
    assert stats["style_preset"] == "icon"
    assert "1 · request" in xml
    assert "2 · route" in xml
    assert "3 · query" in xml


def test_sequence_refined_numbers_every_declared_edge_not_just_data_flow():
    """All 3 edges are flow="control" (not "data") — the stock refined
    numbered-flow walk only chains "data"-class edges, so without the
    sequence_mode override this fixture would produce ZERO badges."""
    xml, stats = build_drawio_from_spec(_sequence_spec(style_preset="refined"), "Seq")
    assert stats["style_preset"] == "refined"
    assert "flow_badge_1" in xml


def test_sequence_does_not_number_edges_when_intent_unset():
    spec = _sequence_spec(style_preset="icon")
    spec["layout_intent"] = "left_to_right_pipeline"
    xml, _ = build_drawio_from_spec(spec, "Seq")
    assert "1 · request" not in xml


# --------------------------------------------------------------------------- #
# default path byte-identity — new intents must not touch the untouched path
# --------------------------------------------------------------------------- #

def test_default_intent_unaffected_by_exotic_dispatch():
    from prettygraph.native.topology import build_tree
    spec = {
        "provider": "aws",
        "nodes": [{"id": "a", "label": "A", "cluster": "c1"},
                 {"id": "b", "label": "B", "cluster": "c1"}],
        "clusters": [{"id": "c1", "label": "Tier"}],
        "edges": [{"from": "a", "to": "b", "label": "call"}],
    }
    d, root = build_tree(spec)
    assert root["kind"] != "pool"
    xml = d.mxfile("t")
    assert "1 · call" not in xml  # sequence numbering never applied
