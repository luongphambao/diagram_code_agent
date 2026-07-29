from __future__ import annotations

import base64

import pytest

from prettygraph.native import svg_emit as se

_PAGE_HEAD = '<mxGraphModel dx="1" dy="1" pageWidth="800" pageHeight="600">'


def _wrap_xml(cells: str) -> str:
    return (
        '<mxfile><diagram name="d" id="d">'
        f"{_PAGE_HEAD}<root>"
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        f"{cells}"
        "</root></mxGraphModel></diagram></mxfile>"
    )


def test_page_size_from_mxgraphmodel():
    xml = _wrap_xml("")
    svg = se.to_svg(xml)
    assert 'width="800"' in svg
    assert 'height="600"' in svg
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")


def test_vertex_renders_rect_and_text():
    cells = (
        '<mxCell id="a" value="&lt;b&gt;Title&lt;/b&gt;&lt;br&gt;body line" '
        'style="rounded=1;arcSize=8;html=1;whiteSpace=wrap;fillColor=#FFFFFF;'
        'strokeColor=#D0D5DD;align=left;verticalAlign=top;fontColor=#101828;fontSize=10;" '
        'vertex="1" parent="1"><mxGeometry x="10" y="20" width="200" height="80" as="geometry"/></mxCell>'
    )
    svg = se.to_svg(_wrap_xml(cells))
    assert '<rect x="10.0" y="20.0" width="200.0" height="80.0"' in svg
    assert "Title" in svg
    assert "body line" in svg
    assert 'font-weight="bold"' in svg  # title is bold


def test_ellipse_shape():
    cells = (
        '<mxCell id="a" value="" style="ellipse;html=1;fillColor=#1D4ED8;strokeColor=#FFFFFF;" '
        'vertex="1" parent="1"><mxGeometry x="0" y="0" width="18" height="18" as="geometry"/></mxCell>'
    )
    svg = se.to_svg(_wrap_xml(cells))
    assert "<ellipse" in svg


def test_line_shape_for_legend_swatch():
    cells = (
        '<mxCell id="a" value="" style="line;html=1;strokeWidth=2;strokeColor=#1D4ED8;fillColor=none;" '
        'vertex="1" parent="1"><mxGeometry x="0" y="0" width="30" height="8" as="geometry"/></mxCell>'
    )
    svg = se.to_svg(_wrap_xml(cells))
    assert "<line " in svg


def test_unbaked_vendor_stencil_renders_neutral_placeholder_not_broken():
    cells = (
        '<mxCell id="a" value="" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.internet;" '
        'vertex="1" parent="1"><mxGeometry x="0" y="0" width="38" height="38" as="geometry"/></mxCell>'
    )
    svg = se.to_svg(_wrap_xml(cells))
    assert se._FALLBACK_GLYPH_FILL in svg


def test_baked_icon_data_uri_gets_base64_marker_restored():
    payload = base64.standard_b64encode(b"not a real png").decode("ascii")
    cells = (
        '<mxCell id="a" value="" '
        f'style="shape=image;html=1;aspect=fixed;image=data:image/png,{payload};" '
        'vertex="1" parent="1"><mxGeometry x="5" y="5" width="48" height="48" as="geometry"/></mxCell>'
    )
    svg = se.to_svg(_wrap_xml(cells))
    assert f"data:image/png;base64,{payload}" in svg
    assert "<image " in svg


@pytest.mark.parametrize(
    "uri, expected",
    [
        ("data:image/png,AAAA", "data:image/png;base64,AAAA"),
        ("data:image/svg+xml,AAAA", "data:image/svg+xml;base64,AAAA"),
        ("data:image/png;base64,AAAA", "data:image/png;base64,AAAA"),  # already correct, untouched
        ("not-a-data-uri", "not-a-data-uri"),
    ],
)
def test_fix_data_uri(uri, expected):
    assert se._fix_data_uri(uri) == expected


def test_edge_uses_waypoints_and_endpoint_anchors():
    cells = (
        '<mxCell id="a" value="" style="fillColor=#FFF;" vertex="1" parent="1">'
        '<mxGeometry x="0" y="0" width="40" height="40" as="geometry"/></mxCell>'
        '<mxCell id="b" value="" style="fillColor=#FFF;" vertex="1" parent="1">'
        '<mxGeometry x="200" y="0" width="40" height="40" as="geometry"/></mxCell>'
        '<mxCell id="e1" value="hop" style="strokeColor=#1D4ED8;exitX=1;exitY=0.5;entryX=0;entryY=0.5;" '
        'edge="1" parent="1" source="a" target="b">'
        '<mxGeometry relative="1" as="geometry"><Array as="points">'
        '<mxPoint x="120" y="20"/></Array></mxGeometry></mxCell>'
    )
    svg = se.to_svg(_wrap_xml(cells))
    assert "<path" in svg
    assert "M 40.0 20.0" in svg  # exitX=1,exitY=0.5 of a's 40x40 box -> (40,20)
    assert "L 120.0 20.0" in svg  # explicit waypoint
    assert "L 200.0 20.0" in svg  # entryX=0,entryY=0.5 of b's box at x=200 -> (200,20)
    assert "hop" in svg


def test_edge_with_dangling_endpoint_is_skipped_not_raised():
    cells = (
        '<mxCell id="e1" value="" style="" edge="1" parent="1" source="missing" target="also-missing">'
        '<mxGeometry relative="1" as="geometry"/></mxCell>'
    )
    svg = se.to_svg(_wrap_xml(cells))
    assert "<svg" in svg  # doesn't raise, just renders nothing for the edge


def test_zone_title_wraps_against_available_width_when_whitespace_wrap():
    # spacingLeft=52 clears an icon badge; the long title must reflow to a
    # second line inside the 200px box instead of overflowing past it.
    cells = (
        '<mxCell id="tab" value="&lt;b&gt;9 · A REALLY VERY LONG ZONE TITLE THAT MUST WRAP&lt;/b&gt;" '
        'style="rounded=1;html=1;whiteSpace=wrap;align=left;verticalAlign=top;spacing=10;'
        'fontColor=#101828;fontSize=10.5;spacingLeft=52;" vertex="1" parent="1">'
        '<mxGeometry x="0" y="0" width="200" height="56" as="geometry"/></mxCell>'
    )
    svg = se.to_svg(_wrap_xml(cells))
    tspans = svg.count("<tspan")
    assert tspans >= 2  # wrapped to more than one line


def test_double_escaped_ampersand_resolves_to_literal():
    cells = (
        '<mxCell id="a" value="&lt;b&gt;Observability &amp;amp; Security&lt;/b&gt;" '
        'style="html=1;whiteSpace=wrap;fontColor=#000;fontSize=10;" vertex="1" parent="1">'
        '<mxGeometry x="0" y="0" width="300" height="40" as="geometry"/></mxCell>'
    )
    svg = se.to_svg(_wrap_xml(cells))
    assert "Observability &amp; Security" in svg or "Observability & Security" in svg
    assert "&amp;amp;" not in svg


def test_text_only_cell_has_no_shape():
    cells = (
        '<mxCell id="a" value="ID" style="text;html=1;align=left;verticalAlign=middle;fontSize=8.5;" '
        'vertex="1" parent="1"><mxGeometry x="0" y="0" width="58" height="16" as="geometry"/></mxCell>'
    )
    svg = se.to_svg(_wrap_xml(cells))
    assert svg.count("<rect") == 1  # only the page background, no shape for the cell itself
    assert "ID" in svg


def test_multipage_only_renders_first_page():
    xml = (
        "<mxfile>"
        '<diagram name="p1" id="p1">'
        '<mxGraphModel pageWidth="100" pageHeight="100"><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="only_here" value="PageOne" style="html=1;" vertex="1" parent="1">'
        '<mxGeometry x="0" y="0" width="10" height="10" as="geometry"/></mxCell>'
        "</root></mxGraphModel></diagram>"
        '<diagram name="p2" id="p2">'
        '<mxGraphModel pageWidth="100" pageHeight="100"><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="only_page2" value="PageTwo" style="html=1;" vertex="1" parent="1">'
        '<mxGeometry x="0" y="0" width="10" height="10" as="geometry"/></mxCell>'
        "</root></mxGraphModel></diagram>"
        "</mxfile>"
    )
    svg = se.to_svg(xml)
    assert "PageOne" in svg
    assert "PageTwo" not in svg
