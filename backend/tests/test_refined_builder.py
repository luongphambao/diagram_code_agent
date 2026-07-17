"""Tests for the refined-preset builder emitters (Stage 1).

Pure style-string + geometry assertions on the new Diagram emitters
(pill / rich_card / note_card / tab_zone / boundary_rect / legend_band)
and the multi-page mxfile export.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from prettygraph.native import Diagram
from prettygraph.native import refined_theme as RT


def _d() -> Diagram:
    return Diagram("pipeline", page=(1920, 1080), flat=True)


def _cell_xml(d: Diagram, id: str) -> str:
    return d.cells[d._cell_index[id]]


def test_rich_card_style_and_body():
    d = _d()
    r = d.rich_card("redis", [100, 100], [145, 155], "ElastiCache for Redis",
                    ["cache.r6g.large", "Detection state & events"],
                    stroke="#C7B8EA")
    xml = _cell_xml(d, "redis")
    assert "arcSize=8" in xml
    assert "shadow=0" in xml
    assert "fontFamily=Helvetica" in xml
    assert "fontSize=10.5" in xml
    assert "align=left" in xml and "verticalAlign=top" in xml
    # bold heading + blank line + body lines (HTML escaped once by _put)
    assert "&lt;b&gt;ElastiCache for Redis&lt;/b&gt;" in xml
    assert "&lt;br&gt;&lt;br&gt;cache.r6g.large" in xml
    # no shadow companion cell, no accent stripe (flat anatomy)
    assert "redis__sh" not in d._cell_index
    assert "redis__ac" not in d._cell_index
    assert r["ob"] is True


def test_tab_zone_emits_tab_pill_at_overlap():
    d = _d()
    d.tab_zone("zone_state", [980, 225], [185, 385], "SHARED STATE", "purple",
               number=4)
    zone = d.R["zone_state"]
    tab = d.R["tab_zone_state"]
    assert tab["y"] == zone["y"] - RT.GEO["tab_overlap"]
    zx = _cell_xml(d, "zone_state")
    tx = _cell_xml(d, "tab_zone_state")
    tab_fill, stroke, tint = RT.ZONE_HUES["purple"]
    assert f"fillColor={tint}" in zx and f"strokeColor={stroke}" in zx
    assert "strokeWidth=1.3" in zx
    assert f"fillColor={tab_fill}" in tx
    assert "4 · SHARED STATE" in tx
    assert "arcSize=12" in tx


def test_boundary_rect_dashed_kinds():
    d = _d()
    d.boundary_rect("aws_cloud", [320, 145], [1210, 710], "cloud",
                    "AWS CLOUD · us-east-1")
    d.boundary_rect("vpc", [345, 195], [845, 455], "vpc", "VPC · MULTI-AZ")
    cloud = _cell_xml(d, "aws_cloud")
    vpc = _cell_xml(d, "vpc")
    assert "fillColor=#FCFCFD" in cloud and "dashed=1" not in cloud
    assert "dashed=1;dashPattern=7 5" in vpc and "fillColor=none" in vpc
    # both stay non-obstacle containers so edges can route across them
    assert d.R["aws_cloud"]["ob"] is False and d.R["vpc"]["ob"] is False
    assert "tab_aws_cloud" in d._cell_index and "tab_vpc" in d._cell_index


def test_note_card_centred_glue():
    d = _d()
    d.note_card("note_sec", [390, 555], [155, 40], "Security boundary",
                ["Only approved camera traffic reaches private compute."])
    xml = _cell_xml(d, "note_sec")
    assert "align=center" in xml and "verticalAlign=middle" in xml
    assert "fontSize=9.5" in xml
    assert d.R["note_sec"]["ob"] is True


def test_legend_band_swatches_and_obstacle():
    d = _d()
    entries = [("Request / data flow", "#2563EB", False),
               ("Monitoring / telemetry", "#C96A1B", True)]
    band = d.legend_band("footer", [40, 880], 1840, entries,
                         scope_note="Current target architecture.",
                         metadata="<b>Format:</b> Editable XML")
    assert band["ob"] is True  # router must treat the footer as an obstacle
    ln0 = _cell_xml(d, "footer__ln0")
    ln1 = _cell_xml(d, "footer__ln1")
    assert "strokeColor=#2563EB" in ln0 and "dashed" not in ln0
    assert "strokeColor=#C96A1B" in ln1 and "dashed=1" in ln1
    assert "footer__scope" in d._cell_index
    assert "footer__meta" in d._cell_index


def test_flat_mode_all_parent_one():
    d = _d()
    d.tab_zone("zone_a", [40, 170], [250, 410], "VIDEO SOURCES", "blue", number=1)
    d.rich_card("cam", [65, 225], [200, 150], "19+ IP Cameras", ["RTSP / RTMP"])
    d.pill("tag_external", [205, 184], [65, 22], "EXTERNAL",
           fill="#FFFFFF", stroke="#B8CDF7", font_color="#2563EB")
    for cid in ("zone_a", "tab_zone_a", "cam", "tag_external"):
        assert 'parent="1"' in _cell_xml(d, cid)


def test_mxfile_multi_page_roundtrip():
    d = _d()
    d.rich_card("a", [100, 100], [200, 100], "A", ["line"])
    original = ('<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
                '<mxCell id="x" value="old" vertex="1" parent="1">'
                '<mxGeometry x="1" y="1" width="10" height="10" as="geometry"/>'
                '</mxCell></root></mxGraphModel>')
    xml = d.mxfile("01 — Refined Architecture",
                   extra_pages=[("02 — Original Source", original)])
    root = ET.fromstring(xml)
    pages = root.findall("diagram")
    assert [p.get("name") for p in pages] == ["01 — Refined Architecture",
                                             "02 — Original Source"]
    assert root.get("compressed") == "false"
    # page 2 model preserved verbatim
    assert original in xml
    # page ids unique
    assert len({p.get("id") for p in pages}) == 2


def test_mxfile_single_page_unchanged():
    d = Diagram("pipeline")
    d.box("b", [10, 10], [50, 30], "B")
    xml = d.mxfile("Diagram")
    root = ET.fromstring(xml)
    assert len(root.findall("diagram")) == 1


def test_edge_semantic_id_via_router():
    d = _d()
    d.rich_card("src", [100, 100], [150, 80], "S")
    d.rich_card("tgt", [400, 100], [150, 80], "T")
    d.link("src", "tgt", "flow", id="e_src_tgt",
           stroke="#2563EB", style="strokeWidth=1.7;endArrow=block;endFill=1;")
    xml = d.to_xml()
    assert 'id="e_src_tgt"' in xml
    assert "strokeWidth=1.7" in xml and "endArrow=block" in xml


def _refined_spec() -> dict:
    return {
        "style_preset": "refined",
        "diagram_title": "DeepStream Detection Pipeline",
        "subtitle": "19+ IP cameras · Multi-AZ runtime",
        "backbone": ["Video Streams", "Secure Ingress", "GPU Inference",
                     "State & Storage", "Outcomes"],
        "metadata": {"format": "Editable XML"},
        "clusters": [
            {"id": "sources", "label": "Video Sources", "number": 1,
             "scope": "external"},
            {"id": "access", "label": "Access & Security", "number": 2,
             "parent": "aws"},
            {"id": "processing", "label": "GPU Processing", "number": 3,
             "parent": "aws"},
            {"id": "state", "label": "Shared State", "number": 4, "parent": "aws"},
            {"id": "operations", "label": "Operations & Governance", "number": 5,
             "role": "ops", "parent": "aws"},
            {"id": "outcomes", "label": "Consumption & Outcomes", "number": 6,
             "role": "outcome"},
            {"id": "aws", "label": "AWS Cloud · us-east-1", "zone": "cloud"},
        ],
        "nodes": [
            {"id": "cameras", "label": "19+ IP Cameras", "cluster": "sources",
             "body": ["RTSP / RTMP streams", "H.264 / H.265 video"]},
            {"id": "ingress", "label": "Stream Ingress", "cluster": "access",
             "body": ["RTSP allow-list", "NAT Gateway"]},
            {"id": "sg", "label": "Security Groups", "cluster": "access"},
            {"id": "worker1", "label": "DeepStream Worker 1",
             "cluster": "processing", "body": ["EC2 g4dn.2xlarge", "NVIDIA T4"]},
            {"id": "worker2", "label": "DeepStream Worker 2",
             "cluster": "processing", "body": ["EC2 g4dn.2xlarge", "NVIDIA T4"]},
            {"id": "redis", "label": "ElastiCache Redis", "cluster": "state",
             "body": ["cache.r6g.large", "Multi-AZ"]},
            {"id": "note_state", "label": "Runtime responsibility",
             "cluster": "state", "kind": "note",
             "body": ["Fast shared state; downstream handoff."]},
            {"id": "iam", "label": "IAM Role", "cluster": "operations",
             "body": ["Least privilege"]},
            {"id": "cloudwatch", "label": "CloudWatch", "cluster": "operations",
             "body": ["Logs · metrics · alarms"]},
            {"id": "dashboard", "label": "Detection Dashboard",
             "cluster": "outcomes", "body": ["Operator view"]},
        ],
        "edges": [
            {"from": "cameras", "to": "ingress", "label": "RTSP", "flow": "data"},
            {"from": "ingress", "to": "worker1", "flow": "serving"},
            {"from": "ingress", "to": "worker2", "flow": "serving"},
            {"from": "worker1", "to": "redis", "flow": "data"},
            {"from": "worker2", "to": "cloudwatch", "flow": "monitoring"},
            {"from": "iam", "to": "worker1", "flow": "security"},
            {"from": "redis", "to": "dashboard", "flow": "data"},
        ],
    }


def test_refined_composition_structure():
    from prettygraph.native.topology import build_drawio_from_spec
    xml, stats = build_drawio_from_spec(_refined_spec(), "Refined")
    assert stats["style_preset"] == "refined"
    root = ET.fromstring(xml)
    model = root.find(".//mxGraphModel")
    cells = {c.get("id"): c for c in model.iter("mxCell")}
    # zones + folder tabs for every content cluster
    for z in ("zone_sources", "zone_access", "zone_processing", "zone_state",
              "zone_operations", "zone_outcomes"):
        assert z in cells, f"missing {z}"
        assert f"tab_{z}" in cells, f"missing tab for {z}"
    # numbered tabs
    assert "1 · VIDEO SOURCES" in cells["tab_zone_sources"].get("value")
    # header stack + backbone + legend footer + background
    for cid in ("__title", "__subtitle", "backbone", "footer", "__bg"):
        assert cid in cells, f"missing {cid}"
    assert "VIDEO STREAMS" in cells["backbone"].get("value")
    # boundary rect over the aws children, visual only
    assert "bnd_aws" in cells and "tab_bnd_aws" in cells
    # scope pill on the external zone
    assert "tag_sources" in cells
    # glue note emitted as a note card
    assert "note_state" in cells
    # everything flat at parent="1"
    vertices = [c for c in cells.values() if c.get("vertex") == "1"]
    assert vertices and all(c.get("parent") == "1" for c in vertices)
    # semantic edge ids with the 5-class styling
    assert "e_cameras_ingress" in cells
    style = cells["e_cameras_ingress"].get("style")
    assert "strokeColor=#2563EB" in style and "strokeWidth=1.7" in style
    assert "endArrow=block" in style
    mon = cells["e_worker2_cloudwatch"].get("style")
    assert "strokeColor=#C96A1B" in mon and "dashed=1" in mon
    sec = cells["e_iam_worker1"].get("style")  # security -> control alias
    assert "strokeColor=#536174" in sec
    # ops band spans the main row bottom; outcomes zone sits right of main zones
    R = {c.get("id"): c.find("mxGeometry") for c in vertices}
    ops_g, out_g = R["zone_operations"], R["zone_outcomes"]
    state_g = R["zone_state"]
    assert float(ops_g.get("y")) > float(state_g.get("y"))
    assert float(out_g.get("x")) > float(state_g.get("x"))
    # no icons, no shadow cells in refined output
    assert "resIcon=mxgraph" not in xml
    assert "__sh" not in xml


def test_refined_grid_and_page():
    from prettygraph.native.topology import build_drawio_from_spec
    xml, _ = build_drawio_from_spec(_refined_spec(), "Refined")
    model = ET.fromstring(xml).find(".//mxGraphModel")
    assert model.get("grid") == "1"
    assert float(model.get("pageWidth")) >= 1400  # page hugs content, 1400 floor


_DIRTY_PAGE = (
    # deliberately awful page: overlapping cards, duplicate-ish geometry, a
    # dangling edge — must NOT leak into a multi-page report
    '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    '<mxCell id="o1" value="A" vertex="1" parent="1" style="rounded=1;">'
    '<mxGeometry x="10" y="10" width="120" height="60" as="geometry"/></mxCell>'
    '<mxCell id="o2" value="B" vertex="1" parent="1" style="rounded=1;">'
    '<mxGeometry x="20" y="20" width="120" height="60" as="geometry"/></mxCell>'
    '<mxCell id="bad" edge="1" parent="1" source="o1" target="ghost">'
    '<mxGeometry relative="1" as="geometry"/></mxCell>'
    '</root></mxGraphModel>')


def test_validator_scopes_to_first_page():
    import domain.validation.validate_drawio as vd
    from prettygraph.native.topology import build_drawio_from_spec
    d_xml, _ = build_drawio_from_spec(_refined_spec(), "Refined")
    # splice the dirty page in as page 2 (what the refined upgrade emits)
    two_page = d_xml.replace(
        "</mxfile>",
        f'<diagram name="02 — Original Source" id="d1">{_DIRTY_PAGE}</diagram></mxfile>')
    clean = vd.validate_xml(d_xml)
    multi = vd.validate_xml(two_page)
    # page-2 dangling edge / overlaps must not add errors or collisions
    assert multi["error_count"] == clean["error_count"]
    assert multi["collision_count"] == clean["collision_count"]
    assert any("preserved original" in w for w in multi["warnings"])


def test_semantic_preservation_page1_only():
    import domain.validation.validate_drawio as vd
    one = ('<mxfile><diagram name="p1"><mxGraphModel><root>'
           '<mxCell id="0"/><mxCell id="1" parent="0"/>'
           '<mxCell id="a" value="A" vertex="1" parent="1">'
           '<mxGeometry x="0" y="0" width="10" height="10" as="geometry"/></mxCell>'
           '</root></mxGraphModel></diagram>'
           f'<diagram name="p2" id="d1">{_DIRTY_PAGE}</diagram></mxfile>')
    # "o1" exists only on page 2 -> must count as missing
    errors, sem = vd.check_semantic_preservation(["a", "o1"], [], one)
    assert sem["node_recall"] == 0.5
    assert "o1" in sem["missing_nodes"]


def test_edit_preserves_second_page(tmp_path):
    from tools.rendering_tools import _load_drawio_model
    from prettygraph.native.topology import build_drawio_from_spec
    d_xml, _ = build_drawio_from_spec(_refined_spec(), "Refined")
    two_page = d_xml.replace(
        "</mxfile>",
        f'<diagram name="02 — Original Source" id="d1">{_DIRTY_PAGE}</diagram></mxfile>')
    f = tmp_path / "out.drawio"
    f.write_text(two_page, encoding="utf-8")
    tree, cell_root = _load_drawio_model(f)
    # mutate a page-1 cell, as edit_drawio does
    cell = next(c for c in cell_root.iter("mxCell") if c.get("id") == "cameras")
    cell.set("value", "edited")
    tree.write(str(f), encoding="unicode", xml_declaration=False)
    out = ET.parse(str(f)).getroot()
    pages = out.findall("diagram")
    assert len(pages) == 2
    # page 2 cells untouched
    p2_ids = {c.get("id") for c in pages[1].iter("mxCell")}
    assert {"o1", "o2", "bad"} <= p2_ids
    # page-1 edit landed
    p1_vals = {c.get("value") for c in pages[0].iter("mxCell")}
    assert "edited" in p1_vals


def test_refined_scorecard_pass_and_structure():
    import domain.validation.validate_drawio as vd
    from prettygraph.native.topology import build_drawio_from_spec
    spec = _refined_spec()
    xml, stats = build_drawio_from_spec(spec, "Refined")
    from prettygraph.native.repair import semantic_stats
    stats["semantic"] = semantic_stats(spec, xml, None)
    report = vd.validate_xml(xml, stats=stats)
    # zones must never register as colliding cards (flat layout)
    assert report["collision_count"] == 0, report["collisions"]
    m = report["layout_metrics"]
    assert m["refined"] is True
    assert m["backbone_present"] and m["zone_numbers_sequential"]
    assert m["glue_notes"] >= 1
    assert m["legend_present"] is True
    sc = vd.production_scorecard(report, stats)
    assert sc["style_preset"] == "refined"
    assert sc["target"] is vd.REFINED_TARGET
    assert sc["breakdown"]["iconography"] >= 8.0  # typographic structure score
    assert sc["node_recall"] == 1.0 and sc["edge_recall"] == 1.0
    assert sc["pass"], sc


def test_refined_scorecard_fails_without_backbone():
    import domain.validation.validate_drawio as vd
    from prettygraph.native.topology import build_drawio_from_spec
    spec = _refined_spec()
    xml, stats = build_drawio_from_spec(spec, "Refined")
    xml_nb = xml.replace('id="backbone"', 'id="stripped"')
    report = vd.validate_xml(xml_nb, stats=stats)
    sc = vd.production_scorecard(report, stats)
    full = vd.production_scorecard(vd.validate_xml(xml, stats=stats), stats)
    assert sc["breakdown"]["iconography"] <= full["breakdown"]["iconography"] - 3


def test_icon_mode_scorecard_unchanged():
    import domain.validation.validate_drawio as vd
    # no style_preset -> icon branch, PRODUCTION_TARGET, same shape as before
    report = {"errors": [], "warnings": [], "advice": [], "polish": [],
              "layout_metrics": {"ratio": 1.6, "icon_coverage": 0.95},
              "error_count": 0, "ok": True, "collision_count": 0}
    sc = vd.production_scorecard(report, {"edges": 4})
    assert sc["style_preset"] == "icon"
    assert sc["target"] is vd.PRODUCTION_TARGET
    assert sc["breakdown"]["iconography"] == 10.0


_SRC_DRAWIO = (
    '<mxfile><diagram name="src" id="s1"><mxGraphModel><root>'
    '<mxCell id="0"/><mxCell id="1" parent="0"/>'
    '<mxCell id="aws_shell" value="AWS Cloud" vertex="1" parent="1" style="rounded=0;">'
    '<mxGeometry x="0" y="0" width="900" height="500" as="geometry"/></mxCell>'
    '<mxCell id="tier_app" value="Application Tier" vertex="1" parent="aws_shell" style="rounded=0;">'
    '<mxGeometry x="20" y="40" width="400" height="300" as="geometry"/></mxCell>'
    '<mxCell id="api" value="API Gateway&lt;br&gt;Authentication, rate limiting, '
    'traffic routing and request transformation" vertex="1" parent="tier_app" style="rounded=1;">'
    '<mxGeometry x="30" y="60" width="160" height="80" as="geometry"/></mxCell>'
    '<mxCell id="svc" value="Core Service" vertex="1" parent="tier_app" style="rounded=1;">'
    '<mxGeometry x="30" y="180" width="160" height="60" as="geometry"/></mxCell>'
    '<mxCell id="e1" value="HTTPS" edge="1" parent="1" source="api" target="svc">'
    '<mxGeometry relative="1" as="geometry"/></mxCell>'
    '</root></mxGraphModel></diagram>'
    f'<diagram name="extra" id="s2">{_DIRTY_PAGE}</diagram></mxfile>')


def test_ingest_refined_spec(tmp_path):
    from domain.diagram.drawio_ingest import (extract_inventory,
                                              inventory_to_render_spec,
                                              first_page_model_xml)
    f = tmp_path / "src.drawio"
    f.write_text(_SRC_DRAWIO, encoding="utf-8")
    inv = extract_inventory(str(f))
    spec = inventory_to_render_spec(inv, style_preset="refined")
    assert spec["style_preset"] == "refined"
    api = next(n for n in spec["nodes"] if n["id"] == "api")
    # long subtitle became 2-3 short body lines, none over the char budget
    assert 2 <= len(api["body"]) <= 3
    assert all(len(l) <= 35 for l in api["body"])
    # source nesting surfaced: tier_app under aws_shell, aws_shell tagged cloud
    tier = next(c for c in spec["clusters"] if c["id"] == "tier_app")
    assert tier.get("parent") == "aws_shell"
    shell = next(c for c in spec["clusters"] if c["id"] == "aws_shell")
    assert shell.get("zone") == "cloud"
    # no underscore-private keys leak into the refined spec
    assert not any(k.startswith("_") for c in spec["clusters"] for k in c)
    # icon path stays flat: no parent/zone keys without the preset
    flat = inventory_to_render_spec(inv)
    assert "style_preset" not in flat
    assert all("parent" not in c and "zone" not in c for c in flat["clusters"])
    # first page serialization: page-1 cells only
    model = first_page_model_xml(str(f))
    assert 'id="api"' in model and 'id="o1"' not in model
    # and the refined build renders it end-to-end
    from prettygraph.native.topology import build_drawio_from_spec
    xml, stats = build_drawio_from_spec(spec, "Upgraded")
    assert stats["style_preset"] == "refined"
    assert 'id="api"' in xml and "tab_zone_tier_app" in xml


def test_e2e_refined_upgrade_deepstream():
    """Integration: refined upgrade of the real DeepStream 'before' file must
    produce a 2-page PASS-grade document (skips if the fixture is absent)."""
    import pytest
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2]
           / "deepstream_aws_architecture_improved(1).drawio")
    if not src.exists():
        pytest.skip("deepstream before-file not present")
    import domain.validation.validate_drawio as vd
    from domain.diagram.drawio_ingest import (extract_inventory,
                                              inventory_to_render_spec,
                                              first_page_model_xml)
    from prettygraph.native.topology import build_drawio_from_spec
    from prettygraph.native.repair import semantic_stats
    inv = extract_inventory(str(src))
    spec = inventory_to_render_spec(inv, style_preset="refined")
    xml, stats = build_drawio_from_spec(spec, "01 — Refined Architecture")
    stats["semantic"] = semantic_stats(spec, xml, None)
    xml = xml.replace("</mxfile>",
                      '<diagram name="02 — Original Source" id="dsrc">'
                      + first_page_model_xml(str(src)) + "</diagram></mxfile>")
    pages = ET.fromstring(xml).findall("diagram")
    assert len(pages) == 2
    report = vd.validate_xml(xml, stats=stats)
    sc = vd.production_scorecard(report, stats)
    assert sc["node_recall"] == 1.0 and sc["edge_recall"] == 1.0
    assert report["error_count"] == 0 and report["collision_count"] == 0
    m = report["layout_metrics"]
    assert m["backbone_present"] and m["zone_numbers_sequential"]
    assert sc["total"] >= 85 and sc["pass"], sc


def test_refined_subzone_span_and_subtint():
    """Pro authored features: AZ sub-frames inside a zone, header/footer span
    distributor cards, and per-card hue sub-tint (playbook §8.5 / §10.3)."""
    from prettygraph.native.topology import build_drawio_from_spec
    from prettygraph.native import refined_theme as RT
    spec = {
        "style_preset": "refined",
        "diagram_title": "T",
        "clusters": [
            {"id": "p", "label": "GPU Processing", "number": 1, "hue": "teal"},
            {"id": "q", "label": "State", "number": 2, "hue": "purple"},
        ],
        "nodes": [
            {"id": "router", "cluster": "p", "span": "header",
             "label": "Stream assignment", "body": ["Distribute feeds"]},
            {"id": "w1", "cluster": "p", "label": "Worker 1", "body": ["g4dn"],
             "subzone": {"id": "az1", "label": "us-east-1a · PRIVATE", "kind": "az"}},
            {"id": "ebs1", "cluster": "p", "label": "EBS gp3", "hue": "orange",
             "body": ["encrypted"],
             "subzone": {"id": "az1", "label": "us-east-1a · PRIVATE", "kind": "az"}},
            {"id": "w2", "cluster": "p", "label": "Worker 2", "body": ["g4dn"],
             "subzone": {"id": "az2", "label": "us-east-1b · PRIVATE", "kind": "az"}},
            {"id": "out", "cluster": "p", "span": "footer", "hue": "teal",
             "label": "Detection events"},
            {"id": "redis", "cluster": "q", "label": "Redis", "body": ["cache"]},
        ],
        "edges": [{"from": "router", "to": "w1", "flow": "execution"},
                  {"from": "w1", "to": "out", "flow": "execution"},
                  {"from": "out", "to": "redis", "flow": "data"}],
    }
    xml, _ = build_drawio_from_spec(spec, "T")
    root = ET.fromstring(xml)
    cells = {c.get("id"): c for c in root.iter("mxCell")}
    # AZ sub-frames rendered as dashed boundary rects with tab pills
    assert "bnd_p_az1" in cells and "bnd_p_az2" in cells
    assert "dashed=1" in cells["bnd_p_az1"].get("style")
    assert "tab_bnd_p_az1" in cells and "PRIVATE" in cells["tab_bnd_p_az1"].get("value")
    # per-card sub-tint: orange EBS card carries the orange tint, not zone teal
    orange_tint = RT.ZONE_HUES["orange"][2]
    assert f"fillColor={orange_tint}" in cells["ebs1"].get("style")
    # header/footer span cards are centre-aligned distributor cards
    assert "align=center" in cells["router"].get("style")
    assert "align=center" in cells["out"].get("style")
    # subzone cards sit inside the AZ frame geometry
    fr = cells["bnd_p_az1"].find("mxGeometry")
    w1g = cells["w1"].find("mxGeometry")
    assert float(w1g.get("x")) >= float(fr.get("x")) - 1
    assert float(w1g.get("x")) + float(w1g.get("width")) <= float(fr.get("x")) + float(fr.get("width")) + 1


def test_refined_card_logo_badge():
    """Refined component cards render a vendor logo as a top-right badge that the
    validator treats as decor (no false collision)."""
    from prettygraph.native.topology import build_drawio_from_spec
    import domain.validation.validate_drawio as vd
    uri = "data:image/png;base64,iVBORw0KGgoAAAANS=="
    spec = {
        "style_preset": "refined", "provider": "gcp", "diagram_title": "T",
        "clusters": [{"id": "z", "label": "Web", "number": 1, "hue": "blue"}],
        "nodes": [
            {"id": "dns", "cluster": "z", "label": "Cloud DNS", "body": ["Managed"],
             "icon_data_uri": uri},
            {"id": "lb", "cluster": "z", "label": "Load Balancer", "body": ["ALB"]},
        ],
        "edges": [{"from": "dns", "to": "lb", "flow": "data"}],
    }
    xml, _ = build_drawio_from_spec(spec, "T")
    cells = {c.get("id"): c for c in ET.fromstring(xml).iter("mxCell")}
    assert "dns__ic" in cells and "shape=image" in cells["dns__ic"].get("style")
    assert "spacingLeft=42" in cells["dns"].get("style")  # text clears the left logo
    # the logo badge must not register as a colliding card
    rep = vd.validate_xml(xml)
    assert rep["collision_count"] == 0


def test_refined_external_tier_is_sidebar():
    """An 'External …' tier is a sidebar dependency, not the ops band, even when
    its name also contains ops words like 'identity'."""
    from prettygraph.native.refined import _role_of
    assert _role_of({"label": "External Identity & Services"}) == "sidebar"
    assert _role_of({"label": "Third-Party APIs"}) == "sidebar"
    assert _role_of({"label": "Operations & Governance"}) == "ops"


def test_refined_access_zone_stays_main_inside_vpc():
    """A security/access zone nested in a VPC is main-plane (edge), NOT the ops
    band — the fix that keeps 'Access & Security' in the top row."""
    from prettygraph.native.refined import _role_of
    clusters = {
        "vpc": {"id": "vpc", "zone": "vpc"},
        "access": {"id": "access", "label": "Access & Security", "parent": "vpc"},
        "identity": {"id": "identity", "label": "Identity & Access"},
        "cw": {"id": "cw", "label": "Monitoring & Logging", "parent": "vpc"},
    }
    assert _role_of(clusters["access"], clusters) == "main"   # in-VPC edge zone
    assert _role_of(clusters["identity"], clusters) == "ops"  # top-level governance
    assert _role_of(clusters["cw"], clusters) == "ops"        # telemetry even in-VPC


def test_refined_theme_tokens_json():
    j = RT.as_json()
    assert j["font"] == "Helvetica"
    assert j["zone_hues"]["blue"]["tab"] == "#2563EB"
    assert j["edge_classes"]["monitoring"]["dashed"] is True
    assert j["geometry"]["page_w"] == 1920
