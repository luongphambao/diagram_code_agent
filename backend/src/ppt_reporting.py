"""Editable BnK PowerPoint proposal generation for architecture diagrams."""

from __future__ import annotations

import datetime as dt
import json
import re
import warnings
from copy import deepcopy
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.enum.text import PP_ALIGN, MSO_AUTO_SIZE
from pptx.util import Inches, Pt

from reporting import (
    DEFAULT_REPORT_SECTIONS,
    assemble_report_data,
    normalize_sections,
    read_json_file,
    record_artifact_inventory,
    record_report_step,
)

DEFAULT_PPT_SECTIONS = [
    "cover",
    "executive_summary",
    "solution_overview",
    "scope",
    "architecture_diagram",
    "technical_stack",
    "key_decisions",
    "delivery_plan",
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
    "wbs": "delivery_plan",
    "risk": "risks",
    "artifact": "appendix",
}

VALID_LAYOUTS = frozenset({
    "Cover-01",
    "Head Page",
    "Head-01",
    "Detail-01",
    "Overview-01",
    "Empty",
    "BnK",
    "C2 - Separator/Dark",
})

OUTLINE_TARGET_MIN = 20
OUTLINE_TARGET_MAX = 30

_OUTLINE_SYSTEM_PROMPT = """\
You are a senior solution architect at BnK, a Vietnamese technology consultancy.
Generate a professional PowerPoint proposal slide outline for a client project.

OUTPUT FORMAT — each slide MUST have exactly these four fields:
{
  "title": "SECTION | Sub-topic",
  "layout": "<layout_name>",
  "bullets": ["...", "..."],
  "asset_ref": null
}

VALID LAYOUT NAMES (use EXACTLY as written):
  "Cover-01"            — Opening cover. Use ONCE as slide 1. Set title to "".
  "Head Page"           — Major section divider with Roman numeral (I., II., III., …).
  "Head-01"             — Secondary section header, no Roman numeral.
  "Detail-01"           — Content slide with title + bullets. Most common. Use 15-20 times.
  "Overview-01"         — Overview: put one subtitle string in bullets[0], no other bullets.
  "Empty"               — Full-width image slide. Use with asset_ref: "architecture_diagram".
  "BnK"                 — Closing brand slide. Use ONCE as the last slide. title "" bullets [].
  "C2 - Separator/Dark" — Dark separator. Optional, once before BnK.

SLIDE COUNT: Generate exactly 20-30 slides total.

TYPICAL STRUCTURE (adapt to the actual project data):
  1.   Cover-01          — cover
  2.   Head Page         "I. Executive Summary"
  3-4. Detail-01         executive highlights, business value
  5.   Head Page         "II. Proposed Solution"
  6.   Overview-01       solution scope overview (subtitle in bullets[0])
  7-10. Detail-01        functional scope, NFRs, approach, key features
  11.  Head Page         "III. Technical Architecture"
  12.  Head-01           "Architecture Overview"
  13.  Empty             architecture diagram (asset_ref: "architecture_diagram")
  14-16. Detail-01       components, integration points, security
  17.  Head Page         "IV. Technology Stack"
  18-20. Detail-01       tech stack per layer (frontend/backend, data, infra)
  21.  Head Page         "V. Project Delivery"
  22.  Overview-01       delivery methodology
  23-24. Detail-01       WBS effort & timeline, team structure
  25.  Detail-01         risks & mitigations
  26.  Head-01           "Key Design Decisions"
  27.  Detail-01         key decisions and rationale
  28.  BnK               closing

TITLE FORMAT:
  - Detail-01: "SECTION | Sub-topic"  e.g. "PROPOSED SOLUTION | Functional Scope"
  - Head Page / Head-01: section name with Roman numeral  e.g. "III. Technical Architecture"
  - Cover-01 and BnK: empty string ""

RULES:
  1. Use ONLY the 8 layout names listed — no other values.
  2. Cover-01 must be slide 1; BnK must be last.
  3. Include the Empty/diagram slide ONLY if HAS_ARCHITECTURE_DIAGRAM is yes.
  4. Base ALL bullet content on the actual project data — no generic placeholders.
  5. OUTPUT: Return ONLY the JSON array. No code fences, no text outside the array.\
"""


class PPTProposalError(RuntimeError):
    """Raised when PPT proposal generation cannot complete."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _template_path() -> Path:
    return _repo_root() / "DATA" / "SLIDE" / "[BnK] Template - Proposal.pptx"


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


_ROMAN = [(1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),
          (50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I")]


def _roman(n: int) -> str:
    result = ""
    for val, numeral in _ROMAN:
        while n >= val:
            result += numeral
            n -= val
    return result


def _layout(prs: Presentation, *names: str):
    wanted = {n.lower() for n in names}
    for layout in prs.slide_layouts:
        if layout.name.lower() in wanted:
            return layout
    import warnings
    warnings.warn(f"PPT layout(s) {list(names)!r} not found in template; using layout[0] as fallback.", stacklevel=3)
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
    slide.shapes.add_picture(str(image_path), Inches(left), Inches(top), width=Inches(final_w), height=Inches(final_h))


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
            bullets.append(f"{module.get('code', '')} {module.get('name', 'Module')}: {module.get('total_md', 0)} MD.")
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
        lines.append(
            f"  Total: {totals.get('total_mandays', 0)} MD"
            f" / {totals.get('total_manmonths', 0)} MM"
        )
        lines.append(
            f"  Timeline: {timeline.get('weeks', 0)} weeks"
            f" / {timeline.get('months', 0)} months"
        )
        for mod in _as_list(wbs.get("effort_by_module"))[:6]:
            if isinstance(mod, dict):
                lines.append(
                    f"  - {mod.get('code', '')} {mod.get('name', 'Module')}:"
                    f" {mod.get('total_md', 0)} MD"
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
        or (lambda m: _try(m.group(1)) if m else None)(
            re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        )
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
        bullets = [
            _clip(b, 200)
            for b in _as_list(item.get("bullets") or [])[:7]
            if str(b or "").strip()
        ]
        valid.append(
            {
                "title": _clip(str(item.get("title") or ""), 80),
                "layout": layout,
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
        else (
            f"\nNOTE: Only include slides relevant to these sections: "
            + ", ".join(sections)
            + "."
        )
    )
    user_msg = (
        f"Here is the project data for the proposal:\n\n{context}{sections_note}\n\n"
        "Generate the slide outline now. Return ONLY the JSON array."
    )

    try:
        response = llm.invoke(
            [SystemMessage(content=_OUTLINE_SYSTEM_PROMPT), HumanMessage(content=user_msg)]
        )
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
    elif layout in ("BnK", "C2 - Separator/Dark"):
        pass  # Closing slides are always appended via _append_thank_you after the loop.
    else:
        _detail_slide(prs, title, bullets, slide_no)


def _append_thank_you(prs: Presentation, thank_you_elements: list) -> None:
    """Append the BnK closing slide using shape elements extracted from the template."""
    if not thank_you_elements:
        return
    slide = prs.slides.add_slide(_layout(prs, "C2 -  Separator/ Dark", "Blank"))
    for el in thank_you_elements:
        slide.shapes._spTree.insert_element_before(el, "p:extLst")  # noqa: SLF001


def generate_ppt_proposal_file(
    workspace: Path,
    *,
    title: str = "",
    subtitle: str = "",
    brand: str = "",
    include_sections: list[str] | None = None,
) -> tuple[Path, list[str], list[str]]:
    """Return (pptx_path, sections_rendered, unrecognized_section_names)."""
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
    sections, unrecognized = normalize_ppt_sections(include_sections)

    prs = Presentation(str(template))
    # Save thank-you slide XML before clearing to avoid dangling refs after _clear_slides().
    thank_you_idx = len(prs.slides) - 1 if prs.slides else -1
    thank_you_elements = (
        [deepcopy(s.element) for s in prs.slides[thank_you_idx].shapes]
        if thank_you_idx >= 0 else []
    )
    _clear_slides(prs)

    # --- Attempt LLM-driven outline (Paper2Any-style) ---
    outline: list[dict[str, Any]] | None = None
    try:
        outline = _generate_slide_outline(report, workspace, sections)
    except Exception as exc:
        warnings.warn(f"PPT outline LLM step failed ({exc!r}); using hardcoded layout.", stacklevel=2)

    if outline:
        slide_no = 1
        for spec in outline:
            if spec.get("layout") in ("BnK", "C2 - Separator/Dark"):
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
                [report.get("business_value"), report.get("technical_value"), report.get("pattern_rationale")],
                slide_no,
            )
            slide_no += 1
        if "scope" in sections:
            _detail_slide(
                prs,
                "SCOPE OF WORK",
                _as_list(report["brief"].get("functional_requirements"))[:5]
                + _as_list(report["brief"].get("non_functional_requirements"))[:5],
                slide_no,
            )
            slide_no += 1
        if "architecture_diagram" in sections:
            _diagram_slide(prs, report, workspace, slide_no)
            slide_no += 1
        if "technical_stack" in sections:
            _detail_slide(prs, "PROPOSED SOLUTION | Technical Stack", _tech_bullets(report), slide_no)
            slide_no += 1
        if "key_decisions" in sections:
            _detail_slide(prs, "PROPOSED SOLUTION | Key Decisions", _as_list(report["blueprint"].get("key_decisions")), slide_no)
            slide_no += 1
        if "delivery_plan" in sections:
            sec += 1
            _section_slide(prs, f"{_roman(sec)}. Project Delivery", slide_no)
            slide_no += 1
            _detail_slide(prs, "PROJECT DELIVERY | Estimated Effort", _delivery_bullets(workspace), slide_no)
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
        summary=(
            f"Generated editable BnK PowerPoint proposal: {slide_count} slides"
            f" ({'LLM outline' if outline else 'hardcoded layout'})."
        ),
        data={"sections": rendered_sections, "slide_count": slide_count, "artifacts": artifacts},
    )
    return pptx_path, rendered_sections, unrecognized

