"""Editable BnK PowerPoint proposal generation for architecture diagrams."""

from __future__ import annotations

import contextvars
import datetime as dt
import json
import re
import warnings
from copy import deepcopy
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_AUTO_SIZE, MSO_ANCHOR
from pptx.util import Inches, Pt

# --- BnK brand palette (Calibri + corporate blue, from template style guide) ---
# BNK_ACCENT/BNK_WHITE/BNK_TEXT/BNK_FONT are style-invariant (every preset shares them);
# BNK_BLUE/BNK_CYAN/BNK_LIGHT are the only 3 colors that actually vary by deck_style (see
# _STYLE_PRESETS below) — kept as module "constants" here purely as the default/fallback
# value, but every render call site reads them through _palette() instead, not by name.
BNK_ACCENT = RGBColor(0xC0, 0x3A, 0x2B)  # red accent (required/important)
BNK_WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BNK_TEXT = RGBColor(0x33, 0x33, 0x33)
BNK_FONT = "Calibri"

# Selectable visual presets (docx WS5 — mirrors the diagram engine's
# style_preset="refined"/"icon" pattern). Each preset is a richer object now (WS "VIP" —
# added font/text/accent_light/card_shadow/eyebrow/divider_gradient on top of the original
# 3 colors): the 3 pre-existing presets set the new keys to their "off" defaults (Calibri,
# no shadow, no eyebrow parsing, no gradient background) so their rendered output is
# unchanged; only "vip" turns the new visual language on.
_STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "corporate": {  # the original BnK default — unchanged from before deck_style existed
        "blue": RGBColor(0x1F, 0x4E, 0x78),
        "cyan": RGBColor(0x00, 0x9F, 0xDF),
        "light": RGBColor(0xE9, 0xF0, 0xF7),
        "text": BNK_TEXT,
        "accent_light": RGBColor(0xE9, 0xF0, 0xF7),
        "font": BNK_FONT,
        "card_shadow": False,
        "eyebrow": False,
        "divider_gradient": None,
    },
    "modern": {  # cooler slate + teal, higher contrast
        "blue": RGBColor(0x10, 0x2A, 0x43),
        "cyan": RGBColor(0x14, 0xB8, 0xA6),
        "light": RGBColor(0xE6, 0xF7, 0xF5),
        "text": BNK_TEXT,
        "accent_light": RGBColor(0xE6, 0xF7, 0xF5),
        "font": BNK_FONT,
        "card_shadow": False,
        "eyebrow": False,
        "divider_gradient": None,
    },
    "minimal": {  # near-monochrome charcoal + a single muted accent
        "blue": RGBColor(0x2B, 0x2B, 0x2B),
        "cyan": RGBColor(0x6B, 0x7A, 0x8F),
        "light": RGBColor(0xF2, 0xF2, 0xF2),
        "text": BNK_TEXT,
        "accent_light": RGBColor(0xF2, 0xF2, 0xF2),
        "font": BNK_FONT,
        "card_shadow": False,
        "eyebrow": False,
        "divider_gradient": None,
    },
    "vip": {  # navy/teal premium look — modeled on the FMCG Storybook reference deck
        "blue": RGBColor(0x0B, 0x1A, 0x2F),  # deep navy — table headers, eyebrow-on-dark
        "cyan": RGBColor(0x19, 0xA8, 0x87),  # primary teal — accents, stat numbers
        "light": RGBColor(0xE9, 0xF7, 0xF2),  # pale teal tint — card backgrounds
        "text": RGBColor(0x1D, 0x3C, 0x47),  # ink navy — body text
        "accent_light": RGBColor(0xC8, 0xEB, 0xDD),  # card border / secondary tint
        "font": "Inter",
        "card_shadow": True,
        "eyebrow": True,
        "divider_gradient": (RGBColor(0x0B, 0x1A, 0x2F), RGBColor(0x19, 0xA8, 0x87)),
    },
}
DECK_STYLES: tuple[str, ...] = tuple(_STYLE_PRESETS)

# contextvars, not a plain module global: generate_ppt_proposal_file can run for
# different threads/users concurrently within the same process (per-thread workspace
# isolation elsewhere in this backend — see backends.py §4.10), so the active style must
# be request-scoped, never shared mutable state. Mirrors observability.set_context's
# established pattern in this codebase for the same class of problem.
_deck_style_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("deck_style", default="corporate")


def _palette() -> dict[str, Any]:
    return _STYLE_PRESETS.get(_deck_style_ctx.get(), _STYLE_PRESETS["corporate"])


def set_deck_style(style: str) -> contextvars.Token:
    """Activate ``style`` for the CURRENT request/task only. Returns a token — pass it to
    ``_deck_style_ctx.reset(token)`` when the render finishes, so a later request on a
    reused thread never inherits a prior request's style. Unknown names fall back to
    "corporate" rather than raising, since a bad deck_style must never block a render."""
    return _deck_style_ctx.set(style if style in _STYLE_PRESETS else "corporate")

from domain.reporting.reporting import (
    DEFAULT_REPORT_SECTIONS,
    _repo_root,
    assemble_report_data,
    normalize_sections,
    read_json_file,
    record_artifact_inventory,
    record_report_step,
)

DEFAULT_PPT_SECTIONS = [
    "cover",
    "agenda",
    "executive_summary",
    "success_story",
    "solution_overview",
    "scope",
    "architecture_diagram",
    "technical_stack",
    "key_decisions",
    "delivery_plan",
    "pricing",
    "risks",
    "appendix",
]

SECTION_ALIASES = {
    "solution": "solution_overview",
    "overview": "solution_overview",
    "diagram": "architecture_diagram",
    "architecture": "architecture_diagram",
    "techstack": "technical_stack",
    "tech_stack": "technical_stack",
    "decisions": "key_decisions",
    "delivery": "delivery_plan",
    "team": "delivery_plan",
    "wbs": "delivery_plan",
    "price": "pricing",
    "pricing": "pricing",
    "capex": "pricing",
    "cost": "pricing",
    "risk": "risks",
    "artifact": "appendix",
    "reference": "appendix",
}

# Layout names below MUST match the actual layout names inside the BnK template
# (verified via python-pptx). Note the double space in the separator layout name.
VALID_LAYOUTS = frozenset(
    {
        "Cover-01",
        "Head Page",
        "Head-01",
        "Detail-01",
        "Overview-01",
        "Empty",
        "BnK",
        "C2 -  Separator/ Dark",
    }
)

# Closing/separator layouts that are appended via _append_thank_you, never rendered inline.
CLOSING_LAYOUTS = frozenset({"BnK", "C2 -  Separator/ Dark"})

# Structured content blocks an outline slide may carry (in addition to plain bullets).
VALID_BLOCKS = frozenset(
    {
        "bullets",
        "tech_stack_table",
        "func_nfr",
        "sdlc",
        "delivery_effort",
        "pricing",
        "milestones",
        "team",
        "gantt",  # rendered via _gantt_slide; not yet dispatched from _render_block's
        # legacy outline path — see deck_resolver._b_master_plan for the params shape.
        "case_study",  # rendered via _case_study_slide; params come from SlideSpec.params
        # (one contract emits several slides — see deck._build_deck_plan_registry).
        "wbs_detail_image",  # the "2. WBS" sheet screenshot — no native equivalent exists,
        # rendered ONLY when wbs_excel_render has produced it (see _wbs_sheet_image_path).
        "diagram_image",  # a finalized non-architecture diagram (sequence/erd/state_machine/
        # process) from diagram_manifest.json; params come from SlideSpec.params (WS4).
    }
)

OUTLINE_TARGET_MIN = 20
OUTLINE_TARGET_MAX = 30

_OUTLINE_SYSTEM_PROMPT = """\
You are a senior solution architect at BnK, a Vietnamese technology consultancy.
Generate a professional PowerPoint proposal slide outline for a client project.

OUTPUT FORMAT — each slide MUST have these fields:
{
  "title": "SECTION | Sub-topic",
  "layout": "<layout_name>",
  "block": "<block_type>",
  "bullets": ["...", "..."],
  "asset_ref": null
}

VALID LAYOUT NAMES (use EXACTLY as written):
  "Cover-01"              — Opening cover. Use ONCE as slide 1. Set title to "".
  "Head Page"            — Major section divider with Roman numeral (I., II., III., …).
  "Head-01"              — Secondary section header, no Roman numeral.
  "Detail-01"            — Content slide with title + bullets. Most common.
  "Overview-01"          — Overview: put one subtitle string in bullets[0], no other bullets.
  "Empty"                — Full-width image slide. Use with asset_ref: "architecture_diagram".
  "BnK"                  — Closing brand slide. Appended automatically; do NOT emit.
  "C2 -  Separator/ Dark" — Dark separator. Appended automatically; do NOT emit.

CONTENT BLOCKS — set "block" to render a professional table instead of bullets.
For these, "layout" is ignored (always Detail-01) and "bullets" may be []:
  "bullets"          — (default) plain bullet slide on the given layout.
  "tech_stack_table" — table Layer | Technology | Description, built from TECH_STACK data.
  "func_nfr"         — two columns: Functional vs Non-Functional Requirements.
  "sdlc"             — SCOPE OF WORK SDLC phase table (Analysis→Maintenance).
  "delivery_effort"  — effort table Code | Module | MD, built from WBS_SUMMARY.
  "pricing"          — CAPEX cost table (NET, excluding taxes).
  "milestones"       — payment milestones table (30/30/30/10).
  "team"             — Client Team vs BnK Team table.
When using a block, DO NOT also invent bullet content for that table — leave bullets [].

SLIDE COUNT: Generate exactly 20-30 slides total.

TYPICAL STRUCTURE (adapt to the actual project data; use blocks where noted):
  1.   Cover-01                          cover
  2.   Head Page                         "I. Executive Summary"
  3-4. Detail-01 (bullets)               executive highlights, business value
  5.   Head Page                         "II. Proposed Solution"
  6.   Overview-01                       solution scope overview (subtitle in bullets[0])
  7.   block:"func_nfr"                  "PROPOSED SOLUTION | Requirements"
  8-9. Detail-01 (bullets)               approach, key features
  10.  Head-01                           "Architecture Overview"
  11.  Empty (asset_ref diagram)         architecture diagram
  12.  block:"tech_stack_table"          "PROPOSED SOLUTION | Technical Stack"
  13.  Head Page                         "IV. Scope of Work"
  14.  block:"sdlc"                      "SCOPE OF WORK | SDLC Phases"
  15.  Detail-01 (bullets)               deliverables, assumptions, change request
  16.  Head Page                         "V. Project Delivery"
  17.  block:"delivery_effort"           "PROJECT DELIVERY | Estimated Effort"
  18.  block:"team"                      "PROJECT DELIVERY | Team Structure"
  19.  Detail-01 (bullets)               risks & mitigations
  20.  Head Page                         "VI. Pricing"
  21.  block:"pricing"                   "PRICING | CAPEX"
  22.  block:"milestones"                "PRICING | Payment Milestones"
  (BnK closing slide is appended automatically — do not include it.)

TITLE FORMAT:
  - Detail-01 / blocks: "SECTION | Sub-topic"  e.g. "PROPOSED SOLUTION | Technical Stack"
  - Head Page / Head-01: section name with Roman numeral  e.g. "IV. Scope of Work"
  - Cover-01: empty string ""

RULES:
  1. Use ONLY the layout names and block names listed — no other values.
  2. Cover-01 must be slide 1; do NOT emit BnK / separator (appended automatically).
  3. Include the Empty/diagram slide ONLY if HAS_ARCHITECTURE_DIAGRAM is yes.
  4. Include block:"delivery_effort" only if WBS_SUMMARY has data; otherwise use bullets.
  5. Base ALL content on the actual project data — no generic placeholders.
  6. OUTPUT: Return ONLY the JSON array. No code fences, no text outside the array.\
"""


class PPTProposalError(RuntimeError):
    """Raised when PPT proposal generation cannot complete."""


def _template_path() -> Path:
    # parents[0]=domain/reporting/, [1]=domain/, [2]=src/, [3]=backend/ — bundled alongside the package
    return Path(__file__).resolve().parents[3] / "templates" / "bnk_proposal_template.pptx"


def _clip(text: Any, limit: int = 220) -> str:
    value = " ".join(str(text or "").split())
    return value[:limit].rstrip() + ("..." if len(value) > limit else "")


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def normalize_ppt_sections(sections: list[str] | None) -> tuple[list[str], list[str]]:
    if not sections:
        return DEFAULT_PPT_SECTIONS.copy(), []
    out: list[str] = []
    unrecognized: list[str] = []
    for raw in sections:
        name = SECTION_ALIASES.get(str(raw).strip().lower(), str(raw).strip().lower())
        if name in DEFAULT_PPT_SECTIONS and name not in out:
            out.append(name)
        elif name not in DEFAULT_PPT_SECTIONS:
            unrecognized.append(str(raw).strip())
    if unrecognized and len(unrecognized) > len(sections) / 2:
        return DEFAULT_PPT_SECTIONS.copy(), unrecognized
    return out or DEFAULT_PPT_SECTIONS.copy(), unrecognized


_ROMAN = [
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
]


def _roman(n: int) -> str:
    result = ""
    for val, numeral in _ROMAN:
        while n >= val:
            result += numeral
            n -= val
    return result


def _layout(prs: Presentation, *names: str):
    wanted = [n.lower() for n in names]
    by_name = {layout.name.lower(): layout for layout in prs.slide_layouts}
    for name in wanted:  # honour caller priority order
        if name in by_name:
            return by_name[name]
    # Prefer a neutral content/blank layout over slide_layouts[0] (which is the cover).
    for safe in ("detail-01", "blank", "empty"):
        if safe in by_name:
            warnings.warn(
                f"PPT layout(s) {list(names)!r} not found; using {by_name[safe].name!r} fallback.",
                stacklevel=3,
            )
            return by_name[safe]
    warnings.warn(
        f"PPT layout(s) {list(names)!r} not found in template; using layout[0] as fallback.",
        stacklevel=3,
    )
    return prs.slide_layouts[0]


def _clear_slides(prs: Presentation) -> None:
    slide_id_list = prs.slides._sldIdLst  # noqa: SLF001 - python-pptx has no public clear API.
    for slide_id in list(slide_id_list):
        rid = slide_id.rId
        prs.part.drop_rel(rid)
        slide_id_list.remove(slide_id)


def _set_placeholder_text(slide, idx: int, text: str) -> bool:
    for shape in slide.placeholders:
        try:
            if shape.placeholder_format.idx == idx:
                shape.text = text
                return True
        except Exception:
            continue
    return False


def _body_placeholder(slide):
    """Return the slide's BODY/content placeholder (idx 13 in Detail-01) if present."""
    from pptx.enum.shapes import PP_PLACEHOLDER

    for shape in slide.placeholders:
        try:
            ph_type = shape.placeholder_format.type
        except Exception:
            continue
        if ph_type in (PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT):
            return shape
    return None


def _fill_bullets_placeholder(slide, items: list[Any], *, font_size: int = 16, limit: int = 7) -> bool:
    """Fill the template's body placeholder with bullets (inherits brand styling).

    Returns True if a placeholder was used, False if none exists.
    """
    ph = _body_placeholder(slide)
    if ph is None:
        return False
    tf = ph.text_frame
    tf.clear()
    tf.word_wrap = True
    bullets = [_clip(item, 180) for item in items[:limit] if str(item or "").strip()]
    if not bullets:
        bullets = ["Details will be confirmed during proposal review."]
    for i, item in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = item
        p.level = 0
        for run in p.runs:
            run.font.size = Pt(font_size)
    return True


def _add_textbox(
    slide,
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    font_size: int = 16,
    bold: bool = False,
    align: PP_ALIGN | None = None,
) -> None:
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    p = tf.paragraphs[0]
    p.text = text
    if align is not None:
        p.alignment = align
    for run in p.runs:
        run.font.size = Pt(font_size)
        run.font.bold = bold


def _add_bullets(
    slide,
    items: list[Any],
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    font_size: int = 16,
    limit: int = 7,
) -> None:
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    bullets = [_clip(item, 180) for item in items[:limit] if str(item or "").strip()]
    if not bullets:
        bullets = ["Details will be confirmed during proposal review."]
    for i, item in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = item
        p.level = 0
        for run in p.runs:
            run.font.size = Pt(font_size)


def _add_title(slide, title: str) -> None:
    if not _set_placeholder_text(slide, 0, title):
        _add_textbox(slide, title, 0.65, 0.35, 12.0, 0.55, font_size=28, bold=True)


def _add_footer(slide, slide_no: int) -> None:
    _add_textbox(slide, str(slide_no), 12.25, 6.9, 0.45, 0.2, font_size=8, align=PP_ALIGN.RIGHT)


# --------------------------------------------------------------------------- #
# VIP visual primitives (deck_style="vip") — gradient backgrounds, cards with a
# soft shadow, eyebrow labels, and stat-number callouts. All are palette-driven so
# calling them under a non-"vip" preset degrades gracefully (flat fill, no shadow).
# --------------------------------------------------------------------------- #


def _add_gradient_background(slide, c1: RGBColor, c2: RGBColor, angle: float = 45.0) -> None:
    """Paint the WHOLE slide with a 2-stop linear gradient (hero cover/divider bg)."""
    fill = slide.background.fill
    fill.gradient()
    stops = fill.gradient_stops
    stops[0].color.rgb = c1
    stops[0].position = 0.0
    stops[-1].color.rgb = c2
    stops[-1].position = 1.0
    fill.gradient_angle = angle


def _add_soft_shadow(
    shape, *, blur_pt: float = 14.0, dist_pt: float = 5.0, color: str = "0B1A2F", alpha_pct: int = 28
) -> None:
    """Best-effort navy-tinted soft outer shadow via raw OOXML — python-pptx's public
    ShadowFormat API only exposes ``.inherit``, no way to configure blur/distance/color, so
    this injects ``<a:effectLst><a:outerShdw/></a:effectLst>`` directly into the shape's
    ``spPr``. Wrapped so a failure here NEVER blocks the render (same pattern as every other
    best-effort helper in this module)."""
    try:
        from pptx.oxml import parse_xml

        emu_blur = int(blur_pt * 12700)
        emu_dist = int(dist_pt * 12700)
        alpha_val = int(max(0, min(100, alpha_pct)) * 1000)
        xml = (
            '<a:effectLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            f'<a:outerShdw blurRad="{emu_blur}" dist="{emu_dist}" dir="5400000" rotWithShape="0">'
            f'<a:srgbClr val="{color}"><a:alpha val="{alpha_val}"/></a:srgbClr>'
            "</a:outerShdw></a:effectLst>"
        )
        shape._element.spPr.append(parse_xml(xml))  # noqa: SLF001 - no public spPr-effect API
    except Exception:  # noqa: BLE001 — a missing shadow must never break the deck
        pass


def _add_card(
    slide,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: RGBColor | None = None,
    radius: float = 0.08,
    shadow: bool | None = None,
):
    """A rounded-rectangle background card. Call BEFORE adding the text/table/image that
    sits on top of it (z-order follows shape-add order). ``shadow=None`` defers to the
    active preset's ``card_shadow`` flag; pass True/False to override per call."""
    from pptx.enum.shapes import MSO_SHAPE

    pal = _palette()
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    try:
        shape.adjustments[0] = radius
    except Exception:  # noqa: BLE001 — cosmetic only
        pass
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill if fill is not None else pal.get("light", BNK_WHITE)
    shape.line.fill.background()
    shape.shadow.inherit = False
    use_shadow = pal.get("card_shadow", False) if shadow is None else shadow
    if use_shadow:
        _add_soft_shadow(shape)
    return shape


def _add_eyebrow(slide, text: str, x: float, y: float, w: float, *, color: RGBColor | None = None) -> None:
    """A small, bold, uppercase label above a headline (the "SECTION" part of a title)."""
    pal = _palette()
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(0.32))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = str(text or "").upper()
    for run in p.runs:
        run.font.size = Pt(11)
        run.font.bold = True
        run.font.name = pal.get("font", BNK_FONT)
        run.font.color.rgb = color if color is not None else pal.get("cyan", BNK_ACCENT)


def _add_stat_block(
    slide,
    number_text: str,
    label_text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    color: RGBColor | None = None,
) -> None:
    """A big bold number with a small caption underneath (approximates the reference
    deck's gradient-text "stat" callouts — python-pptx has no public text-gradient API,
    so this uses a solid, bold, large accent-colored number instead)."""
    pal = _palette()
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.text = str(number_text)
    p.alignment = PP_ALIGN.CENTER
    for run in p.runs:
        run.font.size = Pt(32)
        run.font.bold = True
        run.font.name = pal.get("font", BNK_FONT)
        run.font.color.rgb = color if color is not None else pal.get("cyan", BNK_ACCENT)
    p2 = tf.add_paragraph()
    p2.text = str(label_text)
    p2.alignment = PP_ALIGN.CENTER
    for run in p2.runs:
        run.font.size = Pt(10)
        run.font.name = pal.get("font", BNK_FONT)
        run.font.color.rgb = pal.get("text", BNK_TEXT)


def _image_fit(slide, image_path: Path, x: float, y: float, w: float, h: float) -> None:
    from PIL import Image

    with Image.open(image_path) as img:
        iw, ih = img.size
    box_ratio = w / h
    img_ratio = iw / ih if ih else box_ratio
    if img_ratio > box_ratio:
        final_w = w
        final_h = w / img_ratio
    else:
        final_h = h
        final_w = h * img_ratio
    left = x + (w - final_w) / 2
    top = y + (h - final_h) / 2
    slide.shapes.add_picture(
        str(image_path), Inches(left), Inches(top), width=Inches(final_w), height=Inches(final_h)
    )


def _clone_slide(prs: Presentation, source_index: int):
    source = prs.slides[source_index]
    blank = _layout(prs, "Blank", "Empty")
    slide = prs.slides.add_slide(blank)
    for shape in source.shapes:
        slide.shapes._spTree.insert_element_before(deepcopy(shape.element), "p:extLst")  # noqa: SLF001
    return slide


def _section_slide(prs: Presentation, title: str, slide_no: int):
    slide = prs.slides.add_slide(_layout(prs, "Head Page", "Head-01"))
    _add_title(slide, title)
    _add_footer(slide, slide_no)
    return slide


def _detail_slide(prs: Presentation, title: str, bullets: list[Any], slide_no: int):
    slide = prs.slides.add_slide(_layout(prs, "Detail-01"))
    _add_title(slide, title)
    # Prefer the template's designed body placeholder; fall back to a positioned textbox.
    if not _fill_bullets_placeholder(slide, bullets):
        _add_bullets(slide, bullets, 0.85, 1.35, 11.6, 4.95)
    _add_footer(slide, slide_no)
    return slide


def _overview_slide(prs: Presentation, title: str, subtitle: str, slide_no: int):
    slide = prs.slides.add_slide(_layout(prs, "Overview-01"))
    _set_placeholder_text(slide, 0, title)
    _set_placeholder_text(slide, 1, subtitle)
    _add_footer(slide, slide_no)
    return slide


def _cover_slide(prs: Presentation, report: dict[str, Any], slide_no: int):
    slide = prs.slides.add_slide(_layout(prs, "Cover-01"))
    _set_placeholder_text(slide, 0, report["title"])
    _set_placeholder_text(slide, 1, report["subtitle"])
    date_text = dt.datetime.now().strftime("%B %d, %Y")
    _add_textbox(slide, date_text, 0.75, 6.45, 4.4, 0.3, font_size=13)
    if report.get("brand"):
        _add_textbox(slide, str(report["brand"]), 0.75, 5.95, 4.4, 0.3, font_size=12)
    _add_footer(slide, slide_no)
    return slide


def _diagram_slide(prs: Presentation, report: dict[str, Any], workspace: Path, slide_no: int):
    slide = prs.slides.add_slide(_layout(prs, "Blank", "Empty"))
    _add_title(slide, report["blueprint"].get("diagram_title") or "Application Architecture")
    diagram = workspace / "out.body.png"
    if not diagram.exists():
        diagram = workspace / "out.png"
    if diagram.exists():
        _image_fit(slide, diagram, 0.55, 1.05, 12.15, 5.55)
    else:
        _add_textbox(slide, "No diagram image is available.", 1.0, 2.8, 11.0, 0.4, font_size=16)
    _add_footer(slide, slide_no)
    return slide


# --------------------------------------------------------------------------- #
# Native (editable) brand-styled tables and the BnK-specific slide builders.
# --------------------------------------------------------------------------- #

_CONTENT_X = 0.6
_CONTENT_Y = 1.35
_CONTENT_W = 12.1
_CONTENT_H = 5.35


def _style_cell(
    cell, text: str, *, fill: RGBColor, color: RGBColor, bold: bool, size: int, align=PP_ALIGN.LEFT
) -> None:
    cell.fill.solid()
    cell.fill.fore_color.rgb = fill
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    cell.margin_left = Inches(0.08)
    cell.margin_right = Inches(0.08)
    cell.margin_top = Inches(0.03)
    cell.margin_bottom = Inches(0.03)
    tf = cell.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = align
    p.text = _clip(text, 240)
    for run in p.runs:
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.name = BNK_FONT
        run.font.color.rgb = color


def _add_table(
    slide,
    headers: list[str],
    rows: list[list[Any]],
    *,
    x: float = _CONTENT_X,
    y: float = _CONTENT_Y,
    w: float = _CONTENT_W,
    h: float = _CONTENT_H,
    col_widths: list[float] | None = None,
    header_size: int = 13,
    body_size: int = 11,
    max_rows: int = 12,
):
    """Add a brand-styled, editable table. Header row = BnK blue; alternate body tint."""
    rows = [r for r in rows if any(str(c or "").strip() for c in r)][:max_rows]
    if not rows:
        rows = [["—"] * len(headers)]
    n_rows = len(rows) + 1
    n_cols = len(headers)
    gfx = slide.shapes.add_table(n_rows, n_cols, Inches(x), Inches(y), Inches(w), Inches(h))
    table = gfx.table
    table.first_row = False  # disable theme banding; we colour manually
    table.horz_banding = False
    if col_widths and len(col_widths) == n_cols:
        for i, cw in enumerate(col_widths):
            table.columns[i].width = Inches(cw)
    pal = _palette()
    for c, head in enumerate(headers):
        _style_cell(table.cell(0, c), str(head), fill=pal["blue"], color=BNK_WHITE, bold=True, size=header_size)
    for r, row in enumerate(rows, start=1):
        fill = pal["light"] if r % 2 == 0 else BNK_WHITE
        for c in range(n_cols):
            value = row[c] if c < len(row) else ""
            _style_cell(table.cell(r, c), str(value), fill=fill, color=BNK_TEXT, bold=False, size=body_size)
    return table


def _table_slide(prs: Presentation, title: str, headers, rows, slide_no: int, **kw):
    """A Detail-01 slide whose content area holds a brand-styled table."""
    slide = prs.slides.add_slide(_layout(prs, "Detail-01"))
    _add_title(slide, title)
    _add_table(slide, headers, rows, **kw)
    _add_footer(slide, slide_no)
    return slide


# Top-level tech_stack scalar keys that _tech_items may surface as bogus "layers".
_TECH_META_KEYS = frozenset(
    {
        "estimated_total_monthly_cost_usd",
        "assumptions",
        "scaling_roadmap",
        "notes",
        "summary",
    }
)


def _icon_plan_lookup(workspace: Path) -> dict[str, str]:
    """{normalized_key: absolute_icon_path} from icon_plan.json — the diagram's ALREADY
    resolved icons (see tools.rendering_tools._bake_icon_plan). Reusing this for the
    tech-stack slide keeps its logos visually consistent with the diagram's and skips a
    second icon search entirely (explicit product direction: tech-stack icons must come
    from the diagram step, never a fresh resolve — resolve_tech_stack_icons/tech_icons.json
    is only a fallback for when no diagram has been rendered yet)."""
    path = workspace / "icon_plan.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}

    from backends import LOCAL_ICONS

    root = Path(LOCAL_ICONS)

    def _abs(rel_or_abs: str) -> str:
        p = Path(rel_or_abs)
        return str(p if p.is_absolute() else root / p)

    def _key(s: object) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())

    out: dict[str, str] = {}
    if isinstance(raw, dict):  # {node_id: [rel_paths]} — blueprint.py pre-seed shape
        for k, v in raw.items():
            rel = v[0] if isinstance(v, list) and v else v if isinstance(v, str) else None
            if rel and _key(k):
                out[_key(k)] = _abs(rel)
    elif isinstance(raw, list):  # icon_resolver subagent's fuller {label,id,path,status} shape
        for entry in raw:
            if not isinstance(entry, dict) or entry.get("status") == "NOT_FOUND":
                continue
            # Prefer the portable `icon` field over `path`, which icon_resolver writes as a
            # container-absolute path (mirrors _bake_icon_plan's own preference exactly).
            rel = entry.get("icon") or entry.get("path")
            if not rel:
                continue
            for key in (entry.get("id"), entry.get("label"), entry.get("name")):
                if key and _key(key):
                    out[_key(key)] = _abs(rel)
    return out


def _tech_icons_from_icon_plan(workspace: Path, tech_items: list[dict]) -> dict[str, list[dict]]:
    """tech_icons.json-shaped ``{layer: [{name, path}, ...]}``, sourced from the diagram's
    icon_plan.json instead of a fresh icon search. Only includes a layer when at least one
    of its technologies actually matched an already-resolved icon."""
    lookup = _icon_plan_lookup(workspace)
    if not lookup:
        return {}

    def _key(s: object) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())

    result: dict[str, list[dict]] = {}
    for item in tech_items:
        layer = item.get("layer") or "Layer"
        if str(layer).strip().lower() in _TECH_META_KEYS:
            continue
        names = [n.strip() for n in str(item.get("choice") or "").split(",") if n.strip()]
        icons = [{"name": n, "path": lookup[_key(n)]} for n in names if _key(n) in lookup]
        if icons:
            result[layer] = icons
    return result


def _tech_stack_table_slide(
    prs: Presentation,
    report: dict[str, Any],
    slide_no: int,
    title: str = "PROPOSED SOLUTION | Technical Stack",
    workspace: Path | None = None,
):
    # Prefer reusing the diagram's already-resolved icons (icon_plan.json); fall back to
    # a logo-per-technology layout from a fresh resolve_tech_stack_icons run when no
    # diagram has been rendered yet; plain table as the last resort.
    if workspace is not None:
        reused_icons = _tech_icons_from_icon_plan(workspace, report.get("tech_items") or [])
        if reused_icons:
            return _tech_stack_icon_slide(prs, reused_icons, slide_no, title)
        tech_icons = read_json_file(workspace / "tech_icons.json", {})
        if isinstance(tech_icons, dict) and any(tech_icons.values()):
            return _tech_stack_icon_slide(prs, tech_icons, slide_no, title)
    rows = []
    for item in report.get("tech_items", [])[:12]:
        layer = item.get("layer") or "Layer"
        if str(layer).strip().lower() in _TECH_META_KEYS:
            continue
        choice = item.get("choice") or item.get("name") or "TBD"
        rationale = _clip(item.get("rationale") or "", 140)
        rows.append([layer, choice, rationale])
    if not rows:
        rows = [["Frontend", "TBD", ""], ["Backend", "TBD", ""], ["Database", "TBD", ""]]
    return _table_slide(
        prs,
        title,
        ["Layer", "Technology", "Description"],
        rows,
        slide_no,
        col_widths=[2.4, 3.2, 6.5],
    )


def _tech_stack_icon_slide(
    prs: Presentation, tech_icons: dict, slide_no: int, title: str = "PROPOSED SOLUTION | Technical Stack"
):
    """Technical Stack slide with a logo per technology, grouped by layer.

    ``tech_icons`` is the tech_icons.json produced by resolve_tech_stack_icons:
    ``{layer: [{name, path, icon, source}, ...]}``.
    """
    slide = prs.slides.add_slide(_layout(prs, "Detail-01"))
    _add_title(slide, title)
    layers = [(lyr, icons) for lyr, icons in tech_icons.items() if icons]
    if not layers:
        _add_textbox(slide, "Technical stack not yet available.", 0.85, 1.6, 11.0, 0.4, font_size=14)
        _add_footer(slide, slide_no)
        return slide

    y = 1.25
    row_h = min(0.62, (6.6 - 1.25) / max(1, len(layers)))
    icon_sz = min(0.34, row_h - 0.16)
    for layer, icons in layers:
        box = slide.shapes.add_textbox(Inches(0.55), Inches(y), Inches(2.5), Inches(row_h))
        tf = box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = str(layer)
        for r in p.runs:
            r.font.size = Pt(11)
            r.font.bold = True
            r.font.name = BNK_FONT
            r.font.color.rgb = _palette()["blue"]
        x = 3.15
        for it in icons:
            if x > 12.6:
                break
            path = it.get("path")
            if path and Path(path).exists():
                try:
                    slide.shapes.add_picture(
                        path, Inches(x), Inches(y + (row_h - icon_sz) / 2), height=Inches(icon_sz)
                    )
                except Exception:  # noqa: BLE001
                    pass
            lbl = slide.shapes.add_textbox(Inches(x), Inches(y + row_h - 0.2), Inches(1.4), Inches(0.2))
            lp = lbl.text_frame.paragraphs[0]
            lp.text = str(it.get("name", ""))[:16]
            for r in lp.runs:
                r.font.size = Pt(6.5)
                r.font.name = BNK_FONT
                r.font.color.rgb = BNK_TEXT
            x += 1.5
        y += row_h
    _add_footer(slide, slide_no)
    return slide


def _functional_nfr_slide(
    prs: Presentation, report: dict[str, Any], slide_no: int, title: str = "PROPOSED SOLUTION | Requirements"
):
    brief = report.get("brief") or {}
    func = _as_list(brief.get("functional_requirements"))[:8]
    nfr = _as_list(brief.get("non_functional_requirements"))[:8]
    slide = prs.slides.add_slide(_layout(prs, "Detail-01"))
    _add_title(slide, title)
    half_w = (_CONTENT_W - 0.4) / 2
    _add_table(
        slide,
        ["Functional Requirements"],
        [[r] for r in func] or [["To be confirmed"]],
        x=_CONTENT_X,
        y=_CONTENT_Y,
        w=half_w,
        h=_CONTENT_H,
        header_size=13,
        body_size=11,
    )
    _add_table(
        slide,
        ["Non-Functional Requirements"],
        [[r] for r in nfr] or [["To be confirmed"]],
        x=_CONTENT_X + half_w + 0.4,
        y=_CONTENT_Y,
        w=half_w,
        h=_CONTENT_H,
        header_size=13,
        body_size=11,
    )
    _add_footer(slide, slide_no)
    return slide


_SDLC_DEFAULT = [
    ("Analysis", "Collect & validate requirements with client; wireframing", "BRD, Wireframes"),
    ("Design", "System architecture and UI/UX design", "System Design, UI/UX"),
    ("Development", "Implementation in agile sprints", "Source Code"),
    ("Testing", "Manual QC, SIT & UAT support, load & security test", "Test Report"),
    ("Deployment", "Deploy to DEV / UAT / PROD environments", "Deployment Guide"),
    ("Maintenance", "Post go-live support to fix defects", "Support"),
]


def _sdlc_scope_slide(
    prs: Presentation,
    report: dict[str, Any],
    workspace: Path,
    slide_no: int,
    title: str = "SCOPE OF WORK | SDLC Phases",
):
    rows = [[p, d, dl] for (p, d, dl) in _SDLC_DEFAULT]
    return _table_slide(
        prs,
        title,
        ["Phase", "Activities", "Deliverables"],
        rows,
        slide_no,
        col_widths=[2.2, 6.4, 3.5],
    )


def _add_donut_chart(
    slide, data: dict[str, float], x: float, y: float, w: float, h: float, chart_title: str = ""
):
    """A native (editable) python-pptx donut chart — e.g. effort MD by role."""
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION

    items = [(k, float(v)) for k, v in data.items() if v]
    if not items:
        return None
    chart_data = CategoryChartData()
    chart_data.categories = [k for k, _ in items]
    chart_data.add_series("MD", [v for _, v in items])
    gframe = slide.shapes.add_chart(
        XL_CHART_TYPE.DOUGHNUT, Inches(x), Inches(y), Inches(w), Inches(h), chart_data
    )
    chart = gframe.chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.RIGHT
    chart.legend.include_in_layout = False
    chart.legend.font.size = Pt(9)
    chart.has_title = bool(chart_title)
    if chart_title:
        chart.chart_title.text_frame.text = chart_title
    return chart


def _add_bar_chart(
    slide, categories: list[str], values: list[float], x: float, y: float, w: float, h: float, chart_title: str = ""
):
    """A native (editable) python-pptx clustered-column chart — e.g. cost USD by module."""
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE

    pairs = [(c, float(v)) for c, v in zip(categories, values) if v]
    if not pairs:
        return None
    chart_data = CategoryChartData()
    chart_data.categories = [_clip(c, 24) for c, _ in pairs]
    chart_data.add_series("USD", [v for _, v in pairs])
    gframe = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(x), Inches(y), Inches(w), Inches(h), chart_data
    )
    chart = gframe.chart
    chart.has_legend = False
    chart.has_title = bool(chart_title)
    if chart_title:
        chart.chart_title.text_frame.text = chart_title
    plot = chart.plots[0]
    plot.has_data_labels = False
    return chart


def _delivery_effort_slide(
    prs: Presentation, workspace: Path, slide_no: int, title: str = "PROJECT DELIVERY | Estimated Effort"
):
    wbs = read_json_file(workspace / "wbs.json", {})
    headers = ["Code", "Module", "Effort (MD)"]
    rows: list[list[Any]] = []
    effort_by_role: dict[str, float] = {}
    if isinstance(wbs, dict) and wbs:
        for mod in _as_list(wbs.get("effort_by_module"))[:10]:
            if isinstance(mod, dict):
                rows.append([mod.get("code", ""), mod.get("name", "Module"), mod.get("total_md", 0)])
        totals = wbs.get("effort_totals") or {}
        if totals:
            rows.append(["", "TOTAL", totals.get("total_mandays", 0)])
            effort_by_role = totals.get("effort_by_role") or {}
    if not rows:
        rows = [["", "Effort will be finalized after WBS approval.", ""]]

    if not effort_by_role:
        return _table_slide(prs, title, headers, rows, slide_no, col_widths=[1.6, 7.5, 3.0])

    # A donut of effort-by-role fits alongside the module table — table takes the left
    # ~58%, chart the remaining right column (mirrors the WS2 case-study two-column shape).
    slide = prs.slides.add_slide(_layout(prs, "Detail-01"))
    _add_title(slide, title)
    table_w = _CONTENT_W * 0.56
    _add_table(slide, headers, rows, x=_CONTENT_X, y=_CONTENT_Y, w=table_w, h=_CONTENT_H)
    chart_x = _CONTENT_X + table_w + 0.3
    _add_donut_chart(
        slide, effort_by_role, chart_x, _CONTENT_Y, _CONTENT_W - table_w - 0.3, _CONTENT_H, "Effort by Role (MD)"
    )
    _add_footer(slide, slide_no)
    return slide


def _pricing_slide(prs: Presentation, report: dict[str, Any], slide_no: int, title: str = "PRICING | CAPEX"):
    # Prefer WBS-derived CAPEX (per-module USD from the rate card) when available — a real
    # priced quote instead of a list of components with "—" amounts.
    capex_rows = report.get("capex_rows")
    if capex_rows:
        rows: list[list[Any]] = [[r["module"], f"${int(r['cost']):,}"] for r in capex_rows[:12]]
        total = report.get("capex_total") or sum(r["cost"] for r in capex_rows)
        rows.append(["Total (NET, excluding taxes/VAT)", f"${int(total):,}"])
        if len(capex_rows) < 2:
            return _table_slide(prs, title, ["Module", "Cost (USD)"], rows, slide_no, col_widths=[8.5, 3.6])
        # A bar-by-module chart only makes sense with >=2 modules to compare.
        slide = prs.slides.add_slide(_layout(prs, "Detail-01"))
        _add_title(slide, title)
        table_w = _CONTENT_W * 0.56
        _add_table(
            slide, ["Module", "Cost (USD)"], rows, x=_CONTENT_X, y=_CONTENT_Y, w=table_w, h=_CONTENT_H
        )
        chart_x = _CONTENT_X + table_w + 0.3
        _add_bar_chart(
            slide,
            [r["module"] for r in capex_rows[:8]],
            [r["cost"] for r in capex_rows[:8]],
            chart_x,
            _CONTENT_Y,
            _CONTENT_W - table_w - 0.3,
            _CONTENT_H,
            "Cost by Module (USD)",
        )
        _add_footer(slide, slide_no)
        return slide
    total = report.get("tech_total_cost")
    rows = []
    for item in report.get("tech_items", [])[:8]:
        layer = item.get("layer") or "Item"
        if str(layer).strip().lower() in _TECH_META_KEYS:
            continue
        choice = item.get("choice") or item.get("name") or ""
        rows.append([f"{layer}: {choice}".strip(": "), "—"])
    rows.append(["Total (NET, excluding taxes/VAT)", f"{total} USD" if total else "XXX USD"])
    return _table_slide(
        prs,
        title,
        ["Cost Item", "Amount"],
        rows,
        slide_no,
        col_widths=[8.5, 3.6],
    )


_DEFAULT_MILESTONES = [
    ("1", "Contract sign-off / Analysis complete", "30%"),
    ("2", "Completion of Development", "30%"),
    ("3", "Completion of UAT", "30%"),
    ("4", "Completion of Nursing Period", "10%"),
]


def _payment_milestones_slide(
    prs: Presentation,
    workspace: Path,
    slide_no: int,
    title: str = "PRICING | Payment Milestones",
):
    """Payment milestones — real names from wbs.json when the WBS states them, always
    paired with the standard BnK invoicing split (30/30/30/10 for the usual 4-milestone
    shape; evenly split otherwise). Falls back to the fully-generic template when the WBS
    has no milestones on file — this was previously ALWAYS the generic template, ignoring
    a real wbs.milestones list entirely."""
    wbs = read_json_file(workspace / "wbs.json", {})
    names = [m.get("name") for m in _as_list(wbs.get("milestones")) if isinstance(m, dict) and m.get("name")]
    if names and len(names) == len(_DEFAULT_MILESTONES):
        rows = [[str(i + 1), name, pct] for i, (name, (_, _, pct)) in enumerate(zip(names, _DEFAULT_MILESTONES))]
    elif names:
        base = 100 // len(names)
        pcts = [base] * len(names)
        pcts[-1] += 100 - base * len(names)
        rows = [[str(i + 1), name, f"{pct}%"] for i, (name, pct) in enumerate(zip(names, pcts))]
    else:
        rows = [[n, name, pct] for (n, name, pct) in _DEFAULT_MILESTONES]
    return _table_slide(
        prs,
        title,
        ["#", "Milestone", "Payment"],
        rows,
        slide_no,
        col_widths=[1.0, 8.6, 2.5],
    )


def _gantt_slide(
    prs: Presentation,
    params: dict[str, Any],
    slide_no: int,
    title: str = "PROJECT DELIVERY | Master Plan & Milestones",
):
    """The Master Plan Gantt — same schedule as the WBS Excel '3. Delivery Plan' sheet
    (deck_resolver._b_master_plan calls wbs_excel._module_schedule so the two never drift).

    Column granularity adapts to project length so the grid stays legible on a 13.3" slide:
    weekly for short projects, sprint-grouped, then monthly for long ones — mirroring how
    the Excel sheet groups Month > Sprint > Week headers, just collapsed to one row.
    """
    weeks = int(params.get("weeks") or 0)
    months = int(params.get("months") or 0)
    sprints = int(params.get("sprints") or 0)
    rows = params.get("gantt_rows") or []

    if weeks <= 20 and weeks:
        n_cols, weeks_per_col, label = weeks, 1, lambda i: f"W{i + 1}"
    elif weeks <= 40 and sprints:
        n_cols, weeks_per_col, label = sprints, 2, lambda i: f"S{i + 1}"
    else:
        n_cols, weeks_per_col, label = (months or 1), 4, lambda i: f"M{i + 1}"

    slide = prs.slides.add_slide(_layout(prs, "Detail-01"))
    _add_title(slide, title)
    if not rows or not n_cols:
        _add_textbox(slide, "Delivery timeline not yet available.", 0.85, 1.6, 11.0, 0.4, font_size=14)
        _add_footer(slide, slide_no)
        return slide

    name_w = 3.0
    grid_w = _CONTENT_W - name_w
    col_w = grid_w / n_cols
    n_rows = min(len(rows), 16) + 1
    gfx = slide.shapes.add_table(
        n_rows, n_cols + 1, Inches(_CONTENT_X), Inches(_CONTENT_Y), Inches(_CONTENT_W), Inches(_CONTENT_H)
    )
    table = gfx.table
    table.first_row = False
    table.horz_banding = False
    table.columns[0].width = Inches(name_w)
    for i in range(n_cols):
        table.columns[i + 1].width = Inches(col_w)

    pal = _palette()
    _style_cell(table.cell(0, 0), "Module", fill=pal["blue"], color=BNK_WHITE, bold=True, size=10)
    for i in range(n_cols):
        _style_cell(
            table.cell(0, i + 1),
            label(i),
            fill=pal["blue"],
            color=BNK_WHITE,
            bold=True,
            size=7,
            align=PP_ALIGN.CENTER,
        )

    for r, m in enumerate(rows[:16], start=1):
        _style_cell(
            table.cell(r, 0),
            f"{m.get('code', '')} {m.get('name', '')}".strip(),
            fill=BNK_WHITE,
            color=BNK_TEXT,
            bold=False,
            size=9,
        )
        start_col = max(0, (int(m.get("start_week", 1)) - 1) // weeks_per_col)
        end_col = min(n_cols - 1, (int(m.get("end_week", 1)) - 1) // weeks_per_col)
        for i in range(n_cols):
            active = start_col <= i <= end_col
            _style_cell(
                table.cell(r, i + 1),
                "",
                fill=pal["cyan"] if active else BNK_WHITE,
                color=BNK_WHITE,
                bold=False,
                size=1,
            )

    _add_footer(slide, slide_no)
    return slide


def _wbs_sheet_image_path(workspace: Path, kind: str) -> Path | None:
    """Resolve ``wbs_sheet_images.json``'s ``kind`` entry ("effort"/"wbs"/"delivery") to an
    existing PNG path, or None — the "prefer the LibreOffice screenshot over the native
    table" check every WBS-derived slide below shares (mirrors the existing tech_icons.json
    "prefer icon grid over table" pattern in _tech_stack_table_slide)."""
    manifest = read_json_file(workspace / "wbs_sheet_images.json", {})
    if not isinstance(manifest, dict):
        return None
    ref = manifest.get(kind)
    if not ref:
        return None
    p = Path(ref)
    p = p if p.is_absolute() else workspace / p
    return p if p.exists() else None


def _wbs_sheet_image_slide(prs: Presentation, image_path: Path, slide_no: int, title: str):
    """A full-bleed embed of one rendered wbs_filled.xlsx sheet (the real, brand-styled,
    client-facing Excel look — see wbs_excel_render.py)."""
    slide = prs.slides.add_slide(_layout(prs, "Blank", "Empty"))
    _add_title(slide, title)
    _image_fit(slide, image_path, 0.55, 1.05, 12.15, 5.55)
    _add_footer(slide, slide_no)
    return slide


def _diagram_image_slide(prs: Presentation, params: dict[str, Any], workspace: Path, slide_no: int, title: str):
    """A finalized non-architecture diagram (sequence/erd/state_machine/process) from
    diagram_manifest.json — see deck_resolver._b_additional_diagrams / tools.rendering_tools.
    finalize_diagram(kind=...)."""
    slide = prs.slides.add_slide(_layout(prs, "Blank", "Empty"))
    _add_title(slide, title)
    ref = params.get("image_ref")
    path = Path(ref) if ref else None
    if path is not None and not path.is_absolute():
        path = workspace / path
    if path is not None and path.exists():
        _image_fit(slide, path, 0.55, 1.05, 12.15, 5.55)
    else:
        _add_textbox(slide, "Diagram image not available.", 1.0, 2.8, 11.0, 0.4, font_size=16)
    _add_footer(slide, slide_no)
    return slide


_CLIENT_TEAM_DEFAULT = ["Technical Lead", "Business Analyst", "Project Manager"]
_BNK_TEAM_DEFAULT = ["Technical Lead", "Developer(s)", "BA / Tester", "Project Manager"]


def _team_slide(
    prs: Presentation,
    workspace: Path,
    slide_no: int,
    title: str = "PROJECT DELIVERY | Team Structure",
):
    """BnK-side roles from the real wbs.json team_composition (role + real MD/headcount)
    when available; the client-side column has no WBS-derivable source so it keeps the
    standard template roles. Previously ALWAYS the fully-generic template on both sides,
    even when wbs.json had a real team_composition on file."""
    wbs = read_json_file(workspace / "wbs.json", {})
    bnk_rows: list[str] = []
    for m in _as_list(wbs.get("team_composition")) if isinstance(wbs, dict) else []:
        if not isinstance(m, dict):
            continue
        md, hc = m.get("total_md"), m.get("est_headcount")
        if md:
            bnk_rows.append(f"{m.get('role', 'Role')}: {md} MD" + (f" (~{hc} HC)" if hc else ""))
    bnk_rows = bnk_rows or list(_BNK_TEAM_DEFAULT)
    client_rows = list(_CLIENT_TEAM_DEFAULT)
    n = max(len(client_rows), len(bnk_rows))
    rows = [
        [client_rows[i] if i < len(client_rows) else "", bnk_rows[i] if i < len(bnk_rows) else ""]
        for i in range(n)
    ]
    return _table_slide(
        prs,
        title,
        ["Client Team", "BnK Delivery Team"],
        rows,
        slide_no,
        col_widths=[6.0, 6.1],
    )


def _resolve_asset_path(ref: str | None) -> Path | None:
    """A ``solution_memory.json`` ``image_ref`` (e.g. 'DATA/SLIDE_IMAGES/.../slide_007.png')
    is repo-root-relative; resolve it against the repo root so it can be embedded regardless
    of the current workspace's location."""
    if not ref:
        return None
    p = Path(ref)
    return p if p.is_absolute() else _repo_root() / p


def _case_study_slide(
    prs: Presentation,
    params: dict[str, Any],
    slide_no: int,
    title: str = "SUCCESS STORY",
):
    """One reference past project — text (client/context/outcome/tech/effort) beside an
    optional screenshot (``image_ref``). ``params`` is a SINGLE case's dict, as shaped by
    ``deck_resolver._case_to_params`` (a "Success Story" section emits one of these slides
    per top-k picked project — see ``deck._build_deck_plan_registry``)."""
    slide = prs.slides.add_slide(_layout(prs, "Detail-01"))
    _add_title(slide, title)

    bullets: list[str] = []
    if params.get("client"):
        bullets.append(f"Client: {params['client']}")
    if params.get("context_paragraph"):
        bullets.append(params["context_paragraph"])
    if params.get("outcome"):
        bullets.append(f"Outcome: {params['outcome']}")
    if params.get("tech"):
        bullets.append("Tech: " + ", ".join(params["tech"][:8]))
    if params.get("effort_md"):
        bullets.append(f"Reference effort: {params['effort_md']} MD (past project, not this quote)")

    image_path = _resolve_asset_path(params.get("image_ref"))
    if image_path and image_path.exists():
        _add_bullets(slide, bullets, 0.6, 1.3, 6.5, 5.3, font_size=13)
        try:
            _image_fit(slide, image_path, 7.35, 1.3, 5.35, 5.3)
        except Exception:  # noqa: BLE001 — a broken/unreadable image must not break the deck
            pass
    elif not _fill_bullets_placeholder(slide, bullets):
        _add_bullets(slide, bullets, 0.85, 1.35, 11.6, 4.95)

    _add_footer(slide, slide_no)
    return slide


def _tech_bullets(report: dict[str, Any]) -> list[str]:
    items = []
    for item in report.get("tech_items", [])[:8]:
        layer = item.get("layer") or "Layer"
        choice = item.get("choice") or item.get("name") or "TBD"
        rationale = item.get("rationale") or ""
        items.append(f"{layer}: {choice}" + (f" - {_clip(rationale, 100)}" if rationale else ""))
    return items


def _delivery_bullets(workspace: Path) -> list[str]:
    wbs = read_json_file(workspace / "wbs.json", {})
    if not isinstance(wbs, dict) or not wbs:
        return [
            "Delivery plan will be finalized after WBS approval.",
            "Recommended phases: discovery, solution design, implementation, testing, UAT, launch support.",
        ]
    totals = wbs.get("effort_totals") or {}
    timeline = wbs.get("timeline") or {}
    bullets = [
        f"Total effort: {totals.get('total_mandays', 0)} MD / {totals.get('total_manmonths', 0)} MM.",
        f"Timeline: {timeline.get('weeks', 0)} weeks / {timeline.get('months', 0)} months.",
    ]
    for module in _as_list(wbs.get("effort_by_module"))[:5]:
        if isinstance(module, dict):
            bullets.append(
                f"{module.get('code', '')} {module.get('name', 'Module')}: {module.get('total_md', 0)} MD."
            )
    return bullets


def _build_outline_context(report: dict[str, Any], workspace: Path) -> str:
    """Serialize report data to compact plain-text for the LLM outline prompt."""
    lines: list[str] = []

    lines.append(f"TITLE: {_clip(report.get('title', ''), 120)}")
    lines.append(f"SUBTITLE: {_clip(report.get('subtitle', ''), 120)}")
    lines.append(f"BRAND: {_clip(report.get('brand', ''), 80)}")

    brief = report.get("brief") or {}
    lines.append(f"\nOBJECTIVE: {_clip(brief.get('objective', ''), 300)}")
    stakeholders = _as_list(brief.get("stakeholders"))[:5]
    if stakeholders:
        lines.append(f"STAKEHOLDERS: {', '.join(_clip(str(s), 60) for s in stakeholders)}")

    func_reqs = _as_list(brief.get("functional_requirements"))[:8]
    if func_reqs:
        lines.append("\nFUNCTIONAL_REQUIREMENTS:")
        for r in func_reqs:
            lines.append(f"  - {_clip(r, 200)}")

    nfr = _as_list(brief.get("non_functional_requirements"))[:5]
    if nfr:
        lines.append("\nNON_FUNCTIONAL_REQUIREMENTS:")
        for r in nfr:
            lines.append(f"  - {_clip(r, 200)}")

    blueprint = report.get("blueprint") or {}
    if blueprint.get("pattern"):
        lines.append(f"\nARCHITECTURE_PATTERN: {_clip(blueprint['pattern'], 120)}")
    if report.get("pattern_rationale"):
        lines.append(f"PATTERN_RATIONALE: {_clip(report['pattern_rationale'], 200)}")

    decisions = _as_list(blueprint.get("key_decisions"))[:6]
    if decisions:
        lines.append("\nKEY_DECISIONS:")
        for d in decisions:
            lines.append(f"  - {_clip(d, 200)}")

    tech_items = report.get("tech_items") or []
    if tech_items:
        lines.append("\nTECH_STACK:")
        for item in tech_items[:10]:
            layer = item.get("layer") or "Layer"
            choice = item.get("choice") or item.get("name") or "TBD"
            rationale = _clip(item.get("rationale") or "", 80)
            lines.append(f"  - {layer}: {choice}" + (f" ({rationale})" if rationale else ""))

    exec_pts = _as_list(report.get("executive_points"))[:5]
    if exec_pts:
        lines.append("\nEXECUTIVE_POINTS:")
        for p in exec_pts:
            lines.append(f"  - {_clip(p, 200)}")

    if report.get("business_value"):
        lines.append(f"\nBUSINESS_VALUE: {_clip(report['business_value'], 250)}")
    if report.get("technical_value"):
        lines.append(f"TECHNICAL_VALUE: {_clip(report['technical_value'], 250)}")

    risks = [r for r in _as_list(report.get("risks")) if isinstance(r, dict)][:5]
    if risks:
        lines.append("\nRISKS:")
        for r in risks:
            lines.append(
                f"  - {r.get('type', 'Risk')}: {_clip(r.get('detail', ''), 150)}"
                f" → {_clip(r.get('recommendation', ''), 100)}"
            )

    wbs = read_json_file(workspace / "wbs.json", {})
    if isinstance(wbs, dict) and wbs:
        totals = wbs.get("effort_totals") or {}
        timeline = wbs.get("timeline") or {}
        lines.append("\nWBS_SUMMARY:")
        lines.append(f"  Total: {totals.get('total_mandays', 0)} MD / {totals.get('total_manmonths', 0)} MM")
        lines.append(f"  Timeline: {timeline.get('weeks', 0)} weeks / {timeline.get('months', 0)} months")
        for mod in _as_list(wbs.get("effort_by_module"))[:6]:
            if isinstance(mod, dict):
                lines.append(
                    f"  - {mod.get('code', '')} {mod.get('name', 'Module')}: {mod.get('total_md', 0)} MD"
                )
    else:
        lines.append("\nWBS_SUMMARY: Not yet available.")

    has_diagram = (workspace / "out.body.png").exists() or (workspace / "out.png").exists()
    lines.append(f"\nHAS_ARCHITECTURE_DIAGRAM: {'yes' if has_diagram else 'no'}")

    return "\n".join(lines)


def _parse_outline(raw_text: str) -> list[dict[str, Any]] | None:
    """Parse LLM output into a validated pagecontent list. Returns None on any failure."""
    text = raw_text.strip()

    def _try(s: str) -> list | None:
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, list) else None
        except (json.JSONDecodeError, ValueError):
            return None

    result = (
        _try(text)
        or (lambda m: _try(m.group(1)) if m else None)(re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text))
        or (
            (lambda s, e: _try(text[s : e + 1]) if s != -1 and e > s else None)(
                text.find("["), text.rfind("]")
            )
        )
    )

    if not isinstance(result, list):
        return None

    valid: list[dict[str, Any]] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        layout = str(item.get("layout") or "Detail-01")
        if layout not in VALID_LAYOUTS:
            layout = "Detail-01"
        bullets = [_clip(b, 200) for b in _as_list(item.get("bullets") or [])[:7] if str(b or "").strip()]
        block = str(item.get("block") or "bullets")
        if block not in VALID_BLOCKS:
            block = "bullets"
        valid.append(
            {
                "title": _clip(str(item.get("title") or ""), 80),
                "layout": layout,
                "block": block,
                "bullets": bullets,
                "asset_ref": item.get("asset_ref") or None,
            }
        )

    return valid if len(valid) >= 5 else None


def _generate_slide_outline(
    report: dict[str, Any],
    workspace: Path,
    sections: list[str],
) -> list[dict[str, Any]] | None:
    """Call LLM to generate a pagecontent slide outline. Returns None on any failure."""
    try:
        from config import get_model, make_llm
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError:
        return None

    try:
        model = get_model("ppt_outline", fallback=get_model("main", "mimo-v2.5"))
        llm = make_llm(model)
    except Exception:
        return None

    context = _build_outline_context(report, workspace)
    sections_note = (
        ""
        if set(sections) == set(DEFAULT_PPT_SECTIONS)
        else (f"\nNOTE: Only include slides relevant to these sections: " + ", ".join(sections) + ".")
    )
    user_msg = (
        f"Here is the project data for the proposal:\n\n{context}{sections_note}\n\n"
        "Generate the slide outline now. Return ONLY the JSON array."
    )

    try:
        response = llm.invoke([SystemMessage(content=_OUTLINE_SYSTEM_PROMPT), HumanMessage(content=user_msg)])
        raw = response.content if hasattr(response, "content") else str(response)
        return _parse_outline(raw)
    except Exception:
        return None


def _render_slide(
    prs: Presentation,
    spec: dict[str, Any],
    report: dict[str, Any],
    workspace: Path,
    slide_no: int,
) -> None:
    """Dispatch one slide spec to the appropriate slide builder."""
    layout = spec.get("layout", "Detail-01")
    title = spec.get("title") or ""
    bullets = spec.get("bullets") or []
    asset_ref = spec.get("asset_ref")
    block = spec.get("block") or "bullets"

    # Structured content blocks take precedence over the plain layout dispatch.
    if block != "bullets":
        _render_block(prs, block, title, report, workspace, slide_no, spec=spec)
        return

    if layout == "Cover-01":
        _cover_slide(prs, report, slide_no)
    elif layout == "Head Page":
        slide = prs.slides.add_slide(_layout(prs, "Head Page"))
        _add_title(slide, title)
        _add_footer(slide, slide_no)
    elif layout == "Head-01":
        slide = prs.slides.add_slide(_layout(prs, "Head-01"))
        _add_title(slide, title)
        _add_footer(slide, slide_no)
    elif layout == "Detail-01":
        _detail_slide(prs, title, bullets, slide_no)
    elif layout == "Overview-01":
        _overview_slide(prs, title, bullets[0] if bullets else "", slide_no)
    elif layout == "Empty":
        if asset_ref == "architecture_diagram":
            _diagram_slide(prs, report, workspace, slide_no)
        else:
            slide = prs.slides.add_slide(_layout(prs, "Empty", "Blank"))
            if title:
                _add_title(slide, title)
            _add_footer(slide, slide_no)
    elif layout in CLOSING_LAYOUTS:
        pass  # Closing slides are always appended via _append_thank_you after the loop.
    else:
        _detail_slide(prs, title, bullets, slide_no)


def _render_block(
    prs: Presentation,
    block: str,
    title: str,
    report: dict[str, Any],
    workspace: Path,
    slide_no: int,
    *,
    spec: dict[str, Any] | None = None,
) -> None:
    """Render a structured (table-based) BnK slide from a block type.

    ``spec`` is the raw SlideSpec dict for THIS slide (title/bullets/asset_ref/params) —
    most blocks below ignore it and re-derive their data from ``report``/``workspace``
    (a single global source per deck), but a block that can appear MULTIPLE times per deck
    with different content each time (e.g. "case_study" — one contract emits several slides,
    see deck._build_deck_plan_registry) needs its own per-slide params instead.
    """
    if block == "case_study":
        _case_study_slide(prs, (spec or {}).get("params") or {}, slide_no, title or "SUCCESS STORY")
        return
    if block == "diagram_image":
        _diagram_image_slide(prs, (spec or {}).get("params") or {}, workspace, slide_no, title or "Diagram")
        return
    if block == "wbs_detail_image":
        img = _wbs_sheet_image_path(workspace, "wbs")
        if img:
            _wbs_sheet_image_slide(prs, img, slide_no, title or "PROJECT DELIVERY | WBS Breakdown")
        else:
            _detail_slide(prs, title, ["WBS breakdown screenshot not yet available."], slide_no)
        return
    if block == "tech_stack_table":
        _tech_stack_table_slide(
            prs, report, slide_no, title or "PROPOSED SOLUTION | Technical Stack", workspace=workspace
        )
    elif block == "func_nfr":
        _functional_nfr_slide(prs, report, slide_no, title or "PROPOSED SOLUTION | Requirements")
    elif block == "sdlc":
        _sdlc_scope_slide(prs, report, workspace, slide_no, title or "SCOPE OF WORK | SDLC Phases")
    elif block == "delivery_effort":
        effort_title = title or "PROJECT DELIVERY | Estimated Effort"
        effort_img = _wbs_sheet_image_path(workspace, "effort")
        if effort_img:
            _wbs_sheet_image_slide(prs, effort_img, slide_no, effort_title)
        else:
            _delivery_effort_slide(prs, workspace, slide_no, effort_title)
    elif block == "gantt":
        gantt_title = title or "PROJECT DELIVERY | Master Plan & Milestones"
        delivery_img = _wbs_sheet_image_path(workspace, "delivery")
        if delivery_img:
            _wbs_sheet_image_slide(prs, delivery_img, slide_no, gantt_title)
        else:
            _gantt_slide(prs, _gantt_params_from_wbs(workspace), slide_no, gantt_title)
    elif block == "pricing":
        _pricing_slide(prs, report, slide_no, title or "PRICING | CAPEX")
    elif block == "milestones":
        _payment_milestones_slide(prs, workspace, slide_no, title or "PRICING | Payment Milestones")
    elif block == "team":
        _team_slide(prs, workspace, slide_no, title or "PROJECT DELIVERY | Team Structure")
    else:  # safety net
        _detail_slide(prs, title, [], slide_no)


def _append_thank_you(prs: Presentation, thank_you_elements: list) -> None:
    """Append the BnK closing slide.

    Uses the template's dedicated "BnK" closing layout (which carries the brand
    design) so a closing slide is always produced — even when the template's last
    slide had no overlay shapes. Any captured shapes are layered on top.
    """
    slide = prs.slides.add_slide(_layout(prs, "BnK", "C2 -  Separator/ Dark", "Blank"))
    for el in thank_you_elements:
        slide.shapes._spTree.insert_element_before(el, "p:extLst")  # noqa: SLF001


def _gantt_params_from_wbs(workspace: Path) -> dict[str, Any]:
    """Master Plan Gantt params from wbs.json — same schedule allocator as the WBS Excel
    "3. Delivery Plan" sheet (wbs_excel._module_schedule), so deck and Excel never drift.
    """
    wbs = read_json_file(workspace / "wbs.json", {})
    if not isinstance(wbs, dict) or not wbs:
        return {"weeks": 0, "months": 0, "sprints": 0, "gantt_rows": []}
    try:
        from domain.wbs.wbs_effort import delivery_grid
        from domain.wbs.wbs_excel import _module_schedule

        weeks = int((wbs.get("timeline") or {}).get("weeks") or 16)
        grid = delivery_grid(weeks)
        rows = (
            [
                {
                    "code": m["code"],
                    "name": m["name"],
                    "start_week": m["start_week"],
                    "end_week": m["end_week"],
                }
                for m in _module_schedule(wbs, grid["weeks"])
            ]
            if wbs.get("phases")
            else []
        )
        return {
            "weeks": grid["weeks"],
            "months": grid["months"],
            "sprints": grid["sprints"],
            "gantt_rows": rows,
        }
    except Exception:  # noqa: BLE001 — never let a schedule glitch break the deck
        return {"weeks": 0, "months": 0, "sprints": 0, "gantt_rows": []}


def _load_current_csm(workspace: Path):
    """Load the workspace CSM, preferring whichever of solution_model.json / .prev.json
    carries the most content — see csm_adapter.load_richest_snapshot (improvement plan
    §1.2 deduplicated this; icon_tools.py uses the same shared helper)."""
    try:
        from csm_adapter import load_richest_snapshot
    except ImportError:
        return None
    return load_richest_snapshot(workspace)


def _enrich_report_from_csm(report: dict[str, Any], workspace: Path) -> dict[str, Any]:
    """Backfill empty ``report`` fields from the CSM + wbs.json + out.slide.json.

    In CSM-era workspaces the legacy blueprint/diagram_brief/tech_stack JSON that
    ``assemble_report_data`` reads are often absent (see docs/bnk_deck_sections.md §8.1),
    so every downstream block renderer would draw from empty wells and produce a thin
    deck. This fills only the fields that are empty — the legacy files still win when
    present — so the fix is additive and safe.
    """
    meta = read_json_file(workspace / "out.slide.json", {}) or {}
    wbs = read_json_file(workspace / "wbs.json", {}) or {}

    if (not report.get("title")) or report.get("title") == "Architecture Blueprint":
        report["title"] = meta.get("title") or meta.get("diagram_title") or report.get("title")
    if (not report.get("subtitle")) or report.get("subtitle") == "Client Architecture Report":
        report["subtitle"] = meta.get("kicker") or report.get("subtitle")
    if not report.get("brand"):
        report["brand"] = meta.get("brand") or report.get("brand") or ""

    model = _load_current_csm(workspace)
    if model is not None:
        if not report.get("tech_items"):
            from domain.deck.deck_resolver import _components_by_cluster

            report["tech_items"] = [
                {"layer": name, "choice": ", ".join(names[:8]), "rationale": purpose}
                for name, purpose, names in _components_by_cluster(model)
            ]
        brief = dict(report.get("brief") or {})
        if not brief.get("functional_requirements"):
            brief["functional_requirements"] = [
                r.statement for r in model.requirements if r.kind == "functional"
            ]
        if not brief.get("non_functional_requirements"):
            brief["non_functional_requirements"] = [
                r.statement for r in model.requirements if r.kind == "nfr"
            ]
        report["brief"] = brief
        blueprint = dict(report.get("blueprint") or {})
        if not blueprint.get("key_decisions"):
            blueprint["key_decisions"] = [d.title for d in model.decisions]
        report["blueprint"] = blueprint
        if not report.get("executive_points"):
            biz = [r.statement for r in model.requirements if r.kind == "business"]
            obj = brief.get("objective") or meta.get("kicker") or ""
            report["executive_points"] = ([obj] if obj else []) + (
                biz[:5] or [r.statement for r in model.requirements[:5]]
            )
        if not report.get("risks"):
            report["risks"] = [
                {"type": "Risk", "detail": r.statement, "recommendation": r.mitigation or ""}
                for r in model.risks
            ]

    # WBS-derived CAPEX (module costs) — always derivable from the WBS + rate card.
    totals = wbs.get("effort_totals") or {}
    if wbs.get("effort_by_module") and not report.get("capex_rows"):
        try:
            from domain.wbs.wbs_effort import DEFAULT_RATE_CARD_USD_PER_MONTH, rate_per_manday

            rate = totals.get("rate_card_usd_per_month") or DEFAULT_RATE_CARD_USD_PER_MONTH
            rows = []
            for m in wbs["effort_by_module"]:
                cost = sum(
                    float(b or 0) * rate_per_manday(rate.get(role, 0))
                    for role, b in (m.get("breakdown") or {}).items()
                )
                rows.append(
                    {"module": f"{m.get('code', '')} {m.get('name', '')}".strip(), "cost": round(cost)}
                )
            report["capex_rows"] = rows
            report["capex_total"] = totals.get("total_cost_usd") or round(sum(r["cost"] for r in rows), 2)
        except Exception:  # noqa: BLE001
            pass
    return report


def generate_ppt_proposal_file(
    workspace: Path,
    *,
    title: str = "",
    subtitle: str = "",
    brand: str = "",
    include_sections: list[str] | None = None,
    deck_style: str = "corporate",
) -> tuple[Path, list[str], list[str]]:
    """Return (pptx_path, sections_rendered, unrecognized_section_names).

    ``deck_style`` selects the brand palette (see DECK_STYLES / _STYLE_PRESETS) for THIS
    call only — set/reset around the actual render so a concurrent call for a different
    workspace/style is never affected.
    """
    token = set_deck_style(deck_style)
    try:
        return _generate_ppt_proposal_file_body(
            workspace, title=title, subtitle=subtitle, brand=brand, include_sections=include_sections
        )
    finally:
        _deck_style_ctx.reset(token)


def _generate_ppt_proposal_file_body(
    workspace: Path,
    *,
    title: str = "",
    subtitle: str = "",
    brand: str = "",
    include_sections: list[str] | None = None,
) -> tuple[Path, list[str], list[str]]:
    template = _template_path()
    if not template.exists():
        raise PPTProposalError(f"BnK template not found: {template}")

    # Reuse existing report data assembly and then apply PPT-specific section names.
    report = assemble_report_data(
        workspace,
        title=title,
        subtitle=subtitle,
        brand=brand,
        include_sections=DEFAULT_REPORT_SECTIONS,
    )
    # Backfill empty report fields from the CSM/wbs so CSM-era workspaces (no legacy
    # blueprint/brief/tech_stack JSON) still render real content — see §8.1.
    _enrich_report_from_csm(report, workspace)
    sections, unrecognized = normalize_ppt_sections(include_sections)

    prs = Presentation(str(template))
    # Save thank-you slide XML before clearing to avoid dangling refs after _clear_slides().
    thank_you_idx = len(prs.slides) - 1 if prs.slides else -1
    thank_you_elements = (
        [deepcopy(s.element) for s in prs.slides[thank_you_idx].shapes] if thank_you_idx >= 0 else []
    )
    _clear_slides(prs)

    # --- Prefer the reviewed, traceable storyboard (deck_plan.json) when present ---
    # The deck plan is a CSM projection the user approved at the propose_deck_plan
    # gate; its SlideSpec is a superset of the render outline dict, so we consume it
    # directly. Falls back to the inline LLM outline (then the hardcoded path) below.
    outline: list[dict[str, Any]] | None = None
    outline_source = "hardcoded layout"
    deck_revision: int | None = None
    try:
        from domain.deck.deck import load_deck_plan

        plan = load_deck_plan(workspace)
        if plan and plan.slides:
            deck_revision = plan.revision
            outline = [
                s.model_dump() for s in plan.slides if (s.section in sections or s.section in ("", "cover"))
            ]
            outline_source = "deck_plan"
    except Exception as exc:  # noqa: BLE001 — a bad plan must not block rendering
        warnings.warn(f"deck_plan render step failed ({exc!r}); falling back.", stacklevel=2)

    # --- Attempt LLM-driven outline (Paper2Any-style) when no deck plan ---
    if not outline:
        try:
            outline = _generate_slide_outline(report, workspace, sections)
            if outline:
                outline_source = "LLM outline"
        except Exception as exc:
            warnings.warn(f"PPT outline LLM step failed ({exc!r}); using hardcoded layout.", stacklevel=2)

    if outline:
        slide_no = 1
        for spec in outline:
            if spec.get("layout") in CLOSING_LAYOUTS:
                continue  # skip — closing is always appended via _append_thank_you below
            _render_slide(prs, spec, report, workspace, slide_no)
            slide_no += 1
        _append_thank_you(prs, thank_you_elements)
        rendered_sections = sections  # LLM covered all requested sections
    else:
        # --- Fallback: hardcoded section-by-section path ---
        slide_no = 1
        sec = 0  # running section-divider counter for roman numerals
        if "cover" in sections:
            _cover_slide(prs, report, slide_no)
            slide_no += 1
        if "executive_summary" in sections:
            sec += 1
            _section_slide(prs, f"{_roman(sec)}. Executive Summary", slide_no)
            slide_no += 1
            _detail_slide(prs, "EXECUTIVE SUMMARY | Overview", report.get("executive_points", []), slide_no)
            slide_no += 1
        if "solution_overview" in sections:
            sec += 1
            _section_slide(prs, f"{_roman(sec)}. Solution Proposal", slide_no)
            slide_no += 1
            _overview_slide(
                prs,
                f"Solution Proposal\n{report['title']}",
                "Proposed Solution | Scope Of Work | Project Delivery",
                slide_no,
            )
            slide_no += 1
            _detail_slide(
                prs,
                "PROPOSED SOLUTION | Overview",
                [
                    report.get("business_value"),
                    report.get("technical_value"),
                    report.get("pattern_rationale"),
                ],
                slide_no,
            )
            slide_no += 1
        if "scope" in sections:
            _functional_nfr_slide(prs, report, slide_no, "PROPOSED SOLUTION | Requirements")
            slide_no += 1
            _sdlc_scope_slide(prs, report, workspace, slide_no)
            slide_no += 1
        if "architecture_diagram" in sections:
            _diagram_slide(prs, report, workspace, slide_no)
            slide_no += 1
        if "technical_stack" in sections:
            _tech_stack_table_slide(prs, report, slide_no)
            slide_no += 1
        if "key_decisions" in sections:
            _detail_slide(
                prs,
                "PROPOSED SOLUTION | Key Decisions",
                _as_list(report["blueprint"].get("key_decisions")),
                slide_no,
            )
            slide_no += 1
        if "delivery_plan" in sections:
            sec += 1
            _section_slide(prs, f"{_roman(sec)}. Project Delivery", slide_no)
            slide_no += 1
            _delivery_effort_slide(prs, workspace, slide_no)
            slide_no += 1
            _team_slide(prs, workspace, slide_no)
            slide_no += 1
        if "pricing" in sections:
            sec += 1
            _section_slide(prs, f"{_roman(sec)}. Pricing", slide_no)
            slide_no += 1
            _pricing_slide(prs, report, slide_no)
            slide_no += 1
            _payment_milestones_slide(prs, workspace, slide_no)
            slide_no += 1
        if "risks" in sections:
            risk_bullets = [
                f"{r.get('type', 'Risk')}: {r.get('detail', '')} Recommendation: {r.get('recommendation', '')}"
                for r in report.get("risks", [])[:7]
                if isinstance(r, dict)
            ]
            _detail_slide(prs, "PROJECT DELIVERY | Risk & Mitigation", risk_bullets, slide_no)
            slide_no += 1
        if "appendix" in sections:
            artifacts_inv = record_artifact_inventory(workspace)
            artifact_bullets = [f"{a['name']}: {a['label']} ({a['bytes']} bytes)" for a in artifacts_inv]
            _detail_slide(prs, "REFERENCE | Generated Artifacts", artifact_bullets, slide_no)
            slide_no += 1
        _append_thank_you(prs, thank_you_elements)
        rendered_sections = sections

    artifacts = record_artifact_inventory(workspace)
    pptx_path = workspace / "out.pptx"
    prs.save(str(pptx_path))
    slide_count = len(prs.slides)
    record_report_step(
        workspace,
        "generate_ppt_proposal",
        summary=(f"Generated editable BnK PowerPoint proposal: {slide_count} slides ({outline_source})."),
        data={
            "sections": rendered_sections,
            "slide_count": slide_count,
            "artifacts": artifacts,
            "outline_source": outline_source,
            "deck_plan_revision": deck_revision,
        },
    )
    return pptx_path, rendered_sections, unrecognized
