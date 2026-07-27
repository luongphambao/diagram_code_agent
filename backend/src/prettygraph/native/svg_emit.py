"""Offline SVG rendering of an already-exported .drawio page.

``to_svg`` is a reprojection of the SAME XML ``validate_drawio._parse_cells``
already parses — not a parallel "element list" collected during construction
— so a card's box and wrapped text can never disagree between the .drawio a
viewer shows and the SVG this module produces: there is only one source, the
exported XML itself.

Used as a network-free PNG fallback (see ``rendering_tools._render_drawio_png``)
when neither the draw.io desktop CLI nor outbound HTTPS to
viewer.diagrams.net is available.

Fidelity note: a node with a baked icon (``image=data:...`` in its style —
the common case, since icon_resolver bakes a real vendor PNG per node)
renders pixel-faithful. The narrow set of un-baked generic vendor-stencil
glyphs (``mxgraph.aws4.generic_firewall`` / ``globe`` / ``connector`` / ...
— the Level-4 fallback icon a node gets only when no specific vendor icon
was resolved, see ``rendering_tools._CATEGORY_GLYPHS``) render as a plain
tinted placeholder instead of the exact glyph: reproducing draw.io's own
stencil shape library is out of scope for a fallback renderer.
"""

from __future__ import annotations

import re
from html import escape as _esc
from html import unescape as _unesc

from domain.validation.validate_drawio import _parse_cells  # type: ignore[import-not-found]

from ..text_metrics import LINE_HEIGHT
from ..text_metrics import wrap as _wrap

_DATA_URI_NO_B64 = re.compile(r"^data:([a-zA-Z0-9.+_-]+/[a-zA-Z0-9.+_-]+),")


def _fix_data_uri(uri: str) -> str:
    """``builder.py`` strips ``;base64` from embedded image data URIs so the
    comma-delimited mxCell style string survives (see its own comment on
    this) — a real browser's ``<image>`` decoder has no such special case
    and needs the marker back to treat the payload as base64, not literal
    text."""
    if uri.startswith("data:") and ";base64," not in uri:
        return _DATA_URI_NO_B64.sub(lambda m: f"data:{m.group(1)};base64,", uri, count=1)
    return uri


def _style_dict(style: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in style.split(";"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
        else:
            out[part] = "1"
    return out


def _page_size(xml: str) -> tuple[float, float]:
    m = re.search(r"<mxGraphModel\b[^>]*>", xml)
    if m:
        head = m.group(0)
        w = re.search(r'pageWidth="([\d.]+)"', head)
        h = re.search(r'pageHeight="([\d.]+)"', head)
        if w and h:
            return float(w.group(1)), float(h.group(1))
    return 1600.0, 1200.0


def _primary_page(xml: str) -> str:
    """First ``<mxGraphModel>`` only — the refined upgrade path keeps the
    untouched original as page 2, which must never bleed into the render."""
    start = xml.find("<mxGraphModel")
    if start == -1:
        return xml
    end = xml.find("</mxGraphModel>", start)
    return xml[start : end + len("</mxGraphModel>")] if end != -1 else xml[start:]


def _text_lines(value: str | None) -> tuple[str | None, list[str]]:
    """Split a cell's HTML value into (bold title or None, body lines) —
    reuses the exact ``<b>``/``<br>`` line breaks the renderer already baked
    in (post text-metrics fix these already match real geometry), so this
    module never re-wraps and risks disagreeing with the engine."""
    # Some chrome labels (zone/tab titles with a literal "&") get HTML-escaped
    # twice before landing in the XML attribute — validate_drawio.py works
    # around the exact same quirk; mirror it so "&amp;amp;" doesn't survive
    # as literal text after a single unescape pass.
    value = (value or "").replace("&amp;amp;", "&").replace("&amp;", "&")
    value = _unesc(value)
    bm = re.search(r"<b>(.*?)</b>", value, re.S)
    title = re.sub("<[^>]+>", "", bm.group(1)).strip() if bm else None
    rest = re.sub(r"<b>.*?</b>", "", value, flags=re.S) if bm else value
    body = [re.sub("<[^>]+>", "", part).strip() for part in rest.split("<br>")]
    body = [b for b in body if b]
    return title, body


_FALLBACK_GLYPH_FILL = "#E7EBF0"


def _render_text(value: str, style: dict[str, str], x: float, y: float, w: float, h: float) -> str:
    title, body = _text_lines(value)
    if not title and not body:
        return ""
    fs = float(style.get("fontSize") or 12)
    color = style.get("fontColor") or "#101828"
    if color.startswith("light-dark("):
        color = color[len("light-dark(") : -1].split(",")[0].strip()
    bold_style = style.get("fontStyle") == "1"
    align = style.get("align", "center")
    valign = style.get("verticalAlign", "middle")

    lines: list[tuple[str, bool]] = []
    if title:
        lines.append((title, True))
    lines.extend((b, bold_style) for b in body)

    # mxGraph label inset: a base `spacing` (all sides, default 2) plus a
    # per-side override that's ADDITIVE, not a replacement — zone tab titles
    # in particular declare spacingLeft=52 to clear their own icon glyph
    # (a separate overlapping cell, e.g. tab_zone_x__ic), so a flat generic
    # pad here would draw the title text right under that icon.
    base = float(style.get("spacing") or 2)
    pad_l = base + float(style.get("spacingLeft") or 0)
    pad_r = base + float(style.get("spacingRight") or 0)
    pad_t = base + float(style.get("spacingTop") or 0)
    pad_b = base + float(style.get("spacingBottom") or 0)

    # Card BODY lines are already pre-wrapped by the engine (post text-metrics
    # fix these `<br>` breaks already match real geometry, so this is a
    # no-op for them). Short chrome labels — zone/tab titles in particular —
    # are NOT pre-wrapped: they rely on drawio's own `whiteSpace=wrap` reflow
    # at render time, which this module doesn't otherwise replicate. Re-wrap
    # every logical line against the real available width so those titles
    # don't overflow their box instead of reflowing to a second line.
    if style.get("whiteSpace") == "wrap":
        avail_w = max(10.0, w - pad_l - pad_r)
        lines = [(part, bold) for text, bold in lines for part in (_wrap(text, avail_w, fs, bold) or [text])]

    line_h = fs * LINE_HEIGHT
    if align == "left":
        tx, anchor = x + pad_l, "start"
    elif align == "right":
        tx, anchor = x + w - pad_r, "end"
    else:
        tx, anchor = x + w / 2, "middle"

    total_h = line_h * len(lines)
    if valign == "top":
        ty0 = y + pad_t + fs
    elif valign == "bottom":
        ty0 = y + h - pad_b - total_h + fs
    else:
        ty0 = y + h / 2 - total_h / 2 + fs

    out = [f'<text font-family="Helvetica, Arial, sans-serif" font-size="{fs:.1f}" fill="{_esc(color)}">']
    for i, (text, bold) in enumerate(lines):
        ty = ty0 + i * line_h
        weight = ' font-weight="bold"' if bold else ""
        out.append(f'<tspan x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}"{weight}>{_esc(text)}</tspan>')
    out.append("</text>")
    return "".join(out)


def _render_vertex(c: dict) -> str:
    style = _style_dict(c["style"] or "")
    g = c["absGeo"] or c["geo"]
    x, y, w, h = g["x"], g["y"], g["w"], g["h"]
    raw_style = c["style"] or ""

    if "image" in style:
        href = _fix_data_uri(style["image"])
        if not href.startswith("data:"):
            return ""
        return f'<image x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" href="{_esc(href)}" preserveAspectRatio="xMidYMid meet"/>'

    if re.match(r"^line(;|$)", raw_style):
        stroke = style.get("strokeColor", "#64748B")
        stroke_w = style.get("strokeWidth", "1")
        dash = ' stroke-dasharray="6,4"' if style.get("dashed") == "1" else ""
        y_mid = y + h / 2
        return f'<line x1="{x:.1f}" y1="{y_mid:.1f}" x2="{x + w:.1f}" y2="{y_mid:.1f}" stroke="{stroke}" stroke-width="{stroke_w}"{dash}/>'

    out: list[str] = []
    is_text_only = bool(re.match(r"^text(;|$)", raw_style))
    if not is_text_only:
        fill = style.get("fillColor", "none")
        stroke = style.get("strokeColor", "none")
        stroke_w = style.get("strokeWidth", "1")
        dash = ' stroke-dasharray="6,4"' if style.get("dashed") == "1" else ""
        shape = style.get("shape", "")
        if shape.startswith("mxgraph.") and "image" not in style:
            # un-baked vendor stencil glyph — neutral placeholder, see module docstring
            out.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="4" '
                f'fill="{_FALLBACK_GLYPH_FILL}" stroke="{stroke if stroke != "none" else "#98A2B3"}" stroke-width="1"/>'
            )
        elif "ellipse" in raw_style.split(";"):
            out.append(
                f'<ellipse cx="{x + w / 2:.1f}" cy="{y + h / 2:.1f}" rx="{w / 2:.1f}" ry="{h / 2:.1f}" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_w}"{dash}/>'
            )
        else:
            rounded = style.get("rounded") == "1"
            arc = (float(style.get("arcSize") or 8) / 100.0) * min(w, h) if rounded else 0.0
            out.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{arc:.1f}" ry="{arc:.1f}" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_w}"{dash}/>'
            )

    if c["value"]:
        out.append(_render_text(c["value"], style, x, y, w, h))
    return "".join(out)


def _anchor(g: dict, fx: float | None, fy: float | None) -> tuple[float, float]:
    return g["x"] + (fx if fx is not None else 0.5) * g["w"], g["y"] + (fy if fy is not None else 0.5) * g[
        "h"
    ]


def _label_chip(text: str, cx: float, cy: float, fs: float, color: str, bg: str | None) -> str:
    from ..text_metrics import text_width as tm_text_width

    w = tm_text_width(text, fs) + 8
    h = fs * LINE_HEIGHT
    out = []
    if bg and bg.upper() != "NONE":
        out.append(
            f'<rect x="{cx - w / 2:.1f}" y="{cy - h / 2:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{bg}"/>'
        )
    out.append(
        f'<text x="{cx:.1f}" y="{cy + fs * 0.32:.1f}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" '
        f'font-size="{fs:.1f}" fill="{_esc(color)}">{_esc(text)}</text>'
    )
    return "".join(out)


def _render_edge(c: dict, by_id: dict, markers: dict[str, str]) -> str:
    style = _style_dict(c["style"] or "")
    src, tgt = by_id.get(c["source"]), by_id.get(c["target"])
    sg = (src["absGeo"] or src["geo"]) if src and src["geo"] else None
    tg = (tgt["absGeo"] or tgt["geo"]) if tgt and tgt["geo"] else None
    if not sg or not tg:
        return ""

    def f(k: str) -> float | None:
        v = style.get(k)
        try:
            return float(v) if v is not None else None
        except ValueError:
            return None

    sx, sy = _anchor(sg, f("exitX"), f("exitY"))
    tx, ty = _anchor(tg, f("entryX"), f("entryY"))
    points = [(sx, sy), *[(p["x"], p["y"]) for p in c["wp"]], (tx, ty)]
    path_d = f"M {points[0][0]:.1f} {points[0][1]:.1f} " + " ".join(
        f"L {px:.1f} {py:.1f}" for px, py in points[1:]
    )
    stroke = style.get("strokeColor", "#64748B")
    stroke_w = style.get("strokeWidth", "1")
    dash = ' stroke-dasharray="6,4"' if style.get("dashed") == "1" else ""
    marker = (
        f' marker-end="url(#{markers[stroke]})"'
        if style.get("endArrow", "block") != "none" and stroke in markers
        else ""
    )

    out = [f'<path d="{path_d}" fill="none" stroke="{stroke}" stroke-width="{stroke_w}"{dash}{marker}/>']

    label = (c["value"] or "").strip()
    if label:
        title, body = _text_lines(label)
        text = title or (body[0] if body else "")
        if text:
            mid = len(points) // 2
            mx = (points[mid - 1][0] + points[mid][0]) / 2
            my = (points[mid - 1][1] + points[mid][1]) / 2
            if c["label_offset"]:
                mx += c["label_offset"]["x"]
                my += c["label_offset"]["y"]
            fs = float(style.get("fontSize") or 10)
            color = style.get("fontColor") or "#101828"
            bg = style.get("labelBackgroundColor")
            out.append(_label_chip(text, mx, my, fs, color, bg))
    return "".join(out)


def _arrow_defs(colors: set[str]) -> tuple[str, dict[str, str]]:
    ids: dict[str, str] = {}
    defs = ["<defs>"]
    for i, color in enumerate(sorted(colors)):
        mid = f"arrow{i}"
        ids[color] = mid
        defs.append(
            f'<marker id="{mid}" viewBox="0 0 8 8" markerWidth="7" markerHeight="7" '
            f'refX="7" refY="4" orient="auto-start-reverse">'
            f'<path d="M0,0 L8,4 L0,8 Z" fill="{color}"/></marker>'
        )
    defs.append("</defs>")
    return "".join(defs), ids


def to_svg(xml: str) -> str:
    """Render page 1 of an exported .drawio XML string to a standalone SVG
    document string."""
    page = _primary_page(xml)
    page_w, page_h = _page_size(page)
    cells = _parse_cells(page)
    by_id = {c["id"]: c for c in cells if c["id"]}

    edge_colors = {
        _style_dict(c["style"] or "").get("strokeColor", "#64748B")
        for c in cells
        if c["edge"] == "1" and c.get("source") in by_id and c.get("target") in by_id
    } or {"#64748B"}
    defs, markers = _arrow_defs(edge_colors)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{page_w:.0f}" height="{page_h:.0f}" '
        f'viewBox="0 0 {page_w:.0f} {page_h:.0f}">',
        defs,
        f'<rect x="0" y="0" width="{page_w:.0f}" height="{page_h:.0f}" fill="#FFFFFF"/>',
    ]
    # Single pass in document order: cells are already stable-sorted into the
    # builder's z-buckets (container < edge < shadow < node < fore < chrome,
    # see builder.py) when exported, so preserving parse order here is what
    # keeps a routed connector UNDER card bodies instead of slicing through
    # a title — splitting into a "vertices, then edges" pass would silently
    # invert that.
    for c in cells:
        if not c["id"]:
            continue
        if c["edge"] == "1":
            parts.append(_render_edge(c, by_id, markers))
        elif c["geo"]:
            parts.append(_render_vertex(c))
    parts.append("</svg>")
    return "".join(p for p in parts if p)
