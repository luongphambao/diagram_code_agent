"""docx_edit — thư viện chỉnh sửa .docx theo TỪNG SECTION (không gen lại toàn bộ).

Đây là bản prototype của nhóm tool mà BRD Agent sẽ gọi:
    index_document      -> anchor_map.json   (bản đồ section + checksum)
    read_section        -> đọc nội dung 1 section
    replace_section     -> thay toàn bộ thân 1 section
    append_to_section   -> chèn thêm block vào cuối 1 section
    insert_section_after-> thêm section mới sau 1 section
    delete_section      -> xoá 1 section (kèm nội dung)
    set_table           -> ghi lại dữ liệu 1 bảng theo chỉ số bảng trong section

Nguyên tắc:
- Không đụng tới styles.xml / numbering.xml / header-footer / trường TOC của template.
- Mọi block mới đều mượn style có sẵn trong template  -> giữ nguyên nhận diện thương hiệu.
- Mỗi section có checksum; ghi đè khi checksum lệch sẽ bị từ chối (optimistic locking).
"""
from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass, field, asdict

from docx import Document
from docx.document import Document as _Doc
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.enum.text import WD_ALIGN_PARAGRAPH

HEADING_RE = re.compile(r"^(Heading|Appendix)\s*(\d*)$")


# ───────────────────────────── block helpers ──────────────────────────────
def iter_blocks(doc: _Doc):
    """Duyệt body theo đúng thứ tự tài liệu, trả về (index, Paragraph|Table)."""
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


def heading_level(block) -> int | None:
    """Trả về cấp heading (1..9) hoặc None nếu không phải heading."""
    if not isinstance(block, Paragraph):
        return None
    name = (block.style.name or "").strip()
    m = HEADING_RE.match(name)
    if not m:
        return None
    if name.startswith("Appendix"):
        return 1
    return int(m.group(2)) if m.group(2) else 1


def slugify(text: str) -> str:
    import unicodedata
    t = text.lower().strip().replace("đ", "d")
    t = "".join(c for c in unicodedata.normalize("NFD", t)
                if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:60] or "section"


# ───────────────────────────── section index ──────────────────────────────
@dataclass
class Section:
    section_id: str
    title: str
    level: int
    heading_idx: int          # vị trí block của dòng heading
    start_idx: int            # block đầu tiên của phần thân
    end_idx: int              # block cuối cùng của phần thân (inclusive); -1 nếu rỗng
    n_paragraphs: int = 0
    n_tables: int = 0
    n_images: int = 0
    checksum: str = ""
    parent_id: str | None = None
    path: str = ""            # ví dụ "3 > 3.2 > 3.2.1"

    def to_dict(self):
        return asdict(self)


def _block_text(b) -> str:
    if isinstance(b, Paragraph):
        return b.text
    return "\n".join("\t".join(c.text for c in r.cells) for r in b.rows)


def _count_images(b) -> int:
    if isinstance(b, Paragraph):
        return len(b._p.findall(".//" + qn("a:blip")))
    return 0


def index_document(path_or_doc) -> tuple[_Doc, list[Section]]:
    """Xây bản đồ anchor. Trả về (document, danh sách Section)."""
    doc = path_or_doc if isinstance(path_or_doc, _Doc) else Document(path_or_doc)
    bs = blocks(doc)
    heads: list[tuple[int, int, str]] = []      # (block_idx, level, title)
    for i, b in enumerate(bs):
        lv = heading_level(b)
        if lv is not None and b.text.strip():
            heads.append((i, lv, b.text.strip()))

    sections: list[Section] = []
    used: dict[str, int] = {}
    stack: list[Section] = []
    for n, (idx, lv, title) in enumerate(heads):
        # thân section kéo dài tới heading tiếp theo có cấp <= cấp hiện tại
        end = len(bs) - 1
        for j in range(n + 1, len(heads)):
            if heads[j][1] <= lv:
                end = heads[j][0] - 1
                break
        start = idx + 1
        sid = slugify(title)
        if sid in used:
            used[sid] += 1
            sid = f"{sid}-{used[sid]}"
        else:
            used[sid] = 1

        body = bs[start:end + 1] if end >= start else []
        digest = hashlib.sha256(
            ("\n".join(_block_text(b) for b in body)).encode("utf-8")
        ).hexdigest()[:16]

        while stack and stack[-1].level >= lv:
            stack.pop()
        parent = stack[-1].section_id if stack else None
        path = (stack[-1].path + " > " if stack else "") + title

        s = Section(
            section_id=sid, title=title, level=lv, heading_idx=idx,
            start_idx=start, end_idx=end if end >= start else -1,
            n_paragraphs=sum(1 for b in body if isinstance(b, Paragraph)),
            n_tables=sum(1 for b in body if isinstance(b, Table)),
            n_images=sum(_count_images(b) for b in body),
            checksum=digest, parent_id=parent, path=path,
        )
        sections.append(s)
        stack.append(s)
    return doc, sections


def find(sections: list[Section], section_id: str) -> Section:
    for s in sections:
        if s.section_id == section_id:
            return s
    # cho phép tra theo tiêu đề gần đúng
    for s in sections:
        if slugify(s.title) == slugify(section_id) or s.title.strip() == section_id.strip():
            return s
    raise KeyError(f"Không tìm thấy section '{section_id}'. "
                   f"Các id hợp lệ: {[s.section_id for s in sections][:40]}")


# ───────────────────────── xây block từ đặc tả JSON ───────────────────────
def _style_or_none(doc, name):
    try:
        doc.styles[name]
        return name
    except KeyError:
        return None


# numId của danh sách bullet trong template (dò được bằng detect_bullet_num_id)
BULLET_NUM_ID = 10


def detect_bullet_num_id(doc: _Doc, default: int = 10) -> int:
    """Dò numId của danh sách bullet đang dùng trong template."""
    for p in doc.paragraphs:
        if (p.style.name or "").startswith(("List", "bullet")):
            npr = p._p.find(qn("w:pPr"))
            npr = npr.find(qn("w:numPr")) if npr is not None else None
            if npr is not None:
                nid = npr.find(qn("w:numId"))
                if nid is not None:
                    return int(nid.get(qn("w:val")))
    return default


def _apply_numbering(p: Paragraph, num_id: int, ilvl: int = 0):
    from docx.oxml import OxmlElement
    pPr = p._p.get_or_add_pPr()
    numPr = OxmlElement("w:numPr")
    e_ilvl = OxmlElement("w:ilvl"); e_ilvl.set(qn("w:val"), str(ilvl))
    e_num = OxmlElement("w:numId"); e_num.set(qn("w:val"), str(num_id))
    numPr.append(e_ilvl); numPr.append(e_num)
    pPr.append(numPr)


_PPR_CACHE: dict = {}


def _borrow_heading_pPr(doc: _Doc, p: Paragraph, level: int):
    """Mượn nguyên `pPr` của một heading cùng cấp đã có trong template.

    Template thường ghi đè numbering ngay trên paragraph (numId riêng) thay vì
    chỉ dựa vào style; nếu không sao chép, heading mới sẽ mất số thứ tự.
    """
    key = (id(doc), level)
    exemplar = _PPR_CACHE.get(key)
    if exemplar is None:
        want = f"Heading {level}"
        for q in doc.paragraphs:
            if (q.style.name or "") == want and q._p is not p._p:
                pPr = q._p.find(qn("w:pPr"))
                if pPr is not None and pPr.find(qn("w:numPr")) is not None:
                    exemplar = copy.deepcopy(pPr)
                    # heading mới không tự ngắt trang
                    pb = exemplar.find(qn("w:pageBreakBefore"))
                    if pb is not None:
                        exemplar.remove(pb)
                    break
        if exemplar is None:
            return
        _PPR_CACHE[key] = exemplar
    old = p._p.find(qn("w:pPr"))
    if old is not None:
        p._p.remove(old)
    p._p.insert(0, copy.deepcopy(exemplar))


def _new_paragraph(doc: _Doc, text: str, style: str | None = None,
                   bold: bool = False, italic: bool = False,
                   align: str | None = None) -> Paragraph:
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


def _new_table(doc: _Doc, rows: list[list[str]], style: str = "Table Grid",
               header: bool = True, widths: list[float] | None = None) -> Table:
    ncols = max(len(r) for r in rows)
    t = doc.add_table(rows=len(rows), cols=ncols)
    if _style_or_none(doc, style):
        t.style = doc.styles[style]
    t.autofit = True
    for ri, row in enumerate(rows):
        for ci in range(ncols):
            cell = t.cell(ri, ci)
            cell.text = ""
            para = cell.paragraphs[0]
            run = para.add_run(str(row[ci]) if ci < len(row) else "")
            run.font.size = Pt(9)
            if header and ri == 0:
                run.bold = True
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


def build_block(doc: _Doc, spec: dict):
    """spec = {"type": "p"|"bullet"|"num"|"table"|"image"|"caption"|"code", ...}"""
    kind = spec.get("type", "p")
    if kind == "heading":
        lv = spec.get("level", 2)
        p = _new_paragraph(doc, spec["text"], f"Heading {lv}")
        _borrow_heading_pPr(doc, p, lv)
        return p
    if kind == "p":
        return _new_paragraph(doc, spec["text"], spec.get("style", "Normal"),
                              bold=spec.get("bold", False),
                              italic=spec.get("italic", False))
    if kind == "bullet":
        p = _new_paragraph(doc, spec["text"], "List Paragraph")
        _apply_numbering(p, spec.get("num_id", BULLET_NUM_ID), spec.get("ilvl", 0))
        return p
    if kind == "caption":
        return _new_paragraph(doc, spec["text"], "Caption" if _style_or_none(doc, "Caption") else "Normal",
                              italic=True, align="center")
    if kind == "code":
        p = _new_paragraph(doc, spec["text"], "Normal")
        for r in p.runs:
            r.font.name = "Consolas"
            r.font.size = Pt(8.5)
        return p
    if kind == "table":
        return _new_table(doc, spec["rows"], spec.get("style", "Table Grid"),
                          spec.get("header", True), spec.get("widths"))
    if kind == "image":
        return _new_image(doc, spec["path"], spec.get("width", 6.1))
    raise ValueError(f"type không hợp lệ: {kind}")


def _element(block):
    return block._p if isinstance(block, Paragraph) else block._tbl


def _detach(block):
    el = _element(block)
    el.getparent().remove(el)
    return el


# ───────────────────────────── các thao tác vá ────────────────────────────
def replace_section(path_or_doc, section_id: str, content: list[dict],
                    expect_checksum: str | None = None, save_as: str | None = None):
    """Thay TOÀN BỘ thân của một section bằng danh sách block mới.

    Heading, các section khác, style, header/footer, TOC đều không bị đụng tới.
    """
    doc, sections = index_document(path_or_doc)
    sec = find(sections, section_id)
    if expect_checksum and expect_checksum != sec.checksum:
        raise ValueError(
            f"Xung đột phiên bản ở '{section_id}': checksum hiện tại {sec.checksum}, "
            f"bên gọi mong đợi {expect_checksum}. Hãy index lại rồi thử lại."
        )
    bs = blocks(doc)
    anchor = _element(bs[sec.heading_idx])

    # 1) gỡ toàn bộ thân cũ
    if sec.end_idx >= sec.start_idx:
        for b in bs[sec.start_idx:sec.end_idx + 1]:
            _detach(b)

    # 2) dựng block mới (append cuối body) rồi di chuyển vào đúng chỗ
    new_els = [_element(build_block(doc, spec)) for spec in content]
    cursor = anchor
    for el in new_els:
        el.getparent().remove(el)
        cursor.addnext(el)
        cursor = el

    out = save_as or (path_or_doc if isinstance(path_or_doc, str) else None)
    if out:
        doc.save(out)
    return doc


def append_to_section(path_or_doc, section_id: str, content: list[dict],
                      save_as: str | None = None):
    """Chèn thêm block vào CUỐI thân section, giữ nguyên nội dung đang có."""
    doc, sections = index_document(path_or_doc)
    sec = find(sections, section_id)
    bs = blocks(doc)
    cursor = _element(bs[sec.end_idx if sec.end_idx >= 0 else sec.heading_idx])
    for spec in content:
        el = _element(build_block(doc, spec))
        el.getparent().remove(el)
        cursor.addnext(el)
        cursor = el
    out = save_as or (path_or_doc if isinstance(path_or_doc, str) else None)
    if out:
        doc.save(out)
    return doc


def insert_section_after(path_or_doc, after_section_id: str, title: str,
                         level: int, content: list[dict],
                         save_as: str | None = None):
    """Thêm một section mới (heading + thân) ngay sau section chỉ định."""
    doc, sections = index_document(path_or_doc)
    sec = find(sections, after_section_id)
    bs = blocks(doc)
    cursor = _element(bs[sec.end_idx if sec.end_idx >= 0 else sec.heading_idx])

    h = doc.add_paragraph(title, style=f"Heading {level}")
    els = [h._p] + [_element(build_block(doc, spec)) for spec in content]
    for el in els:
        el.getparent().remove(el)
        cursor.addnext(el)
        cursor = el
    out = save_as or (path_or_doc if isinstance(path_or_doc, str) else None)
    if out:
        doc.save(out)
    return doc


def delete_section(path_or_doc, section_id: str, save_as: str | None = None):
    doc, sections = index_document(path_or_doc)
    sec = find(sections, section_id)
    bs = blocks(doc)
    _detach(bs[sec.heading_idx])
    if sec.end_idx >= sec.start_idx:
        for b in bs[sec.start_idx:sec.end_idx + 1]:
            _detach(b)
    out = save_as or (path_or_doc if isinstance(path_or_doc, str) else None)
    if out:
        doc.save(out)
    return doc


def set_table(path_or_doc, section_id: str, table_ordinal: int,
              rows: list[list[str]], save_as: str | None = None):
    """Ghi lại dữ liệu cho bảng thứ `table_ordinal` (0-based) trong section.

    Giữ nguyên style bảng của template: nhân bản dòng mẫu thay vì tạo bảng mới.
    """
    doc, sections = index_document(path_or_doc)
    sec = find(sections, section_id)
    bs = blocks(doc)
    tables = [b for b in bs[sec.start_idx:sec.end_idx + 1] if isinstance(b, Table)]
    if table_ordinal >= len(tables):
        raise IndexError(f"Section '{section_id}' chỉ có {len(tables)} bảng.")
    t = tables[table_ordinal]

    template_row = copy.deepcopy(t.rows[-1]._tr)
    while len(t.rows) > 1:
        t._tbl.remove(t.rows[-1]._tr)
    # dòng 0 = header
    for ci, val in enumerate(rows[0]):
        if ci < len(t.rows[0].cells):
            cell = t.rows[0].cells[ci]
            cell.text = ""
            r = cell.paragraphs[0].add_run(str(val))
            r.bold = True
            r.font.size = Pt(9)
    for data in rows[1:]:
        tr = copy.deepcopy(template_row)
        t._tbl.append(tr)
        row = t.rows[-1]
        for ci in range(len(row.cells)):
            cell = row.cells[ci]
            cell.text = ""
            r = cell.paragraphs[0].add_run(str(data[ci]) if ci < len(data) else "")
            r.font.size = Pt(9)
    out = save_as or (path_or_doc if isinstance(path_or_doc, str) else None)
    if out:
        doc.save(out)
    return doc


def outline(path) -> list[dict]:
    """Bản đồ anchor rút gọn — chính là payload của tool `read_brd_outline`."""
    _, sections = index_document(path)
    return [s.to_dict() for s in sections]


if __name__ == "__main__":
    import json, sys
    print(json.dumps(outline(sys.argv[1]), ensure_ascii=False, indent=2))
