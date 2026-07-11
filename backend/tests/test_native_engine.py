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
