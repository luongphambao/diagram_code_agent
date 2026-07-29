"""brd_validate — structural lint for a BRD .docx (docs/plans/2026-07-29-brd-agent.md §D).

Same [error]/[warning]/[advice] taxonomy as domain/validation/diagram_lint.py,
applied to the OOXML section tree (domain/brd/brd_docx.py) instead of a typed-
diagram spec. CSM-based traceability checks (FR <-> Requirement coverage) are
deliberately NOT implemented yet — the BRD <-> CSM link isn't defined until the
brd_assembler is wired to a real gate flow; adding a fuzzy traceability check
now would risk false positives with no way to fix them. Everything here is
purely structural and needs no CSM/outline input to run.
"""

from __future__ import annotations

import re
from typing import Optional

from docx.oxml.ns import qn
from docx.table import Table

from domain.brd.brd_docx import Section, blocks, index_document

_PLACEHOLDER_RE = re.compile(r"\b(TODO|TBD|XXX)\b|Lorem ipsum|«\s*…\s*»|<\s*…\s*>", re.I)
_FR_CODE_RE = re.compile(r"^fr\d", re.I)
_FR_CHILD_SLOTS = ("description", "interface-requirements", "data-requirements")


def _own_body(bs: list, sec: Section) -> list:
    return bs[sec.own_start : sec.own_end + 1] if sec.own_end >= sec.own_start else []


def validate_brd(path_or_doc, *, outline: Optional[dict] = None) -> dict:
    """outline: optional {section_id: {"status": "fill"|"keep"|"skip", ...}} — used
    only for the thin-fill-section warning. Returns the same shape as
    domain.validation.diagram_lint.LintReport.to_dict() plus *_count/ok/section_count."""
    doc, sections = index_document(path_or_doc)
    bs = blocks(doc)
    by_id = {s.section_id: s for s in sections}

    errors: list[dict] = []
    warnings: list[dict] = []
    advice: list[dict] = []

    def err(code: str, message: str, ref: str = "") -> None:
        errors.append({"code": code, "message": message, "ref": ref})

    def warn(code: str, message: str, ref: str = "") -> None:
        warnings.append({"code": code, "message": message, "ref": ref})

    seen_ids: set[str] = set()
    prev_level = 0
    for s in sections:
        if s.section_id in seen_ids:
            err("duplicate_id", f"id '{s.section_id}' xuất hiện nhiều lần — lỗi ở indexer.", s.section_id)
        seen_ids.add(s.section_id)

        last_component = s.section_id.rsplit("/", 1)[-1]
        if "~" in last_component:
            warn(
                "ambiguous_anchor",
                f"'{s.section_id}' trùng tiêu đề với anh em cùng cha — nên đổi tên để id không phụ thuộc thứ tự.",
                s.section_id,
            )

        if s.level > prev_level + 1:
            err(
                "heading_level_jump",
                f"'{s.section_id}' nhảy từ cấp {prev_level} lên cấp {s.level} — phá TOC/đánh số.",
                s.section_id,
            )
        prev_level = s.level

        heading_p = bs[s.heading_idx]
        pPr = heading_p._p.find(qn("w:pPr"))
        numPr = pPr.find(qn("w:numPr")) if pPr is not None else None
        if numPr is None:
            err(
                "heading_missing_numbering",
                f"'{s.section_id}' không có numPr — mất đánh số tự động của Word.",
                s.section_id,
            )

        own = _own_body(bs, s)
        if len(own) > 40:
            warn(
                "section_too_long",
                f"'{s.section_id}' có {len(own)} block trong thân riêng — nên tách nhỏ.",
                s.section_id,
            )

        n_placeholder = sum(1 for b in own if _PLACEHOLDER_RE.search(getattr(b, "text", "") or ""))
        if n_placeholder:
            err(
                "placeholder_residue",
                f"'{s.section_id}' còn {n_placeholder} đoạn chứa placeholder (TODO/TBD/Lorem/...).",
                s.section_id,
            )

        for i, b in enumerate(own):
            if hasattr(b, "_p") and b._p.findall(".//" + qn("a:blip")):
                nxt = own[i + 1] if i + 1 < len(own) else None
                nxt_style = getattr(getattr(nxt, "style", None), "name", "") or ""
                if nxt_style != "Caption":
                    warn(
                        "image_missing_caption",
                        f"'{s.section_id}': ảnh không có caption ngay sau.",
                        s.section_id,
                    )
                for blip in b._p.findall(".//" + qn("a:blip")):
                    rid = blip.get(qn("r:embed"))
                    if rid and rid not in doc.part.rels:
                        err(
                            "dangling_image_rel",
                            f"'{s.section_id}': ảnh trỏ rId '{rid}' không tồn tại.",
                            s.section_id,
                        )

        for b in own:
            if isinstance(b, Table):
                if not b.rows:
                    err("empty_table", f"'{s.section_id}': bảng không có dòng nào.", s.section_id)
                    continue
                header_cols = len(b.rows[0].cells)
                for ri, row in enumerate(b.rows[1:], start=1):
                    if len(row.cells) != header_cols:
                        err(
                            "table_column_mismatch",
                            f"'{s.section_id}': dòng {ri} có {len(row.cells)} cột, header có {header_cols}.",
                            s.section_id,
                        )

        if _FR_CODE_RE.match(last_component):
            child_slots = {c.rsplit("/", 1)[-1] for c in s.children}
            missing = [slot for slot in _FR_CHILD_SLOTS if slot not in child_slots]
            if missing:
                err("fr_missing_slot", f"'{s.section_id}' thiếu mục con bắt buộc: {missing}.", s.section_id)

    if outline:
        for sid, meta in outline.items():
            if not (isinstance(meta, dict) and meta.get("status") == "fill"):
                continue
            sec = by_id.get(sid)
            if sec is None:
                continue
            own_text_len = sum(len(getattr(b, "text", "") or "") for b in _own_body(bs, sec))
            if own_text_len < 20:
                warn(
                    "thin_fill_section",
                    f"'{sid}' đánh dấu status=fill nhưng thân chỉ {own_text_len} ký tự.",
                    sid,
                )

    return {
        "errors": errors,
        "warnings": warnings,
        "advice": advice,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "advice_count": len(advice),
        "section_count": len(sections),
        "ok": len(errors) == 0,
    }
