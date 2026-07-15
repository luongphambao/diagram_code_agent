"""Tests for the native declarative layout engine (prettygraph/native).

Pure geometry + catalog stencils — no Graphviz needed, fully deterministic.
"""

from __future__ import annotations

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


# --------------------------------------------------------------------------- #
# GCP production look (layered bands + card nodes + gcp.json image icons)
# --------------------------------------------------------------------------- #

_GCP_SPEC = {
    "provider": "gcp", "pattern": "architecture", "layout_intent": "layered",
    "diagram_title": "IoT Platform",
    "clusters": [
        {"id": "mgmt", "label": "Management & Security", "tier": "management"},
        {"id": "app", "label": "Dashboard & Application", "tier": "application", "number": 1},
        {"id": "data", "label": "Data & Storage", "tier": "data", "number": 2},
        {"id": "msg", "label": "Message Brokering", "tier": "messaging", "number": 3},
    ],
    "nodes": [
        {"id": "sm", "label": "Secret Manager", "tech": "Secret Manager", "cluster": "mgmt"},
        {"id": "cb", "label": "Cloud Build", "tech": "Cloud Build", "cluster": "mgmt"},
        {"id": "api", "label": "API", "tech": "Cloud Run", "cluster": "app"},
        {"id": "fs", "label": "State", "tech": "Cloud Firestore", "cluster": "data"},
        {"id": "bq", "label": "Warehouse", "tech": "BigQuery", "cluster": "data"},
        {"id": "ps", "label": "Telemetry", "tech": "Pub/Sub", "cluster": "msg"},
        {"id": "tasks", "label": "Dispatch", "tech": "Cloud Tasks", "cluster": "msg"},
    ],
    "edges": [
        {"from": "ps", "to": "fs", "flow": "data"},
        {"from": "api", "to": "fs", "flow": "serving"},
        {"from": "api", "to": "tasks", "flow": "control"},
        {"from": "sm", "to": "api", "flow": "security", "style": "dashed"},
    ],
}


def test_topology_gcp_layered_production_look():
    """GCP spec -> tinted layer bands, gcp.json image icons, card nodes, legend."""
    from prettygraph.native.topology import build_tree
    d, _ = build_tree(_GCP_SPEC)
    xml = d.mxfile("t")
    assert xml.count("image=data:image/") >= 6        # gcp_* image tiles resolved
    assert "resIcon=mxgraph.aws4." not in xml         # no AWS-branded icon leak
    # top-level layer bands carry a pale tint (never all-white frames)
    assert "light-dark(#eaf3ec" in xml or "light-dark(#fff3e9" in xml
    # cross-cutting sidebar gets the neutral grey band tint
    assert "light-dark(#eef1f5,#1b2430)" in xml
    # bold title + grey sub-label card composition (HTML label)
    assert "&lt;b&gt;" in xml
    # 4 distinct flow colours -> a legend block in the body
    assert 'value="LEGEND"' in xml


def test_topology_gcp_prefers_vendor_pack_over_generic():
    from prettygraph.native.topology import _resolve_node_icon, _load_catalog
    cat = _load_catalog()
    for tech, expected in (
        ("Cloud Run", "gcp_cloud_run"),
        ("BigQuery", "gcp_bigquery"),
        ("Cloud Firestore", "gcp_firestore"),
        ("Cloud Tasks", "gcp_cloud_tasks"),
    ):
        got = _resolve_node_icon(cat, {"tech": tech, "label": tech}, provider="gcp")
        assert got == expected, f"{tech}: expected {expected}, got {got}"


def test_topology_gcp_polish_gate_clean(tmp_path):
    """The native GCP output must pass its own production-polish gate."""
    from prettygraph.native.topology import build_drawio_from_spec
    from domain.validation import validate_drawio as vd
    xml, stats = build_drawio_from_spec(_GCP_SPEC, "t")
    p = tmp_path / "gcp.drawio"
    p.write_text(xml, encoding="utf-8")
    report = vd.validate_file(str(p))
    assert report["errors"] == []
    assert report.get("polish") == [], f"polish gate fired: {report.get('polish')}"
    assert stats["image_icons"] >= 6


def test_polish_audit_fires_on_untinted_frames_and_missing_legend():
    from domain.validation.validate_drawio import audit_production_polish
    frames = "".join(
        f'<mxCell id="f{i}" value="Layer {i}" vertex="1" parent="1" '
        f'style="rounded=0;fillColor=#FFFFFF;strokeColor=#999999;">'
        f'<mxGeometry x="{40 + i * 10}" y="{100 * i}" width="600" height="90" as="geometry"/></mxCell>'
        f'<mxCell id="n{i}" value="X" vertex="1" parent="f{i}" '
        f'style="rounded=0;fillColor=#FFFFFF;strokeColor=#999999;fontSize=11;">'
        f'<mxGeometry x="10" y="20" width="120" height="50" as="geometry"/></mxCell>'
        for i in range(3))
    edges = (
        '<mxCell id="e1" edge="1" parent="1" source="n0" target="n1" '
        'style="strokeColor=#2563EB;"><mxGeometry relative="1" as="geometry"/></mxCell>'
        '<mxCell id="e2" edge="1" parent="1" source="n1" target="n2" '
        'style="strokeColor=#E11D48;dashed=1;"><mxGeometry relative="1" as="geometry"/></mxCell>')
    xml = ('<mxGraphModel pageWidth="700" pageHeight="420"><root>'
           '<mxCell id="0"/><mxCell id="1" parent="0"/>'
           + frames + edges + "</root></mxGraphModel>")
    findings = audit_production_polish(xml)
    joined = " ".join(findings)
    assert "untinted" in joined
    assert "NO legend" in joined
