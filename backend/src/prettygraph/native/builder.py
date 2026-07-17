"""Diagram builder ported from drawio-ai-kit/src/builder.mjs.

Bundles the mxCell emit surface the layout engine calls (``_put``/``icon``/
``box``/``group``/``corner_icon``/``text``/``title``/``link``), a rect registry
(``self.R`` — the single source of truth the edge router reads), the ``.ob``
obstacle flag, and XML export. Edge routing lives in :mod:`router` (Phase 2.4);
until it lands, edges emit as plain orthogonal source→target connectors.
"""

from __future__ import annotations

from .theme import THEME
from . import refined_theme as RT

try:
    from ..drawio_catalog import (
        load_catalog as _load_catalog,
        style_for_icon as _style_for_icon,
        style_for_group as _style_for_group,
    )
except (ImportError, ValueError):  # pragma: no cover - import fallback
    from domain.diagram.drawio_catalog import (  # type: ignore[no-redef]
        load_catalog as _load_catalog,
        style_for_icon as _style_for_icon,
        style_for_group as _style_for_group,
    )


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# z-order buckets (V2 §7.2 "edge phải nằm dưới card"): lower renders first
# (further back). Cells are stable-sorted by these in to_xml(), so connectors
# always sit ABOVE layer backgrounds but BELOW card shadows/bodies — a stray
# router crossing can never slice through a card title or icon.
Z_CONTAINER = 0   # frames, tinted layer bands, groups, swimlane structure
Z_EDGE = 10       # connectors
Z_SHADOW = 20     # card drop-shadow cells
Z_NODE = 30       # card / box / standalone-icon bodies
Z_FORE = 40       # card sub-icons, accent bars, corner logos
Z_CHROME = 50     # title, legend, free text


class Diagram:
    """Declarative diagram builder — feed it via the layout engine's render_tree."""

    def __init__(self, type="pipeline", *, title="", page=(2000, 1200),
                 contract="scaffold", flat=False):
        if contract not in ("scaffold", "bake"):
            raise ValueError(f'Invalid contract "{contract}" — use "scaffold" or "bake".')
        self.c = _load_catalog()
        self.type = type
        self.contract = contract
        # flat=True emits every vertex at parent="1" with ABSOLUTE geometry (no
        # container nesting) — needed when the body is embedded into a slide, whose
        # _transform_drawio_body assumes a flat body. self.R stays absolute either
        # way, so the router is unaffected.
        self.flat = flat
        self.grid = False  # refined preset turns the 10px grid on (playbook §9.2)
        self.page = list(page)
        self.cells: list[str] = []
        self._cell_z: list[int] = []  # z-bucket per cell, aligned with self.cells
        self._cell_index: dict[str, int] = {}  # id -> position in self.cells
        self.R: dict[str, dict] = {}
        self.phantoms: set[str] = set()
        self.edge_specs: list[dict] = []
        self.eid = 0
        self._cross = 0
        self._overlaps = 0
        self._edges_built = False
        if title:
            self.text("__title", [0, 24], page[0], title, fs=14)

    def _emit_cell(self, id, xml: str, z: int = Z_NODE) -> None:
        """Append a cell, or replace in place if this id was already emitted —
        so re-emitting (e.g. title() after the page size is known) never yields a
        duplicate id. ``z`` is the render bucket used by to_xml()'s stable sort."""
        ix = self._cell_index.get(id)
        if ix is None:
            self._cell_index[id] = len(self.cells)
            self.cells.append(xml)
            self._cell_z.append(z)
        else:
            self.cells[ix] = xml
            self._cell_z[ix] = z

    # ---- primitive ---- #
    def _put(self, id, parent, x, y, w, h, style, label, *, z: int = Z_NODE) -> dict:
        self.R[id] = {"x": x, "y": y, "w": w, "h": h}
        if self.flat:
            eff_parent, ox, oy = "1", 0, 0  # flat: all cells at root, absolute coords
        else:
            eff_parent = parent
            p = self.R.get(parent)
            ox, oy = (p["x"], p["y"]) if p else (0, 0)  # layer parents ("1") -> offset 0
        self._emit_cell(id,
            f'<mxCell id="{id}" value="{_esc(label)}" style="{style}" vertex="1" '
            f'parent="{eff_parent}"><mxGeometry x="{x - ox:.0f}" y="{y - oy:.0f}" '
            f'width="{w:.0f}" height="{h:.0f}" as="geometry"/></mxCell>', z)
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
        r = self._put(id, parent, xy[0], xy[1], size, size, s["style"], "", z=Z_FORE)
        r["ob"] = False
        return r

    def box(self, id, xy, wh, label="", *, parent="1", fill="#FFFFFF",
            stroke="#5A6B7B", va="middle", bold=False, fs=11, round=False,
            ob=True, z=Z_NODE, align=None) -> dict:
        fill = fill or "#FFFFFF"
        stroke = stroke or "#5A6B7B"
        style = (f"rounded={1 if round else 0};whiteSpace=wrap;html=1;fillColor={fill};"
                 f"strokeColor={stroke};fontColor=#1A1A1A;fontSize={fs};"
                 f"fontStyle={1 if bold else 0};verticalAlign={va};")
        # Optional horizontal alignment (band/frame titles read top-LEFT like the
        # production reference, away from centred cards). None = draw.io default (centre).
        if align:
            style += f"align={align};" + ("spacingLeft=12;" if align == "left" else "")
        r = self._put(id, parent, xy[0], xy[1], wh[0], wh[1], style, label, z=z)
        r["ob"] = ob
        return r

    def card(self, id, xy, wh, icon_name=None, title="", sub="", *, parent="1",
             fill=None, stroke=None, accent=None, image_data_uri=None) -> dict:
        """Rounded card node: catalog icon on the LEFT, bold title + grey sub-label.

        Production anatomy (V2 §6.3): a controlled drop-shadow cell behind the
        card + an optional accent stripe on top carrying the layer identity.

        ``image_data_uri`` (V2 §8, upgrade path): render the left icon from an
        embedded data: URI reused from the source .drawio instead of a catalog
        stencil — no catalog lookup, no network.

        The value is HTML (html=1): the inner text is escaped here, the whole
        value again by _put for the XML attribute — draw.io decodes the XML
        layer, then renders the remaining tags/entities as HTML.
        """
        ic = 30
        has_icon = bool(icon_name or image_data_uri)
        x, y, w, h = xy[0], xy[1], wh[0], wh[1]
        # Drop-shadow: a separate offset cell rather than draw.io's shadow=1
        # (which renders heavily and inconsistently). Low opacity, no stroke,
        # behind everything (Z_SHADOW). Not a router obstacle.
        sh = self._put(f"{id}__sh", parent, round(x + 3), round(y + 4), w, h,
                       "rounded=1;arcSize=12;whiteSpace=wrap;html=1;fillColor=#1F2A37;"
                       "opacity=12;strokeColor=none;", "", z=Z_SHADOW)
        sh["ob"] = False
        label = f"<b>{_esc(title)}</b>"
        if sub:
            label += (f'<br><font style="font-size: 10px" color="#647687">'
                      f"{_esc(sub)}</font>")
        # An edge arriving from due-left/right enters at the card's mid-height
        # port — near enough to the (vertically-centred) text block that a bare
        # 12px inset lets the arrowhead visually clip the first few characters of
        # the subtitle line. 20px gives real clearance without an icon to reserve
        # the space instead.
        pad_l = ic + 20 if has_icon else 28
        style = (f"rounded=1;arcSize=12;whiteSpace=wrap;html=1;"
                 f"fillColor={fill or THEME.base};strokeColor={stroke or '#AEB9C4'};"
                 f"fontColor={THEME.font_color};fontSize=12;align=left;"
                 f"spacingLeft={pad_l};spacingRight=10;verticalAlign=middle;")
        r = self._put(id, parent, x, y, w, h, style, label, z=Z_NODE)
        r["ob"] = True  # leaf obstacle (router avoids)
        if accent:
            # Thin accent bar across the card top, inset so it clears the rounded
            # corners; carries the layer's identity colour onto the card.
            ac = self._put(f"{id}__ac", parent, round(x + 8), round(y + 3),
                           max(10, w - 16), 4,
                           f"rounded=1;arcSize=60;html=1;fillColor={accent};"
                           "strokeColor=none;", "", z=Z_FORE)
            ac["ob"] = False
        if has_icon:
            if image_data_uri:
                # mxCell style strings split on ";" for key=value pairs, so a
                # standard "data:image/png;base64,..." URI truncates at the
                # first ";" (image ends up as bare "data:image/png", the
                # actual payload dangling as an unparsed fragment) and the
                # icon silently renders as a broken-image glyph. draw.io's
                # own image-embed convention sidesteps this by dropping the
                # ";base64" marker entirely — "data:image/png,<data>" with a
                # bare comma — which mxGraph's image loader still decodes as
                # base64. Normalize here so every caller (icon_data_uri from
                # upgrade_drawio ingestion, or a fresh base64 encode) is safe
                # regardless of which form it was built with.
                safe_uri = image_data_uri.replace(";base64,", ",", 1)
                icon_style = f"shape=image;html=1;imageAspect=1;aspect=fixed;image={safe_uri};"
            else:
                s = _style_for_icon(self.c, icon_name)
                if not s:
                    raise ValueError(f'card icon not found in catalog: "{icon_name}".')
                icon_style = s["style"]
            ir = self._put(f"{id}__ic", id, round(x + 10),
                           round(y + (h - ic) / 2), ic, ic, icon_style, "", z=Z_FORE)
            ir["ob"] = False
        return r

    def legend(self, entries, xy, *, id="__legend") -> dict | None:
        """Legend box at ``xy``: one row per (label, color, dashed) flow entry."""
        entries = [e for e in (entries or []) if e and e[0]]
        if not entries:
            return None
        row_h, pad, sw = 24, 12, 36
        w = max(170, max(len(str(l)) for l, _, _ in entries) * 7 + sw + pad * 3)
        h = pad * 2 + 24 + row_h * len(entries)
        x, y = xy
        self.box(id, [x, y], [w, h], "LEGEND", fill=THEME.base, stroke="#AEB9C4",
                 va="top", bold=True, fs=12, round=True, ob=False, z=Z_CHROME)
        for i, (label, color, dashed) in enumerate(entries):
            ry = y + pad + 24 + i * row_h
            ln = self._put(f"{id}__ln{i}", id, x + pad, ry + 8, sw, 8,
                           f"line;html=1;strokeWidth=2;strokeColor={color};fillColor=none;"
                           + ("dashed=1;" if dashed else ""), "", z=Z_CHROME)
            ln["ob"] = False
            lb = self._put(f"{id}__lb{i}", id, x + pad + sw + 8, ry,
                           w - sw - pad * 2 - 8, row_h,
                           "text;html=1;align=left;verticalAlign=middle;fontSize=11;"
                           f"fontColor={THEME.font_color};", label, z=Z_CHROME)
            lb["ob"] = False
        return self.R[id]

    # ---- refined-preset emitters (playbook look; tokens from refined_theme) ---- #
    def pill(self, id, xy, wh, label, *, fill, stroke=None, font_color="#FFFFFF",
             fs=None, bold=True, arc=None, z=Z_CHROME, ob=False, parent="1") -> dict:
        """Rounded chip: zone folder-tabs, scope tags, backbone strip, AZ labels."""
        fs = fs if fs is not None else RT.TYPE_SCALE["pill"]
        arc = arc if arc is not None else RT.GEO["arc_pill"]
        style = (f"rounded=1;arcSize={arc};html=1;whiteSpace=wrap;fillColor={fill};"
                 f"strokeColor={stroke or fill};strokeWidth=1;align=center;"
                 f"verticalAlign=middle;fontFamily={RT.FONT};fontColor={font_color};"
                 f"fontSize={fs};fontStyle={1 if bold else 0};")
        r = self._put(id, parent, xy[0], xy[1], wh[0], wh[1], style, label, z=z)
        r["ob"] = ob
        return r

    def rich_card(self, id, xy, wh, title, body_lines=(), *, fill=None, stroke=None,
                  fs=None, align="left", dashed=False, font_color=None,
                  parent="1") -> dict:
        """Refined card: bold heading + 2-4 short body lines, flat (shadow=0),
        white-on-tint elevation. Playbook §10.2/§12 anatomy — no shadow cell,
        no accent stripe, no icon."""
        fs = fs if fs is not None else RT.TYPE_SCALE["card"]
        label = f"<b>{_esc(title)}</b>"
        lines = [str(l) for l in (body_lines or ()) if str(l).strip()]
        if lines:
            label += "<br><br>" + "<br>".join(_esc(l) for l in lines)
        va = "top" if align == "left" else "middle"
        style = (f"rounded=1;arcSize={RT.GEO['arc_zone']};html=1;whiteSpace=wrap;"
                 f"fillColor={fill or RT.CHROME['card_fill']};"
                 f"strokeColor={stroke or '#D0D5DD'};"
                 f"strokeWidth={RT.GEO['card_stroke_w']};shadow=0;align={align};"
                 f"verticalAlign={va};spacing={RT.GEO['card_spacing']};"
                 f"fontFamily={RT.FONT};fontColor={font_color or RT.INK['body']};"
                 f"fontSize={fs};" + ("dashed=1;" if dashed else ""))
        r = self._put(id, parent, xy[0], xy[1], wh[0], wh[1], style, label, z=Z_NODE)
        r["ob"] = True
        return r

    def note_card(self, id, xy, wh, title, lines=(), *, fill=None, stroke="#D0D5DD",
                  fs=None, parent="1") -> dict:
        """Semantic glue note (Security boundary / Runtime responsibility /
        Target outcome): small centred card carrying rationale, not a component."""
        fs = fs if fs is not None else RT.TYPE_SCALE["note"]
        label = f"<b>{_esc(title)}</b>"
        lines = [str(l) for l in (lines or ()) if str(l).strip()]
        if lines:
            label += "<br>" + "<br>".join(_esc(l) for l in lines)
        style = (f"rounded=1;arcSize={RT.GEO['arc_zone']};html=1;whiteSpace=wrap;"
                 f"fillColor={fill or RT.CHROME['card_fill']};strokeColor={stroke};"
                 f"strokeWidth=1;shadow=0;align=center;verticalAlign=middle;"
                 f"spacing=8;fontFamily={RT.FONT};fontColor={RT.INK['body']};"
                 f"fontSize={fs};")
        r = self._put(id, parent, xy[0], xy[1], wh[0], wh[1], style, label, z=Z_NODE)
        r["ob"] = True
        return r

    def tab_zone(self, id, xy, wh, title, hue, *, number=None, tint=True) -> dict:
        """Numbered refined zone: tinted rect + saturated folder-tab pill
        overlapping the top edge at zone.y - tab_overlap."""
        tab_fill, stroke, zone_tint = RT.ZONE_HUES.get(hue, RT.ZONE_HUES["slate"])
        style = (f"rounded=1;arcSize={RT.GEO['arc_zone']};html=1;whiteSpace=wrap;"
                 f"fillColor={zone_tint if tint else '#FFFFFF'};strokeColor={stroke};"
                 f"strokeWidth={RT.GEO['zone_stroke_w']};shadow=0;verticalAlign=top;"
                 f"align=left;spacing=12;fontFamily={RT.FONT};"
                 f"fontColor={RT.INK['body']};")
        r = self._put(id, "1", xy[0], xy[1], wh[0], wh[1], style, "", z=Z_CONTAINER)
        r["ob"] = False  # container: edges route across it
        label = f"{number} · {title}" if number is not None else str(title)
        tab_w = max(100, round(len(label) * 7.2) + 34)
        self.pill(f"tab_{id}", [xy[0] + 18, xy[1] - RT.GEO["tab_overlap"]],
                  [tab_w, RT.GEO["tab_h"]], label, fill=tab_fill,
                  fs=RT.TYPE_SCALE["tab"], z=Z_CHROME)
        return r

    def boundary_rect(self, id, xy, wh, kind, label="") -> dict:
        """Visual cloud/VPC/AZ boundary (refined preset): rect behind zones with
        its own colored tab. Never a parent — nesting is z-order only."""
        fill, stroke, dash, tab_fill = RT.BOUNDARY.get(kind, RT.BOUNDARY["cloud"])
        style = (f"rounded=1;arcSize={RT.GEO['arc_zone']};html=1;whiteSpace=wrap;"
                 f"fillColor={fill or 'none'};strokeColor={stroke};"
                 f"strokeWidth={RT.GEO['boundary_stroke_w']};shadow=0;")
        if dash:
            style += f"dashed=1;dashPattern={dash};"
        r = self._put(id, "1", xy[0], xy[1], wh[0], wh[1], style, "", z=Z_CONTAINER)
        r["ob"] = False
        if label:
            tab_w = max(90, round(len(label) * 7.2) + 30)
            self.pill(f"tab_{id}", [xy[0] + 20, xy[1] - RT.GEO["tab_overlap"]],
                      [tab_w, 28], label, fill=tab_fill,
                      fs=RT.TYPE_SCALE["tab"], z=Z_CHROME)
        return r

    def legend_band(self, id, xy, w, entries, *, scope_note="", metadata="",
                    title="CONNECTOR SEMANTICS & SCOPE", h=None) -> dict:
        """Refined footer band: edge-class swatches + optional scope note and
        metadata cards. The band itself is a router obstacle (edges must not
        tunnel through the footer)."""
        h = h or 145
        x, y = xy
        band = self._put(id, "1", x, y, w, h,
                         f"rounded=1;arcSize={RT.GEO['arc_zone']};html=1;"
                         f"whiteSpace=wrap;fillColor={RT.CHROME['strip_fill']};"
                         f"strokeColor={RT.CHROME['strip_stroke']};strokeWidth=1.3;"
                         f"shadow=0;", "", z=Z_CONTAINER)
        band["ob"] = True
        tx = self._put(f"{id}__title", "1", x + 25, y + 15, 280, 24,
                       f"text;html=1;align=left;verticalAlign=middle;"
                       f"fontFamily={RT.FONT};fontColor={RT.INK['slate']};"
                       f"fontSize=12;fontStyle=1;", title, z=Z_CHROME)
        tx["ob"] = False
        cx = x + 30
        sy = y + 60
        for i, (label, color, dashed) in enumerate(entries or []):
            ln = self._put(f"{id}__ln{i}", "1", cx, sy + 10, 45, 3,
                           f"line;html=1;strokeWidth=2;strokeColor={color};"
                           f"fillColor=none;" + ("dashed=1;dashPattern=6 4;" if dashed else ""),
                           "", z=Z_CHROME)
            ln["ob"] = False
            lw = max(90, round(len(str(label)) * 6.5) + 10)
            lb = self._put(f"{id}__lb{i}", "1", cx + 55, sy - 3, lw, 28,
                           f"text;html=1;align=left;verticalAlign=middle;"
                           f"fontFamily={RT.FONT};fontColor={RT.INK['body']};"
                           f"fontSize={RT.TYPE_SCALE['legend']};", label, z=Z_CHROME)
            lb["ob"] = False
            cx += 55 + lw + 30
        right = x + w
        if metadata:
            mw = 210
            md = self.note_card(f"{id}__meta", [right - mw - 30, y + 30],
                                [mw, 80], "", [metadata])
            md["ob"] = False
            right -= mw + 50
        if scope_note:
            sw = min(520, max(300, right - cx - 40))
            if sw >= 200:
                sn = self._put(f"{id}__scope", "1", right - sw - 20, y + 30, sw, 80,
                               f"rounded=1;arcSize={RT.GEO['arc_zone']};html=1;"
                               f"whiteSpace=wrap;fillColor=#FFFFFF;strokeColor=#D0D5DD;"
                               f"strokeWidth=1;shadow=0;align=left;verticalAlign=top;"
                               f"spacing=10;fontFamily={RT.FONT};"
                               f"fontColor={RT.INK['body']};fontSize=9.5;",
                               f"<b>Scope</b><br>{_esc(scope_note)}", z=Z_CHROME)
                sn["ob"] = False
        return band

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
        r = self._put(id, parent, xy[0], xy[1], wh[0], wh[1], style, label, z=Z_CONTAINER)
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
                  "fontStyle=1;fontSize=11;", label, z=Z_CONTAINER)
        if icon:
            s = _style_for_icon(self.c, icon)
            if not s:
                raise ValueError(f'clusterBox icon not found: "{icon}"')
            self._put(f"{id}_icon", "boundaries", x + 1, y + 1, icon_size, icon_size,
                      s["style"], "", z=Z_FORE)
        return self.R[id]

    def text(self, id, xy, w, label, *, fs=14, parent="1") -> None:
        p = self.R.get(parent)
        ox, oy = (0, 0) if parent == "1" or not p else (p["x"], p["y"])
        self.R[id] = {"x": xy[0], "y": xy[1], "w": w, "h": 30}
        self._emit_cell(id,
            f'<mxCell id="{id}" value="{_esc(label)}" style="text;html=1;align=center;'
            f'fontStyle=1;fontSize={fs};fontColor=light-dark(#232F3E,#E8E8E8);" '
            f'vertex="1" parent="{parent}"><mxGeometry x="{xy[0] - ox:.0f}" '
            f'y="{xy[1] - oy:.0f}" width="{w:.0f}" height="30" as="geometry"/></mxCell>',
            Z_CHROME)

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
        """Route + emit all edges via the deterministic A*/nudge router."""
        if self._edges_built:
            return
        self._edges_built = True
        # drop edges whose endpoints have no rect (phantom-only) before routing
        self.edge_specs = [e for e in self.edge_specs
                           if e["src"] in self.R and e["tgt"] in self.R]
        from .router import build_edges
        build_edges(self)

    # ---- export ---- #
    def to_xml(self) -> str:
        self._build_edges()
        # Stable-sort cells by z-bucket so connectors render behind card
        # shadows/bodies (V2 §7.2). Stable => equal-z cells keep emission order,
        # which preserves parent-before-child (containers z=0 < leaves z=30).
        order = sorted(range(len(self.cells)), key=lambda i: self._cell_z[i])
        cells_xml = "".join(self.cells[i] for i in order)
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
