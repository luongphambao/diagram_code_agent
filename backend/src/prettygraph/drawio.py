"""draw.io export: dot_to_drawio, merge_drawios_vertical."""

from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path

from subprocess_utils import run_graphviz

from .constants import EDGE_COLOR, EDGE_FONTCOLOR

try:
    from ..drawio_catalog import (
        load_catalog as _load_catalog,
        style_for_icon as _style_for_icon,
        style_for_group as _style_for_group,
    )
except (ImportError, ValueError):
    try:
        from drawio_catalog import (  # type: ignore[no-redef]
            load_catalog as _load_catalog,
            style_for_icon as _style_for_icon,
            style_for_group as _style_for_group,
        )
    except ImportError:
        _load_catalog = None  # type: ignore[assignment]
        _style_for_icon = None  # type: ignore[assignment]
        _style_for_group = None  # type: ignore[assignment]


def _b64(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return "data:image/png," + base64.b64encode(Path(path).read_bytes()).decode()
    except OSError:
        return None


def dot_to_drawio(dot_path: str, sidecar_path: str, out_path: str) -> str:
    """Lay out the .dot with Graphviz and emit a styled, editable .drawio."""
    _cat = _load_catalog() if _load_catalog else None

    js = run_graphviz(["dot", "-Tjson", dot_path],
                      capture_output=True, text=True, check=True).stdout
    g = json.loads(js)
    side = json.loads(Path(sidecar_path).read_text(encoding="utf-8"))
    snodes, sclusters = side.get("nodes", {}), side.get("clusters", {})
    sz = side.get("style") or {}
    icon_px = int(sz.get("icon", 36)) - 2
    title_fs = int(sz.get("title", 13))
    edge_fs = int(sz.get("edge", 12))
    cluster_fs = max(int(sz.get("cluster", 15)) - 3, 11)

    x0, y0, x1, y1 = (float(v) for v in g["bb"].split(","))
    H = y1
    cells: list[str] = []
    gvid_to_cell: dict[int, str] = {}
    # Native AWS group frames only when the diagram is already AWS-stencil-native
    # (at least one node resolved a stencil), so a non-AWS diagram never gets an
    # aws4 container by accident.
    has_native = any(m.get("stencil_name") for m in snodes.values())

    for o in g.get("objects", []):
        name = o.get("name", "")
        if name.startswith("cluster"):
            if not o.get("bb"):
                continue
            # Graphviz names subgraphs "cluster_<id>"; strip the FULL prefix so the
            # sidecar lookup (keyed by <id>) matches. Stripping only "cluster" left a
            # leading "_", silently losing every cluster's label, colour and group_name.
            cid = name[len("cluster_"):] if name.startswith("cluster_") else name[len("cluster"):]
            meta = sclusters.get(cid, {})
            cx0, cy0, cx1, cy1 = (float(v) for v in o["bb"].split(","))
            gx, gy, gw, gh = cx0, H - cy1, cx1 - cx0, cy1 - cy0
            group_obj = (
                _style_for_group(_cat, meta["group_name"])
                if _cat and _style_for_group and has_native and meta.get("group_name")
                else None
            )
            if group_obj:
                style = group_obj["style"] + f"fontSize={cluster_fs};"
            else:
                style = (
                    f"rounded=1;arcSize=4;whiteSpace=wrap;html=1;"
                    f"fillColor={meta.get('fill', '#fafafa')};"
                    f"strokeColor={meta.get('stroke', '#cfcfcf')};verticalAlign=top;"
                    f"align=left;spacingLeft=10;spacingTop=6;fontSize={cluster_fs};fontStyle=1;"
                    "fontColor=#5a6270;"
                )
            cells.append(
                f'<mxCell id="c{o["_gvid"]}" value="{html.escape(meta.get("label", ""))}" '
                f'style="{style}" vertex="1" parent="1"><mxGeometry x="{gx:.0f}" '
                f'y="{gy:.0f}" width="{gw:.0f}" height="{gh:.0f}" as="geometry"/></mxCell>'
            )
            continue
        if not o.get("pos") or name not in snodes:
            continue
        meta = snodes[name]
        cx, cy = (float(v) for v in o["pos"].split(","))
        w = float(o.get("width", "1.4")) * 72.0
        h = float(o.get("height", "0.6")) * 72.0
        gx, gy = cx - w / 2.0, (H - cy) - h / 2.0
        cid = f"n{o['_gvid']}"
        gvid_to_cell[o["_gvid"]] = cid
        lbl = meta["label"] + (("\n" + meta["sublabel"]) if meta.get("sublabel") else "")
        shadow = ";shadow=1" if meta.get("shadow") else ""

        # Prefer native draw.io stencil when the catalog has an entry for this icon.
        stencil_name = meta.get("stencil_name")
        stencil_obj = (_style_for_icon(_cat, stencil_name) if _cat and stencil_name else None)
        if stencil_obj:
            sw = stencil_obj.get("width", 48)
            sh = stencil_obj.get("height", 48)
            gx_s = cx - sw / 2.0
            gy_s = (H - cy) - sh / 2.0
            cells.append(
                f'<mxCell id="{cid}" value="{html.escape(lbl)}" style="{stencil_obj["style"]}" '
                f'vertex="1" parent="1"><mxGeometry x="{gx_s:.0f}" y="{gy_s:.0f}" '
                f'width="{sw}" height="{sh}" as="geometry"/></mxCell>'
            )
        else:
            b64 = _b64(meta.get("icon"))
            if b64:
                style = (
                    f"shape=label;html=1;rounded=1;arcSize=12;whiteSpace=wrap;"
                    f"image={b64};imageAlign=left;imageVerticalAlign=middle;"
                    f"imageWidth={icon_px};imageHeight={icon_px};spacingLeft={icon_px + 10};align=left;"
                    f"fontSize={title_fs};fontStyle=1;fontColor=#222222;"
                    f"fillColor={meta['fill']};strokeColor={meta['stroke']}{shadow};"
                )
            else:
                style = (
                    f"rounded=1;whiteSpace=wrap;html=1;fontSize={title_fs};fontStyle=1;"
                    f"fontColor=#222222;fillColor={meta['fill']};"
                    f"strokeColor={meta['stroke']};"
                )
            cells.append(
                f'<mxCell id="{cid}" value="{html.escape(lbl)}" style="{style}" '
                f'vertex="1" parent="1"><mxGeometry x="{gx:.0f}" y="{gy:.0f}" '
                f'width="{max(w, 130):.0f}" height="{max(h, 52):.0f}" as="geometry"/></mxCell>'
            )

    for i, e in enumerate(g.get("edges", [])):
        src, tgt = gvid_to_cell.get(e.get("tail")), gvid_to_cell.get(e.get("head"))
        if not src or not tgt:
            continue
        if "invis" in str(e.get("style", "")):
            continue
        ecolor = e.get("color") or EDGE_COLOR
        ecolor = str(ecolor).split(":")[0].split(";")[0] or EDGE_COLOR
        edashed = "dashed" in str(e.get("style", ""))
        epen = e.get("penwidth")
        style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;"
            f"endFill=1;strokeColor={ecolor};fontSize={edge_fs};fontColor={EDGE_FONTCOLOR};"
            "labelBackgroundColor=#FFFFFF;"
            + ("dashed=1;dashPattern=6 6;" if edashed else "")
            + (f"strokeWidth={float(epen):.1f};" if epen else "")
        )
        cells.append(
            f'<mxCell id="e{i}" value="{html.escape(e.get("label") or "")}" '
            f'style="{style}" edge="1" parent="1" source="{src}" target="{tgt}">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
        )

    xml = (
        '<mxfile host="app.diagrams.net"><diagram name="architecture" id="d1">'
        '<mxGraphModel dx="1400" dy="900" grid="0" guides="1" tooltips="1" '
        'connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        f'pageWidth="{x1 - x0:.0f}" pageHeight="{y1 - y0:.0f}" math="0" shadow="0">'
        '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>"
    )
    Path(out_path).write_text(xml, encoding="utf-8")
    return xml


def _page_dims(xml: str) -> tuple[float, float]:
    m = re.search(r'pageWidth="([\d.]+)" pageHeight="([\d.]+)"', xml)
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)


def merge_drawios_vertical(xmls: list[str], out_path: str, gap: int = 26) -> str:
    """Merge .drawio XMLs into one, stacking each below the previous (centered)."""
    dims = [_page_dims(x) for x in xmls]
    maxw = max(w for w, _ in dims) if dims else 0.0
    total_h = sum(h for _, h in dims) + gap * (len(xmls) - 1)
    body: list[str] = []
    y = 0.0
    for i, (xml, (w, h)) in enumerate(zip(xmls, dims)):
        xoff = (maxw - w) / 2.0
        yoff = y
        m = re.search(r"<root>(.*)</root>", xml, re.S)
        inner = m.group(1) if m else ""
        inner = re.sub(r'<mxCell id="0"/>\s*<mxCell id="1" parent="0"/>', "", inner)
        for pfx in ('id="c', 'id="n', 'id="e',
                    'source="c', 'source="n', 'target="c', 'target="n'):
            inner = inner.replace(pfx, pfx.replace('="', f'="r{i}'))

        def _bump(mt: "re.Match[str]") -> str:
            return (f'<mxGeometry x="{float(mt.group(1)) + xoff:.0f}" '
                    f'y="{float(mt.group(2)) + yoff:.0f}"')

        inner = re.sub(r'<mxGeometry x="(-?[\d.]+)" y="(-?[\d.]+)"', _bump, inner)
        body.append(inner)
        y += h + gap
    xml_out = (
        '<mxfile host="app.diagrams.net"><diagram name="architecture" id="d1">'
        '<mxGraphModel dx="1400" dy="900" grid="0" guides="1" tooltips="1" '
        'connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        f'pageWidth="{maxw:.0f}" pageHeight="{total_h:.0f}" math="0" shadow="0">'
        '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        + "".join(body) + "</root></mxGraphModel></diagram></mxfile>"
    )
    Path(out_path).write_text(xml_out, encoding="utf-8")
    return xml_out
