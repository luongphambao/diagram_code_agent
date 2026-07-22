"""Convert a `diagrams`-generated Graphviz .dot into an editable draw.io file.

Graphviz computes the layout (positions, sizes, cluster boxes, edges); we emit
a .drawio (mxGraphModel) where every node becomes an image shape with the SAME
icon embedded as a base64 data URI, placed at the Graphviz-computed position.
Result: a draw.io file that is auto-laid-out AND fully editable, with real logos
— the strengths of both `diagrams` and next-ai-draw-io.

Runs anywhere `dot` is available (e.g. inside the Modal sandbox, where the icon
files referenced by the .dot live). Usage:
    python -m diagram_mcp.gv_to_drawio /workspace/out.dot /workspace/out.drawio
"""

from __future__ import annotations

import base64
import html
import json
import sys
from pathlib import Path

from subprocess_utils import run_graphviz


def _b64_image(path: str) -> str | None:
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return "data:image/png," + base64.b64encode(data).decode("ascii")


def _num(s: str) -> float:
    return float(s)


def convert(dot_path: str, out_path: str) -> str:
    """Lay out ``dot_path`` and write a .drawio to ``out_path``; return the XML."""
    js = run_graphviz(["dot", "-Tjson", dot_path], capture_output=True, text=True, check=True).stdout
    g = json.loads(js)

    # Canvas height for the Graphviz(bottom-up) -> draw.io(top-down) y flip.
    x0, y0, x1, y1 = (float(v) for v in g["bb"].split(","))
    H = y1

    cells: list[str] = []
    gvid_to_cell: dict[int, str] = {}

    # 1) Clusters first (drawn behind nodes; z-order follows document order).
    for o in g.get("objects", []):
        name = o.get("name", "")
        if not name.startswith("cluster"):
            continue
        if not o.get("bb"):
            continue
        cx0, cy0, cx1, cy1 = (float(v) for v in o["bb"].split(","))
        gx, gy, gw, gh = cx0, H - cy1, cx1 - cx0, cy1 - cy0
        label = html.escape(o.get("label") or "")
        cid = f"cluster{o['_gvid']}"
        style = (
            "rounded=1;arcSize=3;whiteSpace=wrap;html=1;fillColor=#F2F7FF;"
            "strokeColor=#9DB7D6;dashed=0;verticalAlign=top;align=left;"
            "spacingLeft=8;spacingTop=6;fontSize=12;fontStyle=1;fontColor=#5A6270;"
        )
        cells.append(
            f'<mxCell id="{cid}" value="{label}" style="{style}" vertex="1" '
            f'parent="1"><mxGeometry x="{gx:.0f}" y="{gy:.0f}" width="{gw:.0f}" '
            f'height="{gh:.0f}" as="geometry"/></mxCell>'
        )

    # 2) Nodes (image shapes with embedded logo, label below).
    for o in g.get("objects", []):
        if not o.get("pos"):
            continue
        cx, cy = (float(v) for v in o["pos"].split(","))
        w = _num(o.get("width", "1.0")) * 72.0
        h = _num(o.get("height", "1.0")) * 72.0
        # Use a square icon box (top of the reserved cell); label renders below.
        side = min(w, h, 64.0)
        gx = cx - side / 2.0
        gy = (H - cy) - h / 2.0
        label = html.escape(o.get("label") or "")
        cid = f"n{o['_gvid']}"
        gvid_to_cell[o["_gvid"]] = cid
        img = o.get("image")
        b64 = _b64_image(img) if img else None
        if b64:
            style = (
                f"shape=image;html=1;image={b64};verticalLabelPosition=bottom;"
                "verticalAlign=top;labelPosition=center;align=center;"
                "fontSize=11;fontColor=#222222;aspect=fixed;"
            )
            iw = ih = f"{side:.0f}"
        else:
            # Fallback: a labeled rounded box (still editable).
            style = "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#9AA4B2;fontSize=11;"
            iw, ih = f"{w:.0f}", f"{max(h - 24, 30):.0f}"
        cells.append(
            f'<mxCell id="{cid}" value="{label}" style="{style}" vertex="1" '
            f'parent="1"><mxGeometry x="{gx:.0f}" y="{gy:.0f}" width="{iw}" '
            f'height="{ih}" as="geometry"/></mxCell>'
        )

    # 3) Edges (let draw.io route orthogonally between cells; keep labels).
    for i, e in enumerate(g.get("edges", [])):
        src = gvid_to_cell.get(e.get("tail"))
        tgt = gvid_to_cell.get(e.get("head"))
        if not src or not tgt:
            continue
        label = html.escape(e.get("label") or "")
        style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;"
            "endFill=1;strokeColor=#5A6270;fontSize=10;fontColor=#444;"
            "labelBackgroundColor=#FFFFFF;"
        )
        cells.append(
            f'<mxCell id="e{i}" value="{label}" style="{style}" edge="1" '
            f'parent="1" source="{src}" target="{tgt}">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
        )

    xml = (
        '<mxfile host="app.diagrams.net"><diagram name="diagram" id="d1">'
        '<mxGraphModel dx="1400" dy="900" grid="0" gridSize="10" guides="1" '
        'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        f'pageWidth="{x1 - x0:.0f}" pageHeight="{y1 - y0:.0f}" math="0" shadow="0">'
        '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        + "".join(cells)
        + "</root></mxGraphModel></diagram></mxfile>"
    )
    Path(out_path).write_text(xml, encoding="utf-8")
    return xml


def main() -> None:
    dot_path = sys.argv[1] if len(sys.argv) > 1 else "/workspace/out.dot"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "/workspace/out.drawio"
    convert(dot_path, out_path)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
