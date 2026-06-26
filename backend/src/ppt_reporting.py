"""Editable BnK PowerPoint proposal generation for architecture diagrams."""

from __future__ import annotations

import datetime as dt
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


def _layout(prs: Presentation, *names: str):
    wanted = {n.lower() for n in names}
    for layout in prs.slide_layouts:
        if layout.name.lower() in wanted:
            return layout
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
    from reporting import read_json_file

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
    thank_you_idx = len(prs.slides) - 1 if prs.slides else -1
    thank_you = _clone_slide(prs, thank_you_idx) if thank_you_idx >= 0 else None
    _clear_slides(prs)

    slide_no = 1
    if "cover" in sections:
        _cover_slide(prs, report, slide_no)
        slide_no += 1
    if "executive_summary" in sections:
        _section_slide(prs, "I. Executive Summary", slide_no)
        slide_no += 1
        _detail_slide(prs, "EXECUTIVE SUMMARY | Overview", report.get("executive_points", []), slide_no)
        slide_no += 1
    if "solution_overview" in sections:
        _section_slide(prs, "II. Solution Proposal", slide_no)
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
        _section_slide(prs, "III. Project Delivery", slide_no)
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
        artifacts = record_artifact_inventory(workspace)
        artifact_bullets = [f"{a['name']}: {a['label']} ({a['bytes']} bytes)" for a in artifacts]
        _detail_slide(prs, "REFERENCE | Generated Artifacts", artifact_bullets, slide_no)
        slide_no += 1

    if thank_you is not None:
        # Move cloned thank-you slide from scratch presentation into the output deck.
        slide = prs.slides.add_slide(_layout(prs, "C2 -  Separator/ Dark", "Blank"))
        for shape in thank_you.shapes:
            slide.shapes._spTree.insert_element_before(deepcopy(shape.element), "p:extLst")  # noqa: SLF001

    pptx_path = workspace / "out.pptx"
    prs.save(str(pptx_path))
    record_report_step(
        workspace,
        "generate_ppt_proposal",
        summary=f"Generated editable BnK PowerPoint proposal with {len(sections)} requested sections.",
        data={"sections": sections, "artifacts": record_artifact_inventory(workspace)},
    )
    return pptx_path, sections, unrecognized

