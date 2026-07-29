# -*- coding: utf-8 -*-
"""Dựng file BRD v1.1 từ template bằng thư viện docx_edit.

Chạy:  python3 build_brd_v1.1.py
Kết quả: out/BRD_Diagram_Code_Agent_v1.1.docx
"""
import os
import shutil

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

import docx_edit as de
import brd_content as C

TEMPLATE = "template.docx"
OUT_DIR = "out"
OUT = os.path.join(OUT_DIR, "BRD_Diagram_Code_Agent_v1.1.docx")

os.makedirs(OUT_DIR, exist_ok=True)
shutil.copy(TEMPLATE, OUT)


# ───────────────────────── 1. Trang bìa & trang phê duyệt ─────────────────
def set_paragraph_text(doc, idx, text, keep_format_from_run=0):
    """Đổi nội dung một đoạn, giữ nguyên định dạng của run đầu tiên."""
    bs = de.blocks(doc)
    p = bs[idx]
    if not p.runs:
        p.add_run(text)
        return
    p.runs[keep_format_from_run].text = text
    for r in p.runs[keep_format_from_run + 1:]:
        r.text = ""


doc = Document(OUT)
set_paragraph_text(doc, 0, C.PROJECT)
set_paragraph_text(doc, 16, "BUSINESS REQUIREMENTS DOCUMENT")
set_paragraph_text(doc, 18, C.AUTHOR)
set_paragraph_text(doc, 20, C.DATE)
set_paragraph_text(doc, 22, C.VERSION)
set_paragraph_text(
    doc, 26,
    "Tôi đã xem xét kỹ tài liệu đặc tả yêu cầu nghiệp vụ (Business Requirements Document) "
    "của dự án Diagram Code Agent.",
)

# bảng VERSION HISTORY (bảng đầu tiên của tài liệu)
vh = doc.tables[0]
rows = [
    ["0.1.0", "—", "20/07/2026", "Bản nháp đầu tiên: khung tài liệu và phạm vi", "Huy Mai"],
    ["0.9.0", "—", "25/07/2026", "Bổ sung FR01–FR07 và toàn bộ yêu cầu phi chức năng", "Huy Mai"],
    ["1.0.0", "", "28/07/2026",
     "Bổ sung FR08–FR09 (module BRD Agent), 8 sơ đồ phân tích và danh sách vấn đề tồn đọng",
     "Huy Mai"],
    ["1.1.0", "", "29/07/2026",
     "Đối chiếu lại với mã nguồn và 59 workspace đã chạy: sửa số cổng HITL (13, không phải "
     "12), ngân sách web search (10, không phải 3), cơ chế engineer loop (ba tầng); bổ sung "
     "FR13-FR14, 8 sequence/state-machine/ERD diagram dogfood từ chính engine sản phẩm, bảng "
     "gate registry và ngân sách hợp nhất; sửa NFR hiệu năng theo số đo thật; thêm 3 issue mới",
     "Huy Mai"],
]
for ri, data in enumerate(rows):
    row = vh.rows[ri + 2]
    for ci, val in enumerate(data):
        cell = row.cells[ci]
        cell.text = ""
        r = cell.paragraphs[0].add_run(val)
        r.font.size = Pt(9)

# đánh dấu trường mục lục là "bẩn" để Word tự cập nhật khi mở
for fld in doc.element.body.iter(qn("w:fldChar")):
    if fld.get(qn("w:fldCharType")) == "begin":
        fld.set(qn("w:dirty"), "true")
doc.save(OUT)
print("✓ trang bìa, memo phê duyệt, version history")


# ───────────────────── 2. Xoá 2 FR mẫu của template ───────────────────────
for sid in ["fr1-lap-hop-dong", "fr2-gui-hop-dong"]:
    de.delete_section(OUT, sid)
print("✓ đã gỡ FR mẫu của template")


# ───────────────────── 3. Điền nội dung từng section ──────────────────────
for sid, content in C.SECTIONS.items():
    de.replace_section(OUT, sid, content)
    print(f"  · {sid}: {len(content)} block")

# ───────────────────── 4. Chèn 12 FR vào chương 3 ─────────────────────────
de.append_to_section(OUT, "functional-requirements-list", C.FR_BLOCKS)
print(f"✓ đã chèn {len(C.FR_LIST)} yêu cầu chức năng ({len(C.FR_BLOCKS)} block)")


# ───────────────────── 5. Kiểm tra lại bản đồ anchor ──────────────────────
secs = de.outline(OUT)
print(f"\n✓ Hoàn tất: {OUT}")
print(f"  tổng số section: {len(secs)}")
print(f"  tổng số bảng   : {sum(s['n_tables'] for s in secs)}")
print(f"  tổng số hình   : {sum(s['n_images'] for s in secs)}")
