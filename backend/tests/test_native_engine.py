"""Tests for the native declarative layout engine (prettygraph/native).

Pure geometry + catalog stencils — no Graphviz needed, fully deterministic.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import validate_drawio as vd
from prettygraph.native import Diagram, group, frame, grid, icon, box, render_tree
from prettygraph.native.layout_engine import subnet


def _contains(parent_r: dict, child_r: dict) -> bool:
    return (child_r["x"] >= parent_r["x"] - 1
            and child_r["y"] >= parent_r["y"] - 1
            and child_r["x"] + child_r["w"] <= parent_r["x"] + parent_r["w"] + 1
            and child_r["y"] + child_r["h"] <= parent_r["y"] + parent_r["h"] + 1)


def _multi_az() -> Diagram:
    d = Diagram("network")
    tree = group("region", "group_region", "AWS Region", {"dir": "row", "gap": 40}, [
        group("vpc", "group_vpc", "Production VPC", {"dir": "row", "gap": 30}, [
            group("az1", "group_availability_zone", "AZ-1", {"dir": "col"}, [
                subnet("pub1", "Public Subnet", [icon("alb1", "elastic_load_balancing", "ALB")]),
                subnet("prv1", "Private Subnet", [icon("ec2a", "ec2", "Web A"),
                                                  icon("rdsa", "rds", "DB A")]),
            ]),
            group("az2", "group_availability_zone", "AZ-2", {"dir": "col"}, [
                subnet("pub2", "Public Subnet", [icon("alb2", "elastic_load_balancing", "ALB")]),
                subnet("prv2", "Private Subnet", [icon("ec2b", "ec2", "Web B"),
                                                  icon("rdsb", "rds", "DB B")]),
            ]),
        ]),
    ])
    render_tree(d, tree)
    d.title("AWS Multi-AZ Web App")
    d.link("alb1", "ec2a", "HTTP")
    d.link("alb2", "ec2b", "HTTP")
    d.link("ec2a", "rdsa")
    d.link("ec2b", "rdsb")
    return d


def test_render_tree_nests_and_sizes():
    d = _multi_az()
    # every child rect sits inside its parent (containers hug their children)
    assert _contains(d.R["region"], d.R["vpc"])
    assert _contains(d.R["vpc"], d.R["az1"])
    assert _contains(d.R["az1"], d.R["prv1"])
    assert _contains(d.R["prv1"], d.R["ec2a"])
    # page auto-sized to the tree extent
    assert d.page[0] > d.R["region"]["w"]
    assert d.page[1] > d.R["region"]["h"]


def test_native_diagram_emits_ground_truth_stencils():
    d = _multi_az()
    xml = d.mxfile("t")
    assert xml.count("resIcon=mxgraph.aws4.") == 6   # 2 ALB + 2 EC2 + 2 RDS
    assert xml.count("grIcon=mxgraph.aws4.") == 8     # region + vpc + 2 az + 4 subnet
    assert "data:image/png" not in xml               # native, not base64


def test_native_diagram_validates_clean(tmp_path):
    d = _multi_az()
    p = tmp_path / "native.drawio"
    p.write_text(d.mxfile("t"), encoding="utf-8")
    rep = vd.validate_file(str(p))
    assert rep["ok"], rep["errors"]
    assert rep["error_count"] == 0


def test_layout_is_deterministic():
    a = _multi_az().mxfile("t")
    b = _multi_az().mxfile("t")
    assert a == b  # same declaration -> byte-identical output (no Graphviz jitter)


def test_equal_height_siblings_share_bottom_edge():
    # two column groups of different child counts in a row -> stretched to equal height
    d = Diagram("hierarchy")
    tree = group("root", None, "", {"dir": "row", "gap": 30}, [
        frame("left", "Left", {"dir": "col"}, [icon("a", "ec2", "A")]),
        frame("right", "Right", {"dir": "col"}, [icon("b", "ec2", "B"),
                                                 icon("c", "s3", "C"),
                                                 icon("d", "rds", "D")]),
    ])
    render_tree(d, tree)
    assert d.R["left"]["h"] == d.R["right"]["h"]


def test_box_auto_sizes_to_label():
    d = Diagram("pipeline")
    tree = group("root", None, "", {"dir": "col"}, [
        box("short", "Hi"),
        box("longer", "A considerably longer label than the short one"),
    ])
    render_tree(d, tree)
    assert d.R["longer"]["w"] >= d.R["short"]["w"]
    # width is clamped to the [120, 260] band
    assert 120 <= d.R["short"]["w"] <= 260
    assert 120 <= d.R["longer"]["w"] <= 260


def test_grid_lays_children_in_rows():
    d = Diagram("hierarchy")
    tree = grid("g", None, "Services", {"cols": 2}, [
        icon("a", "ec2", "A"), icon("b", "s3", "B"),
        icon("c", "rds", "C"), icon("d", "lambda", "D"),
    ])
    render_tree(d, tree)
    # 4 icons, 2 cols -> 2 rows: a,b on row 0; c,d on row 1 (c below a)
    assert abs(d.R["a"]["y"] - d.R["b"]["y"]) < 2
    assert d.R["c"]["y"] > d.R["a"]["y"]


def test_link_rejects_unknown_node():
    d = Diagram("pipeline")
    render_tree(d, group("root", None, "", {"dir": "col"}, [icon("a", "ec2", "A")]))
    try:
        d.link("a", "ghost")
        assert False, "expected ValueError for unknown node id"
    except ValueError as exc:
        assert "ghost" in str(exc)


# --------------------------------------------------------------------------- #
# auto-topology from render_spec
# --------------------------------------------------------------------------- #

_AWS_SPEC = {
    "provider": "aws", "pattern": "microservices",
    "layout_intent": "left_to_right_pipeline", "slide_title": "Shop",
    "clusters": [
        {"id": "edge", "label": "Edge", "tier": "frontend", "parent": "", "accent": "blue", "number": 1},
        {"id": "vpc", "label": "Application VPC", "tier": "backend", "parent": "", "accent": "violet", "number": 2},
        {"id": "svc", "label": "Services", "tier": "backend", "parent": "vpc", "accent": "violet", "number": None},
        {"id": "data", "label": "Data", "tier": "data", "parent": "", "accent": "green", "number": 3},
    ],
    "nodes": [
        {"id": "cf", "label": "CDN", "tech": "Amazon CloudFront", "cluster": "edge", "type": "cdn"},
        {"id": "api", "label": "API", "tech": "Amazon API Gateway", "cluster": "svc", "type": "gateway"},
        {"id": "orders", "label": "Orders", "tech": "AWS Lambda", "cluster": "svc", "type": "service"},
        {"id": "db", "label": "DB", "tech": "Amazon RDS", "cluster": "data", "type": "database"},
        {"id": "q", "label": "Queue", "tech": "Amazon SQS", "cluster": "data", "type": "queue"},
    ],
    "edges": [
        {"from": "cf", "to": "api", "flow": "data"},
        {"from": "api", "to": "orders", "flow": "data"},
        {"from": "orders", "to": "db", "flow": "data"},
        {"from": "orders", "to": "q", "flow": "control", "style": "dashed"},
    ],
}


def test_topology_resolves_all_aws_stencils():
    from prettygraph.native.topology import build_tree
    d, _ = build_tree(_AWS_SPEC)
    xml = d.mxfile("t")
    assert xml.count("resIcon=mxgraph.aws4.") == 5   # every node got a ground-truth stencil
    assert "grIcon=mxgraph.aws4.group_vpc" in xml     # "Application VPC" -> native group


def test_topology_nests_subcluster_and_validates(tmp_path):
    from prettygraph.native.topology import build_tree
    d, _ = build_tree(_AWS_SPEC)
    assert _contains(d.R["vpc"], d.R["svc"])          # svc nested inside its parent vpc
    assert _contains(d.R["svc"], d.R["api"])          # node inside its cluster
    p = tmp_path / "topo.drawio"
    p.write_text(d.mxfile("t"), encoding="utf-8")
    rep = vd.validate_file(str(p))
    assert rep["error_count"] == 0, rep["errors"]     # edges routed naively but no hard errors


def test_topology_is_deterministic():
    from prettygraph.native.topology import build_tree
    a, _ = build_tree(_AWS_SPEC)
    b, _ = build_tree(_AWS_SPEC)
    assert a.mxfile("t") == b.mxfile("t")


def test_router_avoids_icons_and_overlaps(tmp_path):
    from prettygraph.native.topology import build_tree
    # a fan-out (api -> 3 services) is the classic spaghetti case for a naive router
    d, _ = build_tree(_AWS_SPEC)
    xml = d.mxfile("t")
    assert d._cross == 0, "an edge cuts through an icon it does not connect to"
    assert d._overlaps == 0, "parallel edge runs overlap on the same track"
    p = tmp_path / "routed.drawio"
    p.write_text(xml, encoding="utf-8")
    advice = vd.validate_file(str(p))["advice"]
    assert not any("run THROUGH a node" in a for a in advice)
    assert not any("invisible leaf" in a for a in advice)


def test_router_bakes_waypoints():
    from prettygraph.native.topology import build_tree
    d, _ = build_tree(_AWS_SPEC)  # topology uses contract="bake"
    xml = d.mxfile("t")
    assert "<mxPoint" in xml            # obstacle-avoiding waypoints are frozen
    assert "exitX=" in xml and "entryX=" in xml  # de-collided port pins


def test_router_is_deterministic():
    from prettygraph.native.topology import build_tree
    a, _ = build_tree(_AWS_SPEC)
    b, _ = build_tree(_AWS_SPEC)
    assert a.mxfile("t") == b.mxfile("t")  # router has no RNG / order dependence


def test_build_drawio_from_spec_reports_stats(tmp_path):
    from prettygraph.native.topology import build_drawio_from_spec
    xml, stats = build_drawio_from_spec(_AWS_SPEC, "Shop")
    assert stats["native_icons"] == 5
    assert stats["native_groups"] >= 1
    assert stats["edge_cross"] == 0 and stats["edge_overlaps"] == 0
    assert stats["nodes"] == 5 and stats["edges"] == 4
    p = tmp_path / "spec.drawio"
    p.write_text(xml, encoding="utf-8")
    assert vd.validate_file(str(p))["error_count"] == 0


def test_export_drawio_native_tool_registered():
    import tools
    assert any(getattr(t, "name", "") == "export_drawio_native" for t in tools.DIAGRAM_TOOLS)


def test_topology_non_aws_falls_back_without_aws_group_leak():
    from prettygraph.native.topology import build_tree
    spec = {
        "provider": "gcp", "pattern": "monolith", "layout_intent": "top_down_stack",
        "clusters": [{"id": "net", "label": "VPC Network", "tier": "infra",
                      "parent": "", "accent": "blue", "number": None}],
        "nodes": [{"id": "x", "label": "Custom Widget", "tech": "In-House Thing",
                   "cluster": "net", "type": "service"}],
        "edges": [],
    }
    d, _ = build_tree(spec)
    xml = d.mxfile("t")
    # provider != aws -> the "VPC Network" label must NOT become an aws4 group
    assert "grIcon=mxgraph.aws4." not in xml
