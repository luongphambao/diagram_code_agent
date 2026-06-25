"""Slide compositing: render_slide, vstack_pngs, and PIL helpers."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from .constants import (
    FLOW_COLORS, SLIDE_HERO_H, SLIDE_MARGIN, SLIDE_PAGE_RATIO,
    SLIDE_PANEL_PAD, SLIDE_SIZE,
)


def _xml(s: str | None) -> str:
    return xml_escape(s or "", {'"': "&quot;"})


def _font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    names = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ) if bold else (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _gradient(size: tuple[int, int]):
    from PIL import Image

    w, h = size
    c1, c2, c3 = (4, 18, 22), (15, 57, 128), (17, 166, 142)
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        vy = y / max(h - 1, 1)
        for x in range(w):
            vx = x / max(w - 1, 1)
            mid = vx * 0.75 + vy * 0.25
            if mid < 0.52:
                t = mid / 0.52
                col = tuple(round(c1[i] * (1 - t) + c2[i] * t) for i in range(3))
            else:
                t = (mid - 0.52) / 0.48
                col = tuple(round(c2[i] * (1 - t) + c3[i] * t) for i in range(3))
            px[x, y] = col
    return img


def _draw_centered_text(draw, xy: tuple[int, int], text: str, font, fill,
                        max_width: int, line_gap: int = 8) -> int:
    words = (text or "").split()
    if not words:
        return xy[1]
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    y = xy[1]
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        draw.text((xy[0] - (box[2] - box[0]) / 2, y), line, font=font, fill=fill)
        y += (box[3] - box[1]) + line_gap
    return y


def _normal_legend(legend) -> list[dict[str, str]]:
    if not legend:
        return []
    out: list[dict[str, str]] = []
    for item in legend:
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("name") or "").strip()
            flow = str(item.get("flow") or "").strip()
            fcolor, fstyle = FLOW_COLORS.get(flow, ("#5A6573", "solid"))
            color = str(item.get("color") or fcolor).strip()
            style = str(item.get("style") or fstyle).strip()
        else:
            vals = list(item)
            label = str(vals[0]) if vals else ""
            color = str(vals[1]) if len(vals) > 1 else "#5A6573"
            style = str(vals[2]) if len(vals) > 2 else "solid"
        if label:
            out.append({"label": label, "color": color, "style": style})
    return out


def vstack_pngs(png_paths: list[str], out_png: str, gap: int = 26,
                bg: tuple[int, int, int] = (255, 255, 255)) -> None:
    """Stack PNGs top-to-bottom into one image, each centered horizontally."""
    from PIL import Image
    imgs = [Image.open(p).convert("RGBA") for p in png_paths]
    w = max(im.width for im in imgs)
    h = sum(im.height for im in imgs) + gap * (len(imgs) - 1)
    canvas = Image.new("RGBA", (w, h), (*bg, 255))
    y = 0
    for im in imgs:
        canvas.paste(im, ((w - im.width) // 2, y))
        y += im.height + gap
    canvas.convert("RGB").save(out_png)


def _compose_slide_png(body_png: str, out_png: str, *, title: str,
                       kicker: str | None, brand: str | None,
                       diagram_title: str | None, legend,
                       include_hero: bool = False) -> dict:
    from PIL import Image, ImageDraw

    panel_x = SLIDE_MARGIN
    panel_y = SLIDE_HERO_H + 34 if include_hero else SLIDE_MARGIN
    panel_w = SLIDE_SIZE - SLIDE_MARGIN * 2

    legend_items = _normal_legend(legend)
    legend_h = 118 if legend_items else 0
    caption_area = 74
    max_w = panel_w - SLIDE_PANEL_PAD * 2

    slide_h = round(SLIDE_SIZE / SLIDE_PAGE_RATIO)
    avail_h_for_body = (slide_h - panel_y - SLIDE_MARGIN
                        - caption_area - SLIDE_PANEL_PAD - legend_h)
    avail_h_for_body = max(avail_h_for_body, 100)

    body = Image.open(body_png).convert("RGBA")
    scale = min(max_w / body.width, avail_h_for_body / body.height)
    if abs(scale - 1.0) > 0.01:
        body = body.resize(
            (max(1, round(body.width * scale)), max(1, round(body.height * scale))),
            Image.LANCZOS,
        )
    body_render_h = avail_h_for_body
    panel_h = caption_area + body_render_h + SLIDE_PANEL_PAD + legend_h

    canvas = Image.new("RGB", (SLIDE_SIZE, slide_h), "white")
    if include_hero:
        canvas.paste(_gradient((SLIDE_SIZE, SLIDE_HERO_H)), (0, 0))
    draw = ImageDraw.Draw(canvas)

    if include_hero and brand:
        draw.text((SLIDE_SIZE - SLIDE_MARGIN, 54), brand, font=_font(58, bold=True),
                  fill="white", anchor="ra")
    if include_hero and kicker:
        _draw_centered_text(draw, (SLIDE_SIZE // 2, 284), kicker, _font(68),
                            (248, 250, 252), 1550)
    if include_hero:
        _draw_centered_text(draw, (SLIDE_SIZE // 2, 390), title, _font(78, bold=True),
                            "white", 1850, line_gap=12)

    draw.rounded_rectangle((panel_x, panel_y, panel_x + panel_w, panel_y + panel_h),
                           radius=4, fill="white", outline="#D7DEE8", width=2)

    caption = diagram_title or "System Architecture"
    cap_font = _font(34, bold=True)
    cap_box = draw.textbbox((0, 0), caption, font=cap_font)
    draw.text((SLIDE_SIZE // 2 - (cap_box[2] - cap_box[0]) / 2, panel_y + 22),
              caption, font=cap_font, fill="#0F172A")

    body_x = panel_x + (panel_w - body.width) // 2
    body_y = panel_y + caption_area + max(0, (body_render_h - body.height) // 2)
    canvas.paste(body, (body_x, body_y), body)

    if legend_items:
        lx, ly = panel_x + 26, panel_y + panel_h - legend_h + 18
        lw, lh = 260, legend_h - 36
        draw.rounded_rectangle((lx, ly, lx + lw, ly + lh), radius=8,
                               fill="#FFFFFF", outline="#CBD5E1", width=2)
        draw.text((lx + 16, ly + 12), "LEGEND", font=_font(17, bold=True),
                  fill="#334155")
        yy = ly + 40
        for item in legend_items[:4]:
            color = item["color"]
            if item["style"] == "dashed":
                for x in range(lx + 18, lx + 72, 16):
                    draw.line((x, yy + 9, x + 9, yy + 9), fill=color, width=3)
            else:
                draw.line((lx + 18, yy + 9, lx + 72, yy + 9), fill=color, width=3)
            draw.text((lx + 84, yy), item["label"], font=_font(16), fill="#334155")
            yy += 24

    canvas.save(out_png, quality=95)
    avail_h = body_render_h
    panel_fill_pct = (body.width * body.height) / (max_w * max(avail_h, 1))
    return {
        "panel": [panel_x, panel_y, panel_w, panel_h],
        "body": [body_x, body_y, body.width, body.height],
        "slide_h": slide_h,
        "fill_w": round(body.width / max_w, 4),
        "fill_h": round(body.height / max(avail_h, 1), 4),
        "panel_fill_pct": round(panel_fill_pct, 4),
        "legend_count": len(legend_items),
    }


def _drawio_text_cell(cid: str, value: str, x: float, y: float, w: float, h: float,
                      *, size: int, color: str = "#0F172A", bold: bool = False,
                      align: str = "center", fill: str = "none",
                      stroke: str = "none") -> str:
    style = (
        "text;html=1;strokeColor={stroke};fillColor={fill};align={align};"
        "verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize={size};"
        "fontColor={color};fontStyle={bold};"
    ).format(stroke=stroke, fill=fill, align=align, size=size,
             color=color, bold=1 if bold else 0)
    return (f'<mxCell id="{cid}" value="{_xml(value)}" style="{style}" vertex="1" '
            f'parent="1"><mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" '
            f'height="{h:.0f}" as="geometry"/></mxCell>')


def _drawio_rect_cell(cid: str, x: float, y: float, w: float, h: float,
                      *, fill: str, stroke: str = "none", rounded: int = 0,
                      shadow: int = 0) -> str:
    style = (
        f"rounded={rounded};whiteSpace=wrap;html=1;fillColor={fill};"
        f"strokeColor={stroke};shadow={shadow};"
    )
    return (f'<mxCell id="{cid}" value="" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" '
            f'height="{h:.0f}" as="geometry"/></mxCell>')


def _transform_drawio_body(xml: str, *, x: float, y: float, scale: float,
                           prefix: str = "body_") -> str:
    m = re.search(r"<root>(.*)</root>", xml, re.S)
    inner = m.group(1) if m else ""
    inner = re.sub(r'<mxCell id="0"/>\s*<mxCell id="1" parent="0"/>', "", inner)
    for attr in ("id", "source", "target"):
        inner = re.sub(fr'{attr}="([^"]+)"',
                       lambda mt: f'{attr}="{prefix}{mt.group(1)}"', inner)
    inner = inner.replace(f'parent="{prefix}1"', 'parent="1"')

    def _geo(mt: "re.Match[str]") -> str:
        gx = float(mt.group(1)) * scale + x
        gy = float(mt.group(2)) * scale + y
        gw = float(mt.group(3)) * scale
        gh = float(mt.group(4)) * scale
        return (f'<mxGeometry x="{gx:.0f}" y="{gy:.0f}" width="{gw:.0f}" '
                f'height="{gh:.0f}"')

    return re.sub(
        r'<mxGeometry x="(-?[\d.]+)" y="(-?[\d.]+)" width="([\d.]+)" height="([\d.]+)"',
        _geo,
        inner,
    )


def _compose_slide_drawio(body_xml: str, out_path: str, *, title: str,
                          kicker: str | None, brand: str | None,
                          diagram_title: str | None, legend, body_box: list[int],
                          panel: list[int], include_hero: bool = False,
                          slide_h: int = SLIDE_SIZE) -> str:
    from .drawio import _page_dims

    body_w, body_h = _page_dims(body_xml)
    bx, by, bw, bh = body_box
    scale = min(bw / body_w, bh / body_h) if body_w and body_h else 1.0
    body_inner = _transform_drawio_body(body_xml, x=bx, y=by, scale=scale)

    cells: list[str] = [
        _drawio_rect_cell("slide_bg", 0, 0, SLIDE_SIZE, slide_h, fill="#FFFFFF"),
        _drawio_rect_cell("slide_panel", panel[0], panel[1], panel[2], panel[3],
                          fill="#FFFFFF", stroke="#D7DEE8", rounded=1, shadow=1),
    ]
    if include_hero:
        cells.insert(1, _drawio_rect_cell("slide_hero", 0, 0, SLIDE_SIZE, SLIDE_HERO_H,
                                          fill="#075985"))
    if include_hero and brand:
        cells.append(_drawio_text_cell("slide_brand", brand, SLIDE_SIZE - 368, 44,
                                       330, 70, size=36, color="#FFFFFF",
                                       bold=True, align="right"))
    if include_hero and kicker:
        cells.append(_drawio_text_cell("slide_kicker", kicker, 244, 258, 1560, 86,
                                       size=42, color="#F8FAFC"))
    if include_hero:
        cells.append(_drawio_text_cell("slide_title", title, 90, 352, 1868, 132,
                                       size=50, color="#FFFFFF", bold=True))
    cells.append(_drawio_text_cell("slide_diagram_title",
                                   diagram_title or "System Architecture",
                                   panel[0] + 30, panel[1] + 18, panel[2] - 60, 48,
                                   size=26, color="#0F172A", bold=True))

    legend_items = _normal_legend(legend)
    if legend_items:
        lx, ly, lw, lh = panel[0] + 26, panel[1] + panel[3] - 100, 260, 82
        cells.append(_drawio_rect_cell("legend_box", lx, ly, lw, lh,
                                       fill="#FFFFFF", stroke="#CBD5E1", rounded=1))
        cells.append(_drawio_text_cell("legend_title", "LEGEND", lx + 12, ly + 8,
                                       94, 24, size=13, color="#334155",
                                       bold=True, align="left"))
        yy = ly + 36
        for i, item in enumerate(legend_items[:4]):
            style = "dashed=1;" if item["style"] == "dashed" else ""
            cells.append(
                f'<mxCell id="legend_line_{i}" value="" style="endArrow=none;html=1;'
                f'rounded=0;strokeWidth=3;{style}strokeColor={_xml(item["color"])};" '
                f'edge="1" parent="1"><mxGeometry width="50" height="50" relative="1" '
                f'as="geometry"><mxPoint x="{lx + 18:.0f}" y="{yy + 10:.0f}" as="sourcePoint"/>'
                f'<mxPoint x="{lx + 72:.0f}" y="{yy + 10:.0f}" as="targetPoint"/>'
                f'</mxGeometry></mxCell>'
            )
            cells.append(_drawio_text_cell(f"legend_label_{i}", item["label"],
                                           lx + 84, yy, 148, 22, size=12,
                                           color="#334155", align="left"))
            yy += 24

    xml_out = (
        '<mxfile host="app.diagrams.net"><diagram name="architecture" id="d1">'
        '<mxGraphModel dx="1400" dy="900" grid="0" guides="1" tooltips="1" '
        'connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        f'pageWidth="{SLIDE_SIZE}" pageHeight="{slide_h}" math="0" shadow="0">'
        '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        + "".join(cells) + body_inner + "</root></mxGraphModel></diagram></mxfile>"
    )
    Path(out_path).write_text(xml_out, encoding="utf-8")
    return xml_out


def render_slide(g, out_basename: str, *, title: str,
                 kicker: str | None = None, brand: str | None = None,
                 diagram_title: str | None = None, legend=None,
                 include_hero: bool = False) -> str:
    """Render ``g`` as a single-page 16:9 landscape slide (white background)."""
    from PIL import Image as _Img

    out = Path(out_basename)
    png_path = f"{out_basename}.png"
    drawio_path = f"{out_basename}.drawio"
    marker_path = f"{out_basename}.slide.json"

    body_png = g.render(out_basename)

    _bw, _bh = _Img.open(body_png).size
    _panel_w = SLIDE_SIZE - SLIDE_MARGIN * 2
    _max_w_tmp = _panel_w - SLIDE_PANEL_PAD * 2
    _needed = _max_w_tmp / max(_bw, 1)
    if _needed > 1.15:
        _base_dpi = g.dpi or (192 if g.theme == "pro" else 168)
        body_png = g.render(out_basename, dpi_override=round(_base_dpi * _needed))

    body_copy = f"{out_basename}.body.png"
    shutil.copy(body_png, body_copy)
    body_xml = g.to_drawio(out_basename)
    layout = _compose_slide_png(
        body_png, png_path, title=title, kicker=kicker, brand=brand,
        diagram_title=diagram_title or g.title, legend=legend,
        include_hero=include_hero,
    )
    _compose_slide_drawio(
        body_xml, drawio_path, title=title, kicker=kicker, brand=brand,
        diagram_title=diagram_title or g.title, legend=legend,
        body_box=layout["body"], panel=layout["panel"], include_hero=include_hero,
        slide_h=layout.get("slide_h", SLIDE_SIZE),
    )
    Path(marker_path).write_text(json.dumps({
        "type": "slide",
        "title": title,
        "kicker": kicker,
        "brand": brand,
        "diagram_title": diagram_title or g.title,
        "include_hero": include_hero,
        "png": str(out.with_suffix(".png")),
        "body_png": str(out.with_suffix(".body.png")),
        "drawio": str(out.with_suffix(".drawio")),
        "dot": str(out.with_suffix(".dot")),
        "layout": layout,
    }, indent=2), encoding="utf-8")
    return png_path
