"""brd_docx — section-addressed .docx edit layer (docs/plans/2026-07-29-brd-agent.md).

A BRD .docx is treated as a tree of Sections, each with a STABLE id (a parent-scoped
path, e.g. "fr07/description") and an own-body checksum used for optimistic locking.
Every write goes through one of the ops in `apply_ops` — never a full-document
regeneration — and `apply_brd_ops` wraps that in snapshot + atomic-write + revert-on-
semantic-loss, mirroring the read_drawio/edit_drawio pattern in
backend/src/tools/rendering_tools.py.

Pure domain module: no imports from tools/ or agent/ (docs/conventions.md §1).
"""

from __future__ import annotations

import copy
import hashlib
import io
import os
import re
import shutil
import unicodedata
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from docx import Document
from docx.document import Document as _Doc
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from docx.table import Table
from docx.text.paragraph import Paragraph

HEADING_RE = re.compile(r"^(Heading|Appendix)\s*(\d*)$")
_CODE_RE = re.compile(
    r"^\s*(?P<code>(?:FR|NFR|BR|UC|REQ|RULE|ISS|RSK|APP|PH)[\s\-_–—]?\d{1,3}"
    r"(?:[.\-]\d{1,3})*)(?=\W|$)",
    re.I,
)
_SEP, _DUP = "/", "~"

_STYLE_PARTS_MUST_MATCH = (
    "word/styles.xml",
    "word/numbering.xml",
    "word/settings.xml",
    "word/theme/theme1.xml",
)


# --------------------------------------------------------------------------- #
# errors — plain messages, caught at the tool boundary and returned verbatim
# to the model (repo convention: gate/edit tools never raise, they return a
# string telling the model what to do next).
# --------------------------------------------------------------------------- #
class BrdOpError(Exception):
    """Base for every recoverable op failure."""


class SectionNotFoundError(BrdOpError):
    pass


class AmbiguousSectionError(BrdOpError):
    pass


class ChecksumConflictError(BrdOpError):
    pass


class BlockAddressError(BrdOpError):
    pass


class CascadeRequiredError(BrdOpError):
    pass


# --------------------------------------------------------------------------- #
# block helpers
# --------------------------------------------------------------------------- #
def iter_blocks(doc: _Doc):
    body = doc.element.body
    i = 0
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield i, Paragraph(child, doc)
            i += 1
        elif child.tag == qn("w:tbl"):
            yield i, Table(child, doc)
            i += 1


def blocks(doc: _Doc) -> list:
    return [b for _, b in iter_blocks(doc)]


def heading_level(block) -> Optional[int]:
    if not isinstance(block, Paragraph):
        return None
    try:
        name = (block.style.name or "").strip()
    except KeyError:
        return None
    m = HEADING_RE.match(name)
    if not m:
        return None
    if name.startswith("Appendix"):
        return 1
    return int(m.group(2)) if m.group(2) else 1


def slugify(text: str, max_len: int = 40) -> str:
    t = (text or "").lower().strip().replace("đ", "d")
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    if len(t) > max_len:
        cut = t[:max_len].rsplit("-", 1)[0]
        t = cut or t[:max_len]
    return t.strip("-") or "section"


_LEGACY_NUMBER_PREFIX_RE = re.compile(r"^\s*\d+(?:\.\d+)*\s*[.\t]?\s*")


def id_component(title: str) -> str:
    """'FR07 – Sinh báo cáo PDF' -> 'fr07'; 'Data requirements' -> 'data-requirements'.

    Some templates bake a legacy manual outline number directly into the
    heading text alongside Word's OWN auto-numbering (e.g. real company
    template heading text is literally '3.2.1\\tDescription') — strip that
    redundant prefix before slugifying, or ids drift with every renumber
    exactly like the position-based ids this module exists to replace."""
    m = _CODE_RE.match(title or "")
    if m:
        return re.sub(r"[\s\-_–—.]+", "", m.group("code")).lower()
    return slugify(_LEGACY_NUMBER_PREFIX_RE.sub("", title or "", count=1))


def assign_section_ids(heads: list[tuple[int, int, str]]) -> list[str]:
    """heads = [(block_idx, level, title)] in document order. Dedup is scoped to
    (parent_id, component) — NOT global — so inserting a heading anywhere else in
    the document can never re-point an existing id (the prototype's bug)."""
    stack: list[tuple[int, str]] = []
    used: dict[tuple[str, str], int] = {}
    out: list[str] = []
    for _idx, lv, title in heads:
        while stack and stack[-1][0] >= lv:
            stack.pop()
        parent_id = stack[-1][1] if stack else ""
        comp = id_component(title)
        key = (parent_id, comp)
        used[key] = used.get(key, 0) + 1
        if used[key] > 1:
            comp = f"{comp}{_DUP}{used[key]}"
        sid = f"{parent_id}{_SEP}{comp}" if parent_id else comp
        out.append(sid)
        stack.append((lv, sid))
    return out


def _style_id(b) -> str:
    try:
        return b.style.style_id or ""
    except KeyError:
        return ""


def _numid_ilvl(b) -> tuple[str, str]:
    if not isinstance(b, Paragraph):
        return "", ""
    pPr = b._p.find(qn("w:pPr"))
    numPr = pPr.find(qn("w:numPr")) if pPr is not None else None
    if numPr is None:
        return "", ""
    numId = numPr.find(qn("w:numId"))
    ilvl = numPr.find(qn("w:ilvl"))
    return (
        numId.get(qn("w:val")) if numId is not None else "",
        ilvl.get(qn("w:val")) if ilvl is not None else "",
    )


def _image_rel_targets(b, doc: _Doc) -> list[str]:
    if not isinstance(b, Paragraph):
        return []
    out = []
    for blip in b._p.findall(".//" + qn("a:blip")):
        rid = blip.get(qn("r:embed"))
        if rid and rid in doc.part.rels:
            out.append(doc.part.rels[rid].target_ref)
    return sorted(out)


def _cell_texts(b) -> list[str]:
    return ["\t".join(c.text for c in r.cells) for r in b.rows]


def _count_images(b) -> int:
    """Images inside table cells count too (prototype missed these)."""
    if isinstance(b, Paragraph):
        return len(b._p.findall(".//" + qn("a:blip")))
    if isinstance(b, Table):
        return len(b._tbl.findall(".//" + qn("a:blip")))
    return 0


def block_digest(b, doc: _Doc) -> str:
    """Covers more than text: style id, numbering, and image targets, so an image
    swap or a bullet-vs-plain change is NOT invisible to the optimistic lock."""
    if isinstance(b, Paragraph):
        numid, ilvl = _numid_ilvl(b)
        imgs = ",".join(_image_rel_targets(b, doc))
        payload = f"p|{_style_id(b)}|{numid}:{ilvl}|{b.text}|{imgs}"
    else:
        payload = f"tbl|{_style_id(b)}|{len(b.rows)}x{len(b.columns)}|" + "\x1f".join(_cell_texts(b))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def block_addr(b, ordinal: int, doc: _Doc) -> str:
    return f"b{ordinal}#{block_digest(b, doc)[:8]}"


def _section_digest(body: list, doc: _Doc) -> str:
    parts = []
    for b in body:
        if isinstance(b, Paragraph):
            numid, ilvl = _numid_ilvl(b)
            imgs = ",".join(_image_rel_targets(b, doc))
            parts.append(f"P|{_style_id(b)}|{numid}:{ilvl}|{b.text}|{imgs}")
        else:
            parts.append(f"T|{_style_id(b)}|{len(b.rows)}x{len(b.columns)}|" + "\x1f".join(_cell_texts(b)))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# section index — own body vs subtree are tracked separately (the prototype
# conflated them, which is why replace_section on a parent silently deleted its
# children — see docs/plans/2026-07-29-brd-agent.md §Context (C), P0-2/P0-3).
# --------------------------------------------------------------------------- #
@dataclass
class Section:
    section_id: str
    title: str
    level: int
    heading_idx: int
    own_start: int
    own_end: int  # inclusive; -1 if the section's own body is empty
    sub_start: int
    sub_end: int  # inclusive; -1 if the whole subtree is empty
    own_checksum: str = ""
    sub_checksum: str = ""
    n_paragraphs: int = 0
    n_tables: int = 0
    n_images: int = 0
    parent_id: Optional[str] = None
    children: list[str] = field(default_factory=list)
    path: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def index_document(path_or_doc) -> tuple[_Doc, list[Section]]:
    doc = path_or_doc if isinstance(path_or_doc, _Doc) else Document(path_or_doc)
    bs = blocks(doc)
    heads: list[tuple[int, int, str]] = []
    for i, b in enumerate(bs):
        lv = heading_level(b)
        if lv is not None and b.text.strip():
            heads.append((i, lv, b.text.strip()))

    ids = assign_section_ids(heads)

    sections: list[Section] = []
    stack: list[Section] = []
    for n, (idx, lv, title) in enumerate(heads):
        # own body ends right before the very NEXT heading in the document,
        # whatever its level — a child heading starts a sub-section, which is
        # by definition not part of this section's own body.
        own_end = (heads[n + 1][0] - 1) if n + 1 < len(heads) else len(bs) - 1
        # sub body (whole subtree) ends before the next heading at the SAME or
        # a HIGHER level (i.e. a sibling or an ancestor's sibling).
        sub_end = len(bs) - 1
        for j in range(n + 1, len(heads)):
            if heads[j][1] <= lv:
                sub_end = heads[j][0] - 1
                break
        own_start = sub_start = idx + 1

        sid = ids[n]
        while stack and stack[-1].level >= lv:
            stack.pop()
        parent = stack[-1] if stack else None
        parent_id = parent.section_id if parent else None
        path = (parent.path + " > " if parent else "") + title

        own_body = bs[own_start : own_end + 1] if own_end >= own_start else []
        s = Section(
            section_id=sid,
            title=title,
            level=lv,
            heading_idx=idx,
            own_start=own_start,
            own_end=own_end if own_end >= own_start else -1,
            sub_start=sub_start,
            sub_end=sub_end if sub_end >= sub_start else -1,
            own_checksum=_section_digest(own_body, doc),
            n_paragraphs=sum(1 for b in own_body if isinstance(b, Paragraph)),
            n_tables=sum(1 for b in own_body if isinstance(b, Table)),
            n_images=sum(_count_images(b) for b in own_body),
            parent_id=parent_id,
            path=path,
        )
        sections.append(s)
        if parent is not None:
            parent.children.append(sid)
        stack.append(s)

    for s in sections:
        sub_body = bs[s.sub_start : s.sub_end + 1] if s.sub_end >= s.sub_start else []
        s.sub_checksum = _section_digest(sub_body, doc)

    return doc, sections


def _sections_by_id(sections: list[Section]) -> dict[str, Section]:
    return {s.section_id: s for s in sections}


def resolve_section_ref(sections: list[Section], ref: str) -> Section:
    """Never falls back to fuzzy title matching (the prototype's bug — see
    docs/plans/2026-07-29-brd-agent.md §Context (B)/P0-7). Accepts an exact id
    or a unique trailing-path suffix; anything else is an explicit error listing
    every valid id."""
    ref = (ref or "").strip()
    for s in sections:
        if s.section_id == ref:
            return s
    suffix = ref.strip("/")
    hits = [s for s in sections if s.section_id == suffix or s.section_id.endswith("/" + suffix)]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise AmbiguousSectionError(
            f"'{ref}' khớp {len(hits)} mục: {', '.join(h.section_id for h in hits)}. "
            "Chọn đúng một id đầy đủ từ read_brd_outline."
        )
    raise SectionNotFoundError(
        f"Không tìm thấy mục '{ref}'. Các id hợp lệ: {', '.join(s.section_id for s in sections)}"
    )


def _own_body(doc: _Doc, sec: Section) -> list:
    bs = blocks(doc)
    return bs[sec.own_start : sec.own_end + 1] if sec.own_end >= sec.own_start else []


_BLOCK_ADDR_RE = re.compile(r"^b(\d+)#([0-9a-f]{6,64})$")


def resolve_block_ref(doc: _Doc, sec: Section, ref: str) -> tuple[int, list]:
    """Returns (ordinal within own body, own body list). Self-heals a stale
    ordinal by scanning for a UNIQUE block with the same content digest — never
    guesses when the digest is ambiguous or missing."""
    own = _own_body(doc, sec)
    m = _BLOCK_ADDR_RE.match(ref or "")
    if not m:
        raise BlockAddressError(
            f"Địa chỉ block không hợp lệ: '{ref}'. Dùng đúng định dạng từ read_brd_section."
        )
    ordinal, digest8 = int(m.group(1)), m.group(2)[:8]
    if 0 <= ordinal < len(own) and block_digest(own[ordinal], doc)[:8] == digest8:
        return ordinal, own
    hits = [i for i, b in enumerate(own) if block_digest(b, doc)[:8] == digest8]
    if len(hits) == 1:
        return hits[0], own
    addrs = ", ".join(block_addr(b, i, doc) for i, b in enumerate(own))
    raise BlockAddressError(
        f"Địa chỉ block cũ '{ref}' trong '{sec.section_id}' — không còn khớp. "
        f"Mục hiện có {len(own)} block: {addrs}. Đọc lại read_brd_section('{sec.section_id}')."
    )


def _check_expect(sec: Section, expect: Optional[str]) -> None:
    if not expect:
        raise ValueError("Thiếu 'expect' — bắt buộc cho mọi op.")
    if expect != sec.own_checksum:
        raise ChecksumConflictError(
            f"chưa ghi gì. Mục '{sec.section_id}' hiện có checksum {sec.own_checksum}, "
            f"bạn gửi {expect}. Mục đã đổi kể từ lần bạn đọc — gọi lại "
            f"read_brd_section('{sec.section_id}') rồi thử lại. KHÔNG bỏ qua expect."
        )


# --------------------------------------------------------------------------- #
# style-borrowing cache — scoped to ONE apply-ops call (one Document instance),
# never a module-global keyed on id(doc): CPython reuses freed addresses, so a
# global cache can graft a heading's numbering from an unrelated document.
# --------------------------------------------------------------------------- #
class StyleCache:
    def __init__(self, doc: _Doc):
        self.doc = doc
        self._heading_ppr: dict[int, Any] = {}
        self._negative_heading: set[int] = set()
        self._bullet_num_id: Optional[int] = None

    def heading_pPr(self, level: int):
        if level in self._negative_heading:
            return None
        if level not in self._heading_ppr:
            want = f"Heading {level}"
            found = None
            for q in self.doc.paragraphs:
                if (q.style.name or "") == want:
                    pPr = q._p.find(qn("w:pPr"))
                    if pPr is not None and pPr.find(qn("w:numPr")) is not None:
                        found = copy.deepcopy(pPr)
                        pb = found.find(qn("w:pageBreakBefore"))
                        if pb is not None:
                            found.remove(pb)
                        break
            if found is None:
                self._negative_heading.add(level)
                return None
            self._heading_ppr[level] = found
        return self._heading_ppr[level]

    def bullet_num_id(self) -> int:
        if self._bullet_num_id is None:
            self._bullet_num_id = detect_bullet_num_id(self.doc)
        return self._bullet_num_id


def detect_bullet_num_id(doc: _Doc, default: int = 10) -> int:
    for p in doc.paragraphs:
        if (p.style.name or "").startswith(("List", "bullet")):
            pPr = p._p.find(qn("w:pPr"))
            numPr = pPr.find(qn("w:numPr")) if pPr is not None else None
            if numPr is not None:
                numId = numPr.find(qn("w:numId"))
                if numId is not None:
                    return int(numId.get(qn("w:val")))
    return default


def _apply_numbering(p: Paragraph, num_id: int, ilvl: int = 0) -> None:
    """`get_or_add_numPr` places w:numPr in the OOXML-mandated position (right
    after w:pStyle) — the prototype's manual `pPr.append(numPr)` only worked
    because it only ever ran on an empty pPr; it corrupts a paragraph that
    already has spacing/ind/jc."""
    numPr = p._p.get_or_add_pPr().get_or_add_numPr()
    numPr.get_or_add_ilvl().val = ilvl
    numPr.get_or_add_numId().val = num_id


def _insert_heading(doc: _Doc, style_cache: StyleCache, title: str, level: int) -> Paragraph:
    style = f"Heading {level}"
    p = doc.add_paragraph(title, style=style if _style_or_none(doc, style) else None)
    exemplar = style_cache.heading_pPr(level)
    if exemplar is not None:
        old = p._p.find(qn("w:pPr"))
        if old is not None:
            p._p.remove(old)
        p._p.insert(0, copy.deepcopy(exemplar))
    return p


def _style_or_none(doc: _Doc, name: str):
    try:
        doc.styles[name]
        return name
    except KeyError:
        return None


def _new_paragraph(
    doc: _Doc,
    text: str,
    style: Optional[str] = None,
    bold: bool = False,
    italic: bool = False,
    align: Optional[str] = None,
) -> Paragraph:
    p = doc.add_paragraph()
    if style and _style_or_none(doc, style):
        p.style = doc.styles[style]
    if text:
        run = p.add_run(text)
        run.bold = bold
        run.italic = italic
    if align == "center":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return p


def _set_cell_text(cell, text: str, *, bold: bool = False) -> None:
    """Sets the run's text directly instead of `cell.text = ""` (which calls
    tc.clear_content() and destroys the cell paragraph's own pPr/style)."""
    para = cell.paragraphs[0]
    for extra in list(para.runs[1:]):
        extra.text = ""
    if para.runs:
        para.runs[0].text = str(text)
        if bold:
            para.runs[0].bold = True
    else:
        r = para.add_run(str(text))
        r.bold = bold
    for extra_p in list(cell.paragraphs[1:]):
        _detach(extra_p)


def _new_table(
    doc: _Doc, rows: list[list[str]], style: str = "Table Grid", widths: Optional[list[float]] = None
) -> Table:
    ncols = max(len(r) for r in rows)
    t = doc.add_table(rows=len(rows), cols=ncols)
    if _style_or_none(doc, style):
        t.style = doc.styles[style]
    t.autofit = True
    for ri, row in enumerate(rows):
        for ci in range(ncols):
            _set_cell_text(t.cell(ri, ci), row[ci] if ci < len(row) else "", bold=(ri == 0))
    if widths:
        for ri in range(len(rows)):
            for ci, w in enumerate(widths[:ncols]):
                t.cell(ri, ci).width = Inches(w)
    return t


def _new_image(doc: _Doc, image_path: str, width_in: float = 6.1) -> Paragraph:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(image_path, width=Inches(width_in))
    return p


def build_block(doc: _Doc, spec: dict, style_cache: StyleCache):
    """spec = {"type": "p"|"bullet"|"table"|"image"|"caption"|"code", ...}.
    type="heading" is REJECTED here — heading creation goes only through the
    insert_section op, which knows how to assign it an id."""
    kind = spec.get("type", "p")
    if kind == "heading":
        raise ValueError("type='heading' bị cấm trong content — dùng op insert_section.")
    if kind == "p":
        return _new_paragraph(
            doc,
            spec.get("text", ""),
            spec.get("style", "Normal"),
            bold=spec.get("bold", False),
            italic=spec.get("italic", False),
        )
    if kind == "bullet":
        p = _new_paragraph(doc, spec.get("text", ""), "List Paragraph")
        _apply_numbering(p, spec.get("num_id") or style_cache.bullet_num_id(), spec.get("ilvl", 0))
        return p
    if kind == "caption":
        return _new_paragraph(
            doc,
            spec.get("text", ""),
            "Caption" if _style_or_none(doc, "Caption") else "Normal",
            italic=True,
            align="center",
        )
    if kind == "code":
        p = _new_paragraph(doc, spec.get("text", ""), "Normal")
        for r in p.runs:
            r.font.name = "Consolas"
            r.font.size = Pt(8.5)
        return p
    if kind == "table":
        return _new_table(doc, spec["rows"], spec.get("style", "Table Grid"), spec.get("widths"))
    if kind == "image":
        return _new_image(doc, spec["path"], spec.get("width", 6.1))
    raise ValueError(f"type không hợp lệ: {kind}")


def _element(block):
    return block._p if isinstance(block, Paragraph) else block._tbl


def _detach(block):
    el = _element(block)
    el.getparent().remove(el)
    return el


# --------------------------------------------------------------------------- #
# ops — each returns a short human-readable note; raises a BrdOpError subclass
# on failure (caught uniformly by `apply_ops`).
# --------------------------------------------------------------------------- #
def op_replace_body(doc: _Doc, sec: Section, content: list[dict], style_cache: StyleCache) -> str:
    own = _own_body(doc, sec)
    heading_el = _element(blocks(doc)[sec.heading_idx])
    for b in own:
        _detach(b)
    new_els = [_element(build_block(doc, spec, style_cache)) for spec in content]
    cursor = heading_el
    for el in new_els:
        el.getparent().remove(el)
        cursor.addnext(el)
        cursor = el
    return f"đã thay toàn bộ thân riêng ({len(own)} -> {len(new_els)} block)"


def op_append_body(doc: _Doc, sec: Section, content: list[dict], style_cache: StyleCache) -> str:
    own = _own_body(doc, sec)
    heading_el = _element(blocks(doc)[sec.heading_idx])
    cursor = _element(own[-1]) if own else heading_el
    new_els = [_element(build_block(doc, spec, style_cache)) for spec in content]
    for el in new_els:
        el.getparent().remove(el)
        cursor.addnext(el)
        cursor = el
    return f"đã thêm {len(new_els)} block vào cuối thân"


def op_insert_blocks(
    doc: _Doc, sec: Section, at: str, position: str, content: list[dict], style_cache: StyleCache
) -> str:
    ordinal, own = resolve_block_ref(doc, sec, at)
    anchor_el = _element(own[ordinal])
    new_els = [_element(build_block(doc, spec, style_cache)) for spec in content]
    if position == "before":
        for el in new_els:
            el.getparent().remove(el)
            anchor_el.addprevious(el)
    else:
        cursor = anchor_el
        for el in new_els:
            el.getparent().remove(el)
            cursor.addnext(el)
            cursor = el
    return f"đã chèn {len(new_els)} block {position or 'after'} {at}"


def op_replace_block(doc: _Doc, sec: Section, at: str, content: list[dict], style_cache: StyleCache) -> str:
    ordinal, own = resolve_block_ref(doc, sec, at)
    old_el = _element(own[ordinal])
    new_els = [_element(build_block(doc, spec, style_cache)) for spec in content]
    for el in new_els:
        el.getparent().remove(el)
        old_el.addprevious(el)
    old_el.getparent().remove(old_el)
    return f"đã thay {at} bằng {len(new_els)} block"


def op_delete_blocks(doc: _Doc, sec: Section, at: str, to: Optional[str]) -> str:
    ordinal_from, own = resolve_block_ref(doc, sec, at)
    ordinal_to = ordinal_from
    if to:
        ordinal_to, _own2 = resolve_block_ref(doc, sec, to)
    if ordinal_to < ordinal_from:
        raise ValueError("'to' phải ở sau 'at'.")
    for b in own[ordinal_from : ordinal_to + 1]:
        _detach(b)
    return f"đã xoá {ordinal_to - ordinal_from + 1} block"


def op_set_table(tbl: Table, rows: list[list[str]]) -> str:
    if not tbl.rows:
        raise ValueError("Bảng không có dòng nào để dùng làm mẫu định dạng.")
    if not rows:
        raise ValueError("set_table cần ít nhất 1 dòng (header).")
    ncols = len(tbl.columns)
    template_tr = copy.deepcopy(tbl.rows[-1]._tr)
    for tr in list(tbl._tbl.findall(qn("w:tr"))):
        tbl._tbl.remove(tr)
    for ri, data in enumerate(rows):
        tbl._tbl.append(copy.deepcopy(template_tr))
        row = tbl.rows[-1]
        for ci in range(len(row.cells)):
            _set_cell_text(row.cells[ci], data[ci] if ci < len(data) else "", bold=(ri == 0))
    note = f"đã ghi {len(rows)} dòng x {ncols} cột"
    dropped = max((len(d) for d in rows), default=0) - ncols
    if dropped > 0:
        note += f" (CẢNH BÁO: {dropped} cột dữ liệu bị bỏ vì bảng chỉ có {ncols} cột)"
    return note


def op_set_cell(tbl: Table, row: Optional[int], col: Optional[int], value: Optional[str]) -> str:
    if row is None or col is None:
        raise ValueError("set_cell cần row và col.")
    if row >= len(tbl.rows) or col >= len(tbl.columns):
        raise ValueError(f"Bảng chỉ có {len(tbl.rows)} dòng x {len(tbl.columns)} cột.")
    _set_cell_text(tbl.rows[row].cells[col], value or "", bold=(row == 0))
    return f"đã ghi ô [{row}][{col}]"


def op_append_row(tbl: Table, row_values: Optional[list[str]]) -> str:
    if not tbl.rows:
        raise ValueError("Bảng rỗng — dùng set_table trước.")
    template_tr = copy.deepcopy(tbl.rows[-1]._tr)
    tbl._tbl.append(template_tr)
    row = tbl.rows[-1]
    for ci in range(len(row.cells)):
        _set_cell_text(row.cells[ci], row_values[ci] if row_values and ci < len(row_values) else "")
    return f"đã thêm dòng {len(tbl.rows) - 1}"


def op_delete_row(tbl: Table, row: Optional[int]) -> str:
    if row is None or row >= len(tbl.rows):
        raise ValueError(f"Bảng chỉ có {len(tbl.rows)} dòng.")
    if len(tbl.rows) <= 1:
        raise ValueError("Không thể xoá dòng cuối cùng của bảng — dùng delete_blocks để xoá cả bảng.")
    tbl._tbl.remove(tbl.rows[row]._tr)
    return f"đã xoá dòng {row}"


def op_replace_image(
    doc: _Doc, sec: Section, at: str, image_path: Optional[str], image_width: Optional[float]
) -> str:
    ordinal, own = resolve_block_ref(doc, sec, at)
    old = own[ordinal]
    if not isinstance(old, Paragraph) or not old._p.findall(".//" + qn("a:blip")):
        raise BlockAddressError(f"'{at}' không phải block ảnh.")
    if not image_path:
        raise ValueError("replace_image cần image_path.")
    new_p = _new_image(doc, image_path, image_width or 6.1)
    new_el = _element(new_p)
    new_el.getparent().remove(new_el)
    old_el = _element(old)
    old_el.addprevious(new_el)
    old_el.getparent().remove(old_el)
    return f"đã thay ảnh tại {at}"


def op_rename_heading(doc: _Doc, sec: Section, new_title: Optional[str]) -> str:
    if not new_title or not new_title.strip():
        raise ValueError("rename_heading cần new_title.")
    heading_p = blocks(doc)[sec.heading_idx]
    for r in list(heading_p.runs[1:]):
        r.text = ""
    if heading_p.runs:
        heading_p.runs[0].text = new_title
    else:
        heading_p.add_run(new_title)
    return f"đã đổi tiêu đề '{sec.title}' -> '{new_title}' (id của mục và mục con sẽ đổi ở lần đọc kế tiếp)"


def op_insert_section(
    doc: _Doc,
    sec: Section,
    where: str,
    title: Optional[str],
    level: Optional[int],
    content: Optional[list[dict]],
    style_cache: StyleCache,
) -> str:
    if not title or level is None:
        raise ValueError("insert_section cần title và level.")
    bs = blocks(doc)
    if where == "first_child":
        anchor_el = (
            _element(bs[sec.own_start]) if sec.own_end >= sec.own_start else _element(bs[sec.heading_idx])
        )
        side = "before" if sec.own_end >= sec.own_start else "after"
    elif where == "last_child":
        anchor_el = (
            _element(bs[sec.sub_end]) if sec.sub_end >= sec.sub_start else _element(bs[sec.heading_idx])
        )
        side = "after"
    elif where == "before":
        anchor_el = _element(bs[sec.heading_idx])
        side = "before"
    else:  # "after" — after the whole subtree, as a sibling
        anchor_el = _element(bs[sec.sub_end]) if sec.sub_end >= 0 else _element(bs[sec.heading_idx])
        side = "after"

    heading_p = _insert_heading(doc, style_cache, title, level)
    els = [_element(heading_p)] + [_element(build_block(doc, spec, style_cache)) for spec in (content or [])]
    for el in els:
        el.getparent().remove(el)
    if side == "before":
        for el in els:
            anchor_el.addprevious(el)
    else:
        cursor = anchor_el
        for el in els:
            cursor.addnext(el)
            cursor = el
    return f"đã chèn mục mới '{title}' (L{level}) {where} '{sec.section_id}'"


def op_delete_section(doc: _Doc, sec: Section, cascade: Optional[bool]) -> str:
    if sec.children and not cascade:
        raise CascadeRequiredError(
            f"delete_section('{sec.section_id}') có {len(sec.children)} mục con "
            f"({', '.join(sec.children)}). Gửi lại với cascade=true nếu thật sự muốn xoá cả "
            f"{1 + len(sec.children)} mục, hoặc xoá từng mục con trước."
        )
    bs = blocks(doc)
    if sec.sub_end >= sec.sub_start:
        for b in bs[sec.sub_start : sec.sub_end + 1]:
            _detach(b)
    _detach(bs[sec.heading_idx])
    return f"đã xoá mục '{sec.section_id}'" + (
        f" (cascade: {len(sec.children)} mục con)" if sec.children else ""
    )


# --------------------------------------------------------------------------- #
# dispatcher + batch application
# --------------------------------------------------------------------------- #
def _apply_one(doc: _Doc, sections: list[Section], style_cache: StyleCache, op: dict) -> str:
    kind = op.get("op")
    ref = op.get("section")
    if not ref:
        raise ValueError("Thiếu 'section'.")
    sec = resolve_section_ref(sections, ref)
    _check_expect(sec, op.get("expect"))

    if kind == "replace_body":
        return op_replace_body(doc, sec, op.get("content") or [], style_cache)
    if kind == "append_body":
        return op_append_body(doc, sec, op.get("content") or [], style_cache)
    if kind == "insert_blocks":
        return op_insert_blocks(
            doc, sec, op.get("at"), op.get("position") or "after", op.get("content") or [], style_cache
        )
    if kind == "replace_block":
        return op_replace_block(doc, sec, op.get("at"), op.get("content") or [], style_cache)
    if kind == "delete_blocks":
        return op_delete_blocks(doc, sec, op.get("at"), op.get("to"))
    if kind in ("set_table", "set_cell", "append_row", "delete_row"):
        ordinal, own = resolve_block_ref(doc, sec, op.get("at"))
        tbl = own[ordinal]
        if not isinstance(tbl, Table):
            raise BlockAddressError(f"'{op.get('at')}' không phải bảng trong '{sec.section_id}'.")
        if kind == "set_table":
            return op_set_table(tbl, op.get("rows") or [])
        if kind == "set_cell":
            return op_set_cell(tbl, op.get("row"), op.get("col"), op.get("value"))
        if kind == "append_row":
            return op_append_row(tbl, op.get("row_values"))
        return op_delete_row(tbl, op.get("row"))
    if kind == "replace_image":
        return op_replace_image(doc, sec, op.get("at"), op.get("image_path"), op.get("image_width"))
    if kind == "rename_heading":
        return op_rename_heading(doc, sec, op.get("title"))
    if kind == "insert_section":
        return op_insert_section(
            doc,
            sec,
            op.get("where") or "after",
            op.get("title"),
            op.get("level"),
            op.get("content"),
            style_cache,
        )
    if kind == "delete_section":
        return op_delete_section(doc, sec, op.get("cascade"))
    raise ValueError(f"op không hợp lệ: {kind}")


def apply_ops(doc: _Doc, ops: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    """Applies ops one at a time, re-indexing between each (an insert/delete
    shifts every subsequent block position). Returns (succeeded_ops, applied
    notes, failed notes) — a failed op never aborts the rest of the batch here;
    `apply_brd_ops` decides whether the WHOLE batch gets reverted afterwards."""
    succeeded: list[dict] = []
    applied: list[str] = []
    failed: list[str] = []
    style_cache = StyleCache(doc)
    for op in ops:
        try:
            _, sections = index_document(doc)
            note = _apply_one(doc, sections, style_cache, op)
            succeeded.append(op)
            applied.append(f"{op.get('op')} {op.get('section')}: {note}")
        except BrdOpError as exc:
            failed.append(f"{op.get('op')} {op.get('section')}: {exc}")
    return succeeded, applied, failed


# --------------------------------------------------------------------------- #
# semantic-preservation guard — the .docx analogue of edit_drawio's
# _semantic_loss_diff (backend/src/tools/rendering_tools.py:1628).
# --------------------------------------------------------------------------- #
def _headings_missing_numbering(doc: _Doc) -> list[str]:
    bad = []
    for p in doc.paragraphs:
        lv = heading_level(p)
        if lv is None or not p.text.strip():
            continue
        pPr = p._p.find(qn("w:pPr"))
        numPr = pPr.find(qn("w:numPr")) if pPr is not None else None
        if numPr is None:
            bad.append(p.text.strip()[:40])
    return bad


def _collect_subtree_ids(by_id: dict[str, Section], root_id: str) -> set[str]:
    """Every descendant id of `root_id` (NOT including root_id itself), walking
    `children` recursively — a cascade delete_section (or a rename_heading,
    which re-derives the whole renamed subtree's ids on next index) affects
    the FULL subtree, not just direct children."""
    out: set[str] = set()
    root = by_id.get(root_id)
    stack = list(root.children) if root is not None else []
    while stack:
        cid = stack.pop()
        if cid in out:
            continue
        out.add(cid)
        child = by_id.get(cid)
        if child is not None:
            stack.extend(child.children)
    return out


def check_semantic_preservation(
    before_bytes: bytes,
    before_sections: list[Section],
    after_bytes: bytes,
    after_sections: list[Section],
    *,
    ops: list[dict],
) -> list[str]:
    findings: list[str] = []

    with zipfile.ZipFile(io.BytesIO(before_bytes)) as za, zipfile.ZipFile(io.BytesIO(after_bytes)) as zb:
        for name in _STYLE_PARTS_MUST_MATCH:
            in_a, in_b = name in za.namelist(), name in zb.namelist()
            if in_a != in_b:
                findings.append(f"{name} bị thêm/xoá")
            elif in_a and za.read(name) != zb.read(name):
                findings.append(f"{name} bị thay đổi — vi phạm bất biến style/numbering")

    before_ids = {s.section_id for s in before_sections}
    after_ids = {s.section_id for s in after_sections}
    before_by_id = _sections_by_id(before_sections)

    expected_deleted: set[str] = set()
    # rename_heading legitimately changes the renamed section's id (and every
    # descendant's, since parent_id cascades) — see op_rename_heading's own
    # note. heading_idx is stable across a pure text rename (no blocks move),
    # so match old ids to their new id by POSITION instead of treating the
    # churn as an unexpected loss.
    renamed_old_ids: set[str] = set()
    renamed_heading_idxs: set[int] = set()
    n_insert = 0
    for op in ops:
        if op.get("op") == "delete_section":
            sid = op.get("section", "")
            expected_deleted.add(sid)
            if op.get("cascade"):
                expected_deleted.update(_collect_subtree_ids(before_by_id, sid))
        elif op.get("op") == "insert_section":
            n_insert += 1
        elif op.get("op") == "rename_heading":
            sid = op.get("section", "")
            sec = before_by_id.get(sid)
            if sec is not None:
                renamed_old_ids.add(sid)
                renamed_old_ids.update(_collect_subtree_ids(before_by_id, sid))
                renamed_heading_idxs.add(sec.heading_idx)
                for cid in _collect_subtree_ids(before_by_id, sid):
                    csec = before_by_id.get(cid)
                    if csec is not None:
                        renamed_heading_idxs.add(csec.heading_idx)

    unexpected_missing = (before_ids - after_ids) - expected_deleted - renamed_old_ids
    if unexpected_missing:
        findings.append(f"Mất mục ngoài dự kiến: {sorted(unexpected_missing)}")

    after_by_heading_idx = {s.heading_idx: s.section_id for s in after_sections}
    renamed_new_ids = {after_by_heading_idx[h] for h in renamed_heading_idxs if h in after_by_heading_idx}
    unexpected_new = (after_ids - before_ids) - renamed_new_ids
    if len(unexpected_new) != n_insert:
        findings.append(f"Số mục mới ({len(unexpected_new)}) không khớp số op insert_section ({n_insert})")

    own_before = {s.section_id: s.own_checksum for s in before_sections}
    own_after = {s.section_id: s.own_checksum for s in after_sections}
    touched = {op.get("section") for op in ops}
    for sid, chk in own_after.items():
        if sid in own_before and own_before[sid] != chk and sid not in touched:
            findings.append(f"Mục '{sid}' đổi checksum ngoài dự kiến (không nằm trong batch)")

    after_doc = Document(io.BytesIO(after_bytes))
    bad_numbering = _headings_missing_numbering(after_doc)
    if bad_numbering:
        findings.append(f"{len(bad_numbering)} heading mất đánh số tự động: {bad_numbering[:5]}")

    return findings


# --------------------------------------------------------------------------- #
# snapshot + atomic apply
# --------------------------------------------------------------------------- #
def snapshot(revisions_dir: Path, src: Path, *, keep: int = 20) -> Path:
    revisions_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(revisions_dir.glob("REV-*.docx"), key=lambda p: int(p.stem.split("-")[1]))
    n = (int(existing[-1].stem.split("-")[1]) + 1) if existing else 0
    dest = revisions_dir / f"REV-{n}.docx"
    shutil.copyfile(src, dest)
    existing.append(dest)
    for stale in existing[:-keep]:
        stale.unlink(missing_ok=True)
    return dest


@dataclass
class BrdApplyResult:
    ok: bool
    applied: list[str]
    failed: list[str]
    reverted: bool
    revert_reasons: list[str]
    revision_path: Optional[Path] = None


def apply_brd_ops(src: Path, ops: list[dict], *, revisions_dir: Optional[Path] = None) -> BrdApplyResult:
    """Snapshot -> apply in memory -> validate -> atomic write, or revert with
    the live file never touched (see docs/plans/2026-07-29-brd-agent.md §C3)."""
    before_bytes = src.read_bytes()
    _, before_sections = index_document(io.BytesIO(before_bytes))
    rev_path = snapshot(revisions_dir, src) if revisions_dir is not None else None

    doc = Document(io.BytesIO(before_bytes))
    succeeded, applied, failed = apply_ops(doc, ops)
    if not succeeded:
        return BrdApplyResult(
            ok=False,
            applied=applied,
            failed=failed,
            reverted=False,
            revert_reasons=[],
            revision_path=rev_path,
        )

    buf = io.BytesIO()
    doc.save(buf)
    after_bytes = buf.getvalue()
    _, after_sections = index_document(io.BytesIO(after_bytes))

    loss = check_semantic_preservation(
        before_bytes, before_sections, after_bytes, after_sections, ops=succeeded
    )
    if loss:
        return BrdApplyResult(
            ok=False,
            applied=[],
            failed=failed + [f"TOÀN BỘ BATCH BỊ HOÀN TÁC: {r}" for r in loss],
            reverted=True,
            revert_reasons=loss,
            revision_path=rev_path,
        )

    tmp = src.with_suffix(src.suffix + ".tmp")
    tmp.write_bytes(after_bytes)
    os.replace(tmp, src)
    return BrdApplyResult(
        ok=True, applied=applied, failed=failed, reverted=False, revert_reasons=[], revision_path=rev_path
    )


def outline(path) -> list[dict]:
    _, sections = index_document(path)
    return [s.to_dict() for s in sections]


def _section_text(doc: _Doc, sec: Section) -> str:
    own = _own_body(doc, sec)
    lines = []
    for b in own:
        if isinstance(b, Table):
            lines.extend(_cell_texts(b))
        else:
            t = b.text.strip()
            if t:
                lines.append(t)
    return "\n".join(lines)


def preview_ops(path_or_bytes, ops: list[dict]) -> dict:
    """Simulate `ops` in-memory WITHOUT touching disk — the diff source for the
    edit_brd_section approval card (docs/plans/2026-07-29-brd-agent.md §E3).
    interrupt_on pauses BEFORE the tool body runs, so the card must compute
    "what would change" itself from the raw args rather than trust the model's
    own description of the edit.

    Returns {"sections": [{"section_id", "before", "after"}], "applied", "failed"}
    — `before`/`after` are the touched section's own-body text (one line per
    block) BEFORE and AFTER the ops, for the caller to line-diff. A section
    that fails to resolve (bad ref) or whose op fails is simply omitted from
    `sections`; `failed` carries the raw error notes."""
    raw = path_or_bytes.read_bytes() if isinstance(path_or_bytes, Path) else path_or_bytes

    doc_before = Document(io.BytesIO(raw))
    _, sections_before = index_document(doc_before)
    by_id_before = _sections_by_id(sections_before)

    touched_ids: list[str] = []
    for op in ops:
        try:
            sec = resolve_section_ref(sections_before, op.get("section", ""))
        except BrdOpError:
            continue
        if sec.section_id not in touched_ids:
            touched_ids.append(sec.section_id)

    before_text = {sid: _section_text(doc_before, by_id_before[sid]) for sid in touched_ids}

    doc_after = Document(io.BytesIO(raw))
    _succeeded, applied, failed = apply_ops(doc_after, ops)
    _, sections_after = index_document(doc_after)
    by_id_after = _sections_by_id(sections_after)

    sections_out = [
        {
            "section_id": sid,
            "before": before_text.get(sid, ""),
            "after": _section_text(doc_after, by_id_after[sid]),
        }
        for sid in touched_ids
        if sid in by_id_after
    ]
    return {"sections": sections_out, "applied": applied, "failed": failed}
