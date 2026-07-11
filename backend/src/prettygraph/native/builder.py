"""Diagram builder ported from drawio-ai-kit/src/builder.mjs.

Bundles the mxCell emit surface the layout engine calls (``_put``/``icon``/
``box``/``group``/``corner_icon``/``text``/``title``/``link``), a rect registry
(``self.R`` — the single source of truth the edge router reads), the ``.ob``
obstacle flag, and XML export. Edge routing lives in :mod:`router` (Phase 2.4);
until it lands, edges emit as plain orthogonal source→target connectors.
"""

from __future__ import annotations

from .theme import THEME

try:
    from ..drawio_catalog import (
        load_catalog as _load_catalog,
        style_for_icon as _style_for_icon,
        style_for_group as _style_for_group,
    )
except (ImportError, ValueError):  # pragma: no cover - import fallback
    from drawio_catalog import (  # type: ignore[no-redef]
        load_catalog as _load_catalog,
        style_for_icon as _style_for_icon,
        style_for_group as _style_for_group,
    )


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


class Diagram:
    """Declarative diagram builder — feed it via the layout engine's render_tree."""

    def __init__(self, type="pipeline", *, title="", page=(2000, 1200),
                 contract="scaffold"):
        if contract not in ("scaffold", "bake"):
            raise ValueError(f'Invalid contract "{contract}" — use "scaffold" or "bake".')
        self.c = _load_catalog()
        self.type = type
        self.contract = contract
        self.page = list(page)
        self.cells: list[str] = []
        self._cell_index: dict[str, int] = {}  # id -> position in self.cells
        self.R: dict[str, dict] = {}
        self.phantoms: set[str] = set()
        self.edge_specs: list[dict] = []
        self._edges_built = False
        if title:
            self.text("__title", [0, 24], page[0], title, fs=14)

    def _emit_cell(self, id, xml: str) -> None:
        """Append a cell, or replace in place if this id was already emitted —
        so re-emitting (e.g. title() after the page size is known) never yields a
        duplicate id."""
        ix = self._cell_index.get(id)
        if ix is None:
            self._cell_index[id] = len(self.cells)
            self.cells.append(xml)
        else:
            self.cells[ix] = xml

    # ---- primitive ---- #
    def _put(self, id, parent, x, y, w, h, style, label) -> dict:
        self.R[id] = {"x": x, "y": y, "w": w, "h": h}
        p = self.R.get(parent)
        ox, oy = (p["x"], p["y"]) if p else (0, 0)  # layer parents ("1") -> offset 0
        self._emit_cell(id,
            f'<mxCell id="{id}" value="{_esc(label)}" style="{style}" vertex="1" '
            f'parent="{parent}"><mxGeometry x="{x - ox:.0f}" y="{y - oy:.0f}" '
            f'width="{w:.0f}" height="{h:.0f}" as="geometry"/></mxCell>')
        return self.R[id]

    # ---- vertices ---- #
    def icon(self, id, name, xy, *, parent="1", label="") -> dict:
        s = _style_for_icon(self.c, name)
        if not s:
            raise ValueError(f'Icon not found in catalog: "{name}" — use search_icon.')
        r = self._put(id, parent, xy[0], xy[1], 48, 48, s["style"], label)
        r["ob"] = True  # leaf obstacle (router avoids)
        return r

    def corner_icon(self, id, name, xy, size=22, parent="1") -> dict:
        s = _style_for_icon(self.c, name)
        if not s:
            raise ValueError(f'cornerIcon not found in catalog: "{name}".')
        r = self._put(id, parent, xy[0], xy[1], size, size, s["style"], "")
        r["ob"] = False
        return r

    def box(self, id, xy, wh, label="", *, parent="1", fill="#FFFFFF",
            stroke="#5A6B7B", va="middle", bold=False, fs=11, round=False,
            ob=True) -> dict:
        fill = fill or "#FFFFFF"
        stroke = stroke or "#5A6B7B"
        style = (f"rounded={1 if round else 0};whiteSpace=wrap;html=1;fillColor={fill};"
                 f"strokeColor={stroke};fontColor=#1A1A1A;fontSize={fs};"
                 f"fontStyle={1 if bold else 0};verticalAlign={va};")
        r = self._put(id, parent, xy[0], xy[1], wh[0], wh[1], style, label)
        r["ob"] = ob
        return r

    def group(self, id, gname, xy, wh, label="", *, parent="1", fill=None,
              stroke=None) -> dict:
        s = _style_for_group(self.c, gname)
        if not s:
            raise ValueError(f'Group not found: "{gname}"')
        style = s["style"]
        # THEME always wins for group_subnet — never let a caller hardcode subnet fill.
        if gname == "group_subnet":
            priv = "private" in (label or "").lower()
            fill = THEME.subnet_private if priv else THEME.subnet_public
            stroke = stroke or (THEME.subnet_private_stroke if priv
                                else THEME.subnet_public_stroke)
        if not stroke and gname == "group_region":
            stroke = THEME.region_stroke
        if not stroke and gname == "group_vpc":
            stroke = THEME.vpc_stroke
        if not stroke and gname == "group_account":
            stroke = THEME.account_stroke
        if not stroke and gname == "group_availability_zone":
            stroke = THEME.az_stroke
        if fill:
            style += f"fillColor={fill};"
        if stroke:
            style += f"strokeColor={stroke};"
        r = self._put(id, parent, xy[0], xy[1], wh[0], wh[1], style, label)
        r["ob"] = False  # container -> edges pass through
        return r

    def cluster_box(self, id, child_ids, label="", *, icon=None, stroke="#ED7100",
                    dashed=True, pad=14, pad_top=34, icon_size=20, stroke_width=1,
                    font_color=None) -> dict | None:
        rs = [self.R[c] for c in child_ids if c in self.R]
        if not rs:
            return None
        x = min(r["x"] for r in rs) - pad
        y = min(r["y"] for r in rs) - pad_top
        w = max(r["x"] + r["w"] for r in rs) + pad - x
        h = max(r["y"] + r["h"] for r in rs) + pad - y
        fc = font_color or stroke
        spacing_left = icon_size + 6 if icon else 6
        dash = "dashed=1;" if dashed else ""
        self._put(id, "boundaries", x, y, w, h,
                  f"rounded=0;{dash}fillColor=none;strokeColor={stroke};"
                  f"strokeWidth={stroke_width};verticalAlign=top;align=left;"
                  f"spacingLeft={spacing_left};spacingTop=5;fontColor={fc};"
                  "fontStyle=1;fontSize=11;", label)
        if icon:
            s = _style_for_icon(self.c, icon)
            if not s:
                raise ValueError(f'clusterBox icon not found: "{icon}"')
            self._put(f"{id}_icon", "boundaries", x + 1, y + 1, icon_size, icon_size,
                      s["style"], "")
        return self.R[id]

    def text(self, id, xy, w, label, *, fs=14, parent="1") -> None:
        p = self.R.get(parent)
        ox, oy = (0, 0) if parent == "1" or not p else (p["x"], p["y"])
        self.R[id] = {"x": xy[0], "y": xy[1], "w": w, "h": 30}
        self._emit_cell(id,
            f'<mxCell id="{id}" value="{_esc(label)}" style="text;html=1;align=center;'
            f'fontStyle=1;fontSize={fs};fontColor=light-dark(#232F3E,#E8E8E8);" '
            f'vertex="1" parent="{parent}"><mxGeometry x="{xy[0] - ox:.0f}" '
            f'y="{xy[1] - oy:.0f}" width="{w:.0f}" height="30" as="geometry"/></mxCell>')

    def title(self, label, *, fs=14) -> "Diagram":
        self.text("__title", [0, 24], self.page[0], label, fs=fs)
        return self

    def span_v(self, id, spec, at) -> dict:
        icon = spec.get("icon")
        label = spec.get("label", "")
        w = spec["w"]
        pad = spec.get("pad", 16)
        fill = spec.get("fill", "#FFFFFF")
        stroke = spec.get("stroke", "#5A6B7B")
        F = self.R[at["from"]]
        T = self.R.get(at.get("to")) or F
        if at.get("lane"):
            lane = self.R[at["lane"]]
            x = round(lane["x"] + (lane["w"] - w) / 2)
        else:
            a, b = self.R[at["between"][0]], self.R[at["between"][1]]
            x = round((a["x"] + a["w"] + b["x"]) / 2 - w / 2)
        y = round(F["y"] - pad)
        h = round(T["y"] + T["h"] - F["y"] + pad * 2)
        self.box(id, [x, y], [w, h], label, fill=fill, stroke=stroke, va="bottom", fs=10)
        if icon:
            self.icon(f"{id}_ic", icon, [round(x + (w - 48) / 2), y + 12])
        return self.R[id]

    # ---- edges ---- #
    def link(self, src, tgt, label="", **opts) -> "Diagram":
        for node in (src, tgt):
            if node not in self.R and node not in self.phantoms:
                raise ValueError(
                    f'link(): unknown node id "{node}" — not built and not a phantom.')
        self.edge_specs.append({"src": src, "tgt": tgt, "label": label, "opts": opts})
        return self

    def _build_edges(self) -> None:
        """Emit edges. Phase 2.2 placeholder: plain orthogonal source→target
        connectors (draw.io auto-routes). Phase 2.4 replaces this with the
        A*/nudge obstacle-avoiding router."""
        if self._edges_built:
            return
        self._edges_built = True
        for i, e in enumerate(self.edge_specs):
            if e["src"] not in self.R or e["tgt"] not in self.R:
                continue  # skip phantom-only endpoints (no rect to anchor)
            opts = e["opts"]
            color = opts.get("color") or THEME.edge_stroke
            dashed = "dashed=1;dashPattern=6 6;" if opts.get("style") == "dashed" else ""
            style = (
                "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;"
                f"strokeColor={color};strokeWidth={THEME.edge_stroke_width};"
                f"fontColor={THEME.edge_font_color};labelBackgroundColor={THEME.edge_label_bg};"
                + dashed)
            self.cells.append(
                f'<mxCell id="e{i}" value="{_esc(e["label"])}" style="{style}" edge="1" '
                f'parent="1" source="{e["src"]}" target="{e["tgt"]}">'
                '<mxGeometry relative="1" as="geometry"/></mxCell>')

    # ---- export ---- #
    def to_xml(self) -> str:
        self._build_edges()
        cells_xml = "".join(self.cells)
        bounds_layer = (
            '<mxCell id="boundaries" value="Stack boundaries (locked)" parent="0" '
            'style="locked=1;"/>' if 'parent="boundaries"' in cells_xml else "")
        return (
            '<mxGraphModel dx="1400" dy="900" grid="0" gridSize="10" guides="1" '
            'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
            f'pageWidth="{self.page[0]:.0f}" pageHeight="{self.page[1]:.0f}" math="0" '
            'shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
            f'{bounds_layer}{cells_xml}</root></mxGraphModel>')

    def mxfile(self, name="Diagram") -> str:
        return (f'<mxfile host="app.diagrams.net"><diagram name="{_esc(name)}" id="d">'
                f'{self.to_xml()}</diagram></mxfile>')
