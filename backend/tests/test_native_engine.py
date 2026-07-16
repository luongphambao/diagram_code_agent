"""Tests for the native declarative layout engine (prettygraph/native).

Pure geometry + catalog stencils — no Graphviz needed, fully deterministic.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import domain.validation.validate_drawio as vd
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


_LONG_LABEL_SPEC = {
    "provider": "aws", "pattern": "microservices",
    "layout_intent": "left_to_right_pipeline", "slide_title": "AI Doc",
    "clusters": [{"id": "ai", "label": "AI Processing", "tier": "backend",
                  "parent": "", "accent": "violet", "number": 1}],
    "nodes": [
        # long label (no \n split — tech is a substring of label): must NOT use
        # the bare-icon convention (its label would overflow past the neighbor).
        {"id": "textract", "label": "Amazon Textract OCR and Layout Analysis Engine",
         "tech": "Amazon Textract", "cluster": "ai", "type": "service"},
        # short label: keeps the normal bare AWS icon convention.
        {"id": "bucket", "label": "Amazon S3", "tech": "Amazon S3",
         "cluster": "ai", "type": "storage"},
    ],
    "edges": [],
}


def test_long_label_falls_back_to_card_not_bare_icon():
    """A long, unwrappable label on a 'bare AWS icon' node would overflow past its
    reserved layout spacing and collide with the neighbor (the ZenWood sample's
    Textract/Bedrock overlap) — it must render as a card (wraps safely) instead."""
    from prettygraph.native.topology import build_tree
    d, _ = build_tree(_LONG_LABEL_SPEC)
    xml = d.mxfile("t")
    assert 'id="textract"' in xml
    textract_cell = re.search(r'<mxCell id="textract"[^>]*style="([^"]*)"', xml).group(1)
    assert "whiteSpace=wrap" in textract_cell       # card style, not bare icon
    assert "resIcon=mxgraph.aws4." not in textract_cell
    # the short-label sibling keeps the normal bare-icon convention
    bucket_cell = re.search(r'<mxCell id="bucket"[^>]*style="([^"]*)"', xml).group(1)
    assert "resIcon=mxgraph.aws4." in bucket_cell


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


# --------------------------------------------------------------------------- #
# topology zones (Workstream 1): real Cloud/VPC/Subnet/AZ nesting
# --------------------------------------------------------------------------- #

_ZONE_SPEC = {
    "provider": "aws", "pattern": "microservices",
    "layout_intent": "left_to_right_pipeline", "slide_title": "DeepStream",
    "clusters": [
        {"id": "cloud", "label": "AWS Cloud", "tier": "infra", "parent": "", "zone": "cloud"},
        {"id": "vpc", "label": "VPC", "tier": "infra", "parent": "cloud", "zone": "vpc"},
        {"id": "az1", "label": "us-east-1a", "tier": "infra", "parent": "vpc", "zone": "az"},
        {"id": "pub", "label": "Public subnet", "tier": "infra", "parent": "az1", "zone": "subnet_public"},
        {"id": "prv", "label": "Private subnet", "tier": "infra", "parent": "az1", "zone": "subnet_private"},
    ],
    "nodes": [
        {"id": "alb", "label": "ALB", "tech": "Elastic Load Balancing", "cluster": "pub", "type": "lb"},
        {"id": "ec2", "label": "DeepStream", "tech": "Amazon EC2", "cluster": "prv", "type": "service"},
        {"id": "rds", "label": "State", "tech": "Amazon RDS", "cluster": "prv", "type": "database"},
    ],
    "edges": [{"from": "alb", "to": "ec2", "flow": "data"},
              {"from": "ec2", "to": "rds", "flow": "data"}],
}


def test_aws_zones_use_group_stencils_and_nest(tmp_path):
    from prettygraph.native.topology import build_drawio_from_spec
    xml, stats = build_drawio_from_spec(_ZONE_SPEC, "DeepStream")
    # AWS zones render as real group stencils, incl. the (catalog-dashed) AZ frame.
    assert "grIcon=mxgraph.aws4.group_vpc" in xml
    assert "grIcon=mxgraph.aws4.group_availability_zone" in xml
    assert "grIcon=mxgraph.aws4.group_subnet" in xml
    assert "dashed=1" in xml                      # AZ boundary is dashed
    assert stats["edge_cross"] == 0 and stats["edge_overlaps"] == 0
    p = tmp_path / "zones.drawio"
    p.write_text(xml, encoding="utf-8")
    assert vd.validate_file(str(p))["error_count"] == 0


def test_non_aws_zone_draws_label_pill(tmp_path):
    from prettygraph.native.topology import build_drawio_from_spec
    spec = {**_ZONE_SPEC, "provider": "gcp"}
    xml, _ = build_drawio_from_spec(spec, "DeepStream")
    # Non-AWS zones have no group stencils -> tinted frame + top-left label pill.
    assert 'id="vpc__pill"' in xml
    assert 'id="az1__pill"' in xml
    assert "grIcon=mxgraph.aws4.group_vpc" not in xml   # no AWS stencils leak
    assert "dashed=1" in xml                             # AZ frame still dashed
    p = tmp_path / "gcp_zones.drawio"
    p.write_text(xml, encoding="utf-8")
    assert vd.validate_file(str(p))["error_count"] == 0


def test_zone_containment_is_concentric():
    from prettygraph.native.topology import build_tree
    d, _ = build_tree(_ZONE_SPEC)
    # cloud > vpc > az1 > (pub|prv) > nodes — real concentric nesting.
    assert _contains(d.R["cloud"], d.R["vpc"])
    assert _contains(d.R["vpc"], d.R["az1"])
    assert _contains(d.R["az1"], d.R["prv"])
    assert _contains(d.R["prv"], d.R["ec2"])


def test_empty_zone_is_backward_compatible():
    """zone == '' must be a pure no-op: identical output to a spec with no zone key."""
    import copy
    from prettygraph.native.topology import build_drawio_from_spec
    with_empty = copy.deepcopy(_AWS_SPEC)
    for c in with_empty["clusters"]:
        c["zone"] = ""
    a, _ = build_drawio_from_spec(_AWS_SPEC, "Shop")
    b, _ = build_drawio_from_spec(with_empty, "Shop")
    assert a == b


def test_native_slide_framing(tmp_path):
    """Slide mode wraps the flat native body in hero + legend chrome and validates clean."""
    from prettygraph.native.topology import build_drawio_from_spec
    from prettygraph.slide import compose_native_slide
    spec = {**_AWS_SPEC, "presentation_style": "slide"}
    xml, _ = build_drawio_from_spec(spec, "Shop", flat=True)
    out = tmp_path / "slide.drawio"
    compose_native_slide(xml, str(out), title="Shop", kicker="Kick", brand="ACME",
                         diagram_title="Arch", legend=[{"label": "Data Flow", "flow": "data"}],
                         include_hero=True)
    slide_xml = out.read_text(encoding="utf-8")
    assert "slide_hero" in slide_xml and "legend_box" in slide_xml
    assert "slide_title" in slide_xml
    assert vd.validate_file(str(out))["error_count"] == 0, vd.validate_file(str(out))["errors"]


def test_transform_drawio_body_scales_font_size_with_geometry():
    """A dense diagram gets scaled down to fit the slide panel (compose_native_slide);
    fontSize must shrink in lockstep with geometry or text overflows its (now smaller)
    box and collides with neighboring cells — the bug behind the CIMB sample's
    illegible overlapping text."""
    from prettygraph.slide import _transform_drawio_body
    xml = (
        '<mxfile><diagram><mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="a" value="Node" style="fontSize=13;fontStyle=1;" vertex="1" parent="1">'
        '<mxGeometry x="10" y="10" width="200" height="50"/></mxCell>'
        '</root></mxGraphModel></diagram></mxfile>'
    )
    out = _transform_drawio_body(xml, x=0, y=0, scale=0.5)
    assert "fontSize=13" not in out
    assert "fontSize=7" in out   # round(13 * 0.5) == 6 -> floored up to the 7 minimum
    assert 'width="100"' in out  # geometry still scales as before


def test_native_cornericon_logo_for_nonaws():
    """A non-AWS container gets a swappable corner logo (not an AWS group stencil)."""
    from prettygraph.native.topology import build_drawio_from_spec
    spec = {
        "provider": "onprem", "pattern": "pipeline",
        "layout_intent": "left_to_right_pipeline",
        "clusters": [{"id": "d", "label": "Vector Data Store", "tier": "data", "accent": "green"}],
        "nodes": [{"id": "q", "label": "Qdrant", "tech": "qdrant", "cluster": "d"}],
        "edges": [],
    }
    xml, _ = build_drawio_from_spec(spec, "x")
    assert "grIcon=mxgraph.aws4.group" not in xml           # no AWS group leak
    assert "mxgraph.aws4.generic_database" in xml           # corner logo on the data frame


def test_concept_icons_resolve():
    """AI/ML infra terms missing from the OSS packs now resolve to a real stencil."""
    from prettygraph.native.topology import _resolve_node_icon, _load_catalog
    cat = _load_catalog()
    for tech in ("gpu", "nvidia", "triton", "vlm", "faiss"):
        assert _resolve_node_icon(cat, {"tech": tech, "label": tech}) == tech


def _bands_spec(n: int, *, layout_intent: str = "") -> dict:
    """A synthetic spec with ``n`` independent top-level clusters (no cross-cut
    labels), one node each — enough to exercise the layer-band placement."""
    return {
        "provider": "aws", "pattern": "microservices", "layout_intent": layout_intent,
        "clusters": [{"id": f"c{i}", "label": f"Domain {i}", "tier": "app",
                      "parent": "", "accent": None, "number": i + 1} for i in range(n)],
        "nodes": [{"id": f"n{i}", "label": f"Node {i}", "tech": "AWS Lambda",
                   "cluster": f"c{i}", "type": "service"} for i in range(n)],
        "edges": [],
    }


def test_topology_stacks_single_column_regardless_of_band_count():
    """No explicit grid intent: always one vertical column, even with many bands.

    Grid-of-bands used to auto-trigger above a band-count threshold, but that
    regressed real diagrams — the router (built for one top-to-bottom channel)
    routes cross-band edges far messier once bands sit in a 2-D grid, and small
    bands get stretched to match the largest one in their row/column. Grid is
    now opt-in only (layout_intent="grid"), so any band count must stack."""
    from prettygraph.native.topology import build_tree
    for n in (3, 7):
        d, _ = build_tree(_bands_spec(n))
        ys = [d.R[f"c{i}"]["y"] for i in range(n)]
        xs = [d.R[f"c{i}"]["x"] for i in range(n)]
        assert ys == sorted(ys) and len(set(ys)) == n   # strictly stacked top-to-bottom
        assert max(xs) - min(xs) < 2                    # all in the same column


def test_topology_explicit_grid_intent_still_available():
    """layout_intent='grid' is still available as an explicit, deliberate opt-in."""
    from prettygraph.native.topology import build_tree
    d, _ = build_tree(_bands_spec(3, layout_intent="grid"))
    assert abs(d.R["c0"]["y"] - d.R["c1"]["y"]) < 2
    assert d.R["c1"]["x"] > d.R["c0"]["x"]
    assert d.R["c2"]["y"] > d.R["c0"]["y"]


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
