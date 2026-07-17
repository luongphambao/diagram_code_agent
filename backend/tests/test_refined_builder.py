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


def test_refined_theme_tokens_json():
    j = RT.as_json()
    assert j["font"] == "Helvetica"
    assert j["zone_hues"]["blue"]["tab"] == "#2563EB"
    assert j["edge_classes"]["monitoring"]["dashed"] is True
    assert j["geometry"]["page_w"] == 1920
