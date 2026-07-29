# Kế hoạch xây dựng luồng BRD Agent

**Dự án:** `diagram_code_agent` · **Phiên bản kế hoạch:** 1.0 · **Ngày:** 28/07/2026

---

## 1. Mục tiêu và ba nguyên tắc thiết kế

Bổ sung vào hệ thống một luồng sinh **tài liệu BRD dạng `.docx`** từ template chuẩn của công ty,
với yêu cầu bắt buộc: **sửa được từng phần, không sinh lại toàn bộ**.

Ba nguyên tắc chi phối toàn bộ thiết kế:

| # | Nguyên tắc | Hệ quả kỹ thuật |
|---|---|---|
| 1 | **Template là hợp đồng bất khả xâm phạm** | Không đụng `styles.xml`, `numbering.xml`, header/footer, trường TOC. Mọi block mới **mượn** `pPr` của một block cùng loại đã có trong template. |
| 2 | **Section là đơn vị nguyên tử** | Mọi thao tác ghi đều nhận `section_id` + `expect_checksum`. Không có API nào ghi cả file. |
| 3 | **Tái sử dụng tối đa hạ tầng sẵn có** | Dùng lại `assemble_report_data()`, CSM, cơ chế gate, middleware, eval harness. Chỉ thêm 1 subagent, 9 tool, 3 gate. |

> Tiền lệ trong chính repo: cặp `read_drawio` / `edit_drawio` đã áp dụng đúng mô hình
> "đọc bản kiểm kê → vá đúng phần tử → re-validate". BRD Agent là bản sao của mô hình đó
> cho OOXML thay vì XML của draw.io.

---

## 2. Vị trí trong kiến trúc hiện tại

```
main agent (35 tools)
├── icon_resolver      (7 tools)   — giữ nguyên
├── drawer             (8 tools)   — giữ nguyên
├── critic             (2 tools)   — giữ nguyên
├── wbs_planner        (4 tools)   — giữ nguyên
├── ppt_generator      (3 tools)   — giữ nguyên
└── brd_writer         (6 tools)   ← THÊM MỚI
```

**Tái sử dụng nguyên vẹn**

| Thành phần sẵn có | Dùng để làm gì |
|---|---|
| `domain/reporting/reporting.py::assemble_report_data()` | Gom `architecture_analysis / diagram_brief / tech_stack / blueprint / critique` + suy ra traceability, risk, executive points. Không đọc lại JSON thủ công. |
| `ppt_reporting.py::_enrich_report_from_csm()` | Backfill từ `solution_model.json` + `wbs.json` cho workspace kiểu CSM. |
| `memory/stores/csm_adapter.py` | Nguồn sự thật cho phần Functional Requirements (Requirement → Component → WorkItem). |
| `domain/wbs/wbs_schema.py` | Nguồn cho mục "Delivery plan / Assumptions". |
| `tools/__init__.py::GATE_TOOL_NAMES`, `GATE_DECISIONS`, `ROLE_GATE_PERMISSIONS` | Đăng ký 3 gate mới, không viết cơ chế HITL riêng. |
| `agent/middleware/phase_filter.py` | Thêm phase `brd` để lọc tool đúng giai đoạn. |
| `evals/_core.py` | Khung eval: dataset JSON + judge + baseline + tolerance 0.02. |

**Thêm mới**

```
backend/
├── src/
│   ├── domain/reporting/
│   │   ├── brd_docx.py            # lớp OOXML: index / patch / render  (~450 LOC)
│   │   └── brd_assembler.py       # ngữ cảnh → nội dung từng section    (~380 LOC)
│   ├── tools/analysis/brd_gates.py  # 9 tool, 3 trong đó là gate         (~420 LOC)
│   └── agent/subagents/brd_writer.py                                     (~35 LOC)
├── skills/brd-writing/
│   ├── SKILL.md
│   └── reference/{template-map.md, section-recipes.md, style-contract.md}
├── templates/brd_template.docx      # template chuẩn công ty
└── evals/brd/{dataset/*.json, judge.py, run_eval.py, baseline.json}
```

---

## 3. Artifact mới trong workspace

Giữ đúng triết lý hiện có: **trạng thái bền vững nằm ở file trong workspace, không nằm trong graph state.**

| File | Vai trò |
|---|---|
| `template_map.json` | Bản đồ anchor của **template gốc**: `section_id`, `title`, `level`, `heading_idx`, `[start,end]`, số bảng/hình, `checksum`. Tính một lần, cache theo hash của template. |
| `brd_outline.json` | Dàn ý đã phê duyệt: mỗi `section_id` ↦ `{source, content_kind, status, notes}`. Đây là artifact của GATE B1. |
| `brd_sections/<section_id>.json` | Nội dung đã soạn cho từng mục, dạng danh sách block. Tách file để sửa 1 mục không đụng mục khác. |
| `out.brd.docx` | Bản hiện hành. |
| `brd_revisions/REV-<n>.docx` | Ảnh chụp trước mỗi lần vá — phục vụ diff và hoàn tác. |
| `brd_patch_log.json` | Sổ chỉ-ghi-thêm: `{revision, section_id, operation, before_checksum, after_checksum, actor, approved_by, timestamp}`. |
| `brd_validation.json` | Kết quả linter cấu trúc gần nhất. |

Phase mới trong `phase_filter.py`, đặt **sau** `ppt`:

```python
# _PHASE_ORDER: intake < blueprint < draw < wbs < ppt < report < brd
# phát hiện phase: tồn tại out.brd.docx  → "brd"
#                  tồn tại brd_outline.json → "brd_draft"
```

---

## 4. Đặc tả subagent `brd_writer`

```python
# backend/src/agent/subagents/brd_writer.py
from .spec import SubagentSpec
from ..constants import BRD_CALL_LIMIT, BRD_SKILL_PATHS
from ...tools import BRD_WRITER_TOOLS

def build_brd_writer_spec(model_role="brd_writer") -> SubagentSpec:
    return SubagentSpec(
        name="brd_writer",
        description=(
            "Soạn và chỉnh sửa tài liệu BRD .docx từ template công ty. "
            "Chỉ được thao tác theo từng section; không bao giờ ghi đè cả file."
        ),
        model_role=model_role,
        tools=BRD_WRITER_TOOLS,       # 6 tool không-gate
        run_limit=BRD_CALL_LIMIT,     # 60
        skills=BRD_SKILL_PATHS,       # ["brd-writing"]
        use_vision_relay=False,       # không cần đọc ảnh
        permissions=[
            # chặn subagent ghi thẳng vào file .docx bằng filesystem builtin
            FilesystemPermission(deny="write", path="/workspace/out.brd.docx"),
            FilesystemPermission(deny="write", path="/workspace/brd_revisions/"),
        ],
    )
```

**Vì sao subagent riêng chứ không nhét vào main agent:** soạn 40 mục nội dung tốn rất nhiều
token; tách ra để (a) `ModelCallLimit` cô lập chi phí, (b) `usage.json` tách chi phí theo
`agent_name`, (c) main agent giữ context sạch để điều phối. Giống hệt lý do đã tách
`wbs_planner` và `ppt_generator`.

**Gate ở lại main agent** — đúng quy ước hiện tại: subagent không mở interrupt.

---

## 5. Đặc tả tool

### 5.1 Bảng tổng hợp

| # | Tool | Thuộc về | Gate | Mục đích |
|---|---|---|---|---|
| 1 | `load_brd_context` | brd_writer | | Gom ngữ cảnh từ CSM + report data thành một dict gọn |
| 2 | `inspect_brd_template` | brd_writer | | Lập/đọc `template_map.json` |
| 3 | `draft_brd_outline` | brd_writer | | Ghi `brd_outline.json` |
| 4 | `draft_section_content` | brd_writer | | Ghi `brd_sections/<id>.json` cho 1..n mục |
| 5 | `read_brd_outline` | brd_writer + main | | Đọc anchor map + checksum của **file hiện hành** |
| 6 | `validate_brd` | brd_writer + main | | Linter cấu trúc + traceability |
| 7 | `propose_brd_outline` | main | ✅ B1 | Trình dàn ý xin duyệt |
| 8 | `generate_brd_docx` | main | ✅ B2 | Kết xuất lần đầu `out.brd.docx` |
| 9 | `edit_brd_section` | main | ✅ B3 | Vá đúng 1 mục, tăng revision |

### 5.2 JSON schema (Pydantic — theo đúng khuôn `CoercingModel` của repo)

```python
# backend/src/tools/schemas/brd.py
from typing import Literal, Optional
from pydantic import Field
from .coercion import CoercingModel     # sửa arg JSON méo do mimo sinh ra

BlockKind = Literal["p", "bullet", "table", "image", "caption", "code", "heading"]

class Block(CoercingModel):
    type: BlockKind = "p"
    text: Optional[str]        = Field(None, description="Nội dung cho p/bullet/caption/code")
    rows: Optional[list[list[str]]] = Field(None, description="Dữ liệu bảng, dòng 0 là header")
    widths: Optional[list[float]]   = Field(None, description="Bề rộng cột (inch)")
    path: Optional[str]        = Field(None, description="Đường dẫn ảnh trong workspace")
    width: float               = Field(6.1, description="Bề rộng ảnh (inch)")
    bold: bool = False
    italic: bool = False
    level: int = Field(2, ge=1, le=3, description="Cấp heading khi type='heading'")

class OutlineItem(CoercingModel):
    section_id: str
    title: str
    level: int = Field(ge=1, le=3)
    source: Literal["csm","blueprint","techstack","wbs","diagram","manual","template"]
    content_kind: BlockKind = "p"
    status: Literal["fill","keep","skip"] = "fill"
    notes: str = ""

class BrdOutlineConfig(CoercingModel):
    """Args của propose_brd_outline — GATE B1"""
    title: str    = Field(description="Tên dự án trên trang bìa")
    subtitle: str = ""
    version: str  = "1.0.0"
    author: str   = ""
    language: Literal["vi","en","bilingual"] = "vi"
    items: list[OutlineItem] = Field(description="Toàn bộ mục của template kèm quyết định xử lý")
    skipped_reason: str = Field("", description="Bắt buộc nếu có mục status='skip'")

class BrdRenderConfig(CoercingModel):
    """Args của generate_brd_docx — GATE B2"""
    template: str = Field("brd_template.docx", description="Template trong backend/templates/")
    embed_figures: list[str] = Field(default_factory=list,
        description="Danh sách file ảnh trong workspace cần nhúng, ví dụ ['out.png']")
    refresh_toc: bool = True
    output_name: str = "out.brd.docx"

class BrdEditRequest(CoercingModel):
    """Args của edit_brd_section — GATE B3"""
    section_id: str = Field(description="Lấy từ read_brd_outline; không được đoán")
    operation: Literal["replace","append","insert_after","delete","set_table"] = "replace"
    expect_checksum: str = Field(description="Checksum đọc được ngay trước khi vá")
    content: list[Block] = Field(default_factory=list)
    table_ordinal: int = Field(0, description="Chỉ dùng cho operation='set_table'")
    new_title: Optional[str] = Field(None, description="Chỉ dùng cho operation='insert_after'")
    new_level: int = Field(2, description="Chỉ dùng cho operation='insert_after'")
    reason: str = Field(description="Lý do sửa — ghi vào brd_patch_log.json")
```

### 5.3 Hợp đồng trả về

Mọi tool trả **chuỗi văn bản** (đúng quy ước repo), kèm số liệu để model tự kiểm chứng:

```
read_brd_outline →
  "74 mục. Ví dụ: [1] introduction (L1, 0 bảng, chk=a3f1…) …
   Dùng chính xác section_id ở trên khi gọi edit_brd_section."

edit_brd_section →
  "✓ REV-3 · mục 'security' (4.3.3): replace · 1 bảng ↦ 1 bảng + 1 đoạn.
   73/74 mục khác giữ nguyên checksum. Đã lưu brd_revisions/REV-2.docx để hoàn tác."

edit_brd_section (xung đột) →
  "✗ Từ chối: checksum của 'security' hiện là 96b7…, bạn gửi 987f….
   Gọi lại read_brd_outline rồi thử lại — KHÔNG được bỏ qua expect_checksum."
```

---

## 6. Ba cổng HITL

Đăng ký vào `tools/__init__.py`:

```python
GATE_TOOL_NAMES = [..., "propose_brd_outline", "generate_brd_docx", "edit_brd_section"]

GATE_DECISIONS.update({
    "propose_brd_outline": ["approve", "approve_with_assumptions",
                            "request_alternative", "reject"],
    "generate_brd_docx":   ["approve", "reject"],
    "edit_brd_section":    ["approve", "request_alternative", "reject"],
})

ROLE_GATE_PERMISSIONS.update({
    "propose_brd_outline": {"ba", "lead", "admin"},
    "generate_brd_docx":   {"ba", "lead", "admin"},
    "edit_brd_section":    {"ba", "lead", "admin"},
})
```

| Gate | Thẻ giao diện | Người dùng thấy gì |
|---|---|---|
| **B1** `propose_brd_outline` | `brd_outline_approval` | Cây mục của template + nhãn `fill / keep / skip` + nguồn dữ liệu mỗi mục |
| **B2** `generate_brd_docx` | `brd_render_approval` | Danh sách mục sẽ điền, ảnh sẽ nhúng, cảnh báo linter, nút xem trước |
| **B3** `edit_brd_section` | `brd_edit_approval` | **Diff trước–sau ở mức đoạn văn** của đúng mục đó + số mục không đổi |

> **Lưu ý về `edit_brd_section` là gate:** ban đầu có thể thấy nặng nề, nhưng đây là thao tác
> ghi vào tài liệu sắp gửi khách hàng. Nếu muốn giảm ma sát, cho phép cấu hình
> `BRD_EDIT_AUTO_APPROVE=true` khi người dùng chính là tác giả (`actor == author`), giống
> cách `export_to_delivery` mặc định `dry_run`.

---

## 7. Cơ chế edit-in-place (phần lõi)

### 7.1 Ba lớp

```
Lớp 1 — INDEX      duyệt body theo thứ tự tài liệu (w:p / w:tbl xen kẽ)
                   heading = style khớp ^(Heading|Appendix)\s*\d*$
                   thân section = tới heading kế tiếp có level <= level hiện tại
                   checksum = sha256(text các block trong thân)[:16]

Lớp 2 — PATCH      replace | append | insert_after | delete | set_table
                   block mới build bằng doc.add_paragraph/add_table (append cuối body)
                   rồi di chuyển bằng lxml: anchor.addnext(el)

Lớp 3 — GUARD      expect_checksum lệch  → từ chối, buộc index lại
                   style contract        → pPr mượn từ exemplar cùng loại trong template
                   snapshot              → copy file sang brd_revisions/REV-n.docx trước khi ghi
```

### 7.2 Vì sao `python-docx` chứ không phải docx-js / unzip-sửa-XML

| Cách | Đánh giá |
|---|---|
| `docx-js` (npm) | **Không mở được file có sẵn** — chỉ tạo mới. Loại. |
| `unzip` → sửa `word/document.xml` bằng regex → `zip` | Được, nhưng Word chẻ text thành nhiều `w:r`; phải chạy `merge_runs` trước, và mọi thao tác chèn bảng/ảnh phải tự viết XML + quản lý `rels`. Rủi ro hỏng file cao. |
| **`python-docx` + thao tác lxml trực tiếp** ✅ | Giữ nguyên `styles.xml`/`numbering.xml`/`rels`; API bảng và ảnh có sẵn; vẫn xuống được tầng `_p` / `_tbl` để chèn đúng vị trí. **Đã có prototype chạy được** (`docx_edit.py`). |

### 7.3 Ba cạm bẫy đã gặp trong prototype — phải xử lý ngay từ đầu

1. **Heading mất số thứ tự.** Template ghi đè numbering **trên chính paragraph**
   (`numPr` với `numId=2`), không chỉ ở style. Heading mới tạo bằng `p.style = "Heading 2"`
   sẽ **không có số**. → phải deepcopy nguyên `pPr` của một heading cùng cấp đã có
   (hàm `_borrow_heading_pPr`), đồng thời gỡ `pageBreakBefore`.
2. **Bullet mất dấu chấm đầu dòng.** Style `List Paragraph` chỉ thụt lề; dấu bullet đến từ
   `numPr numId=10` gắn trực tiếp trên paragraph. → dò `numId` bullet của template rồi áp lại.
3. **TOC là field có cache.** Đặt `w:dirty="true"` để Word tự cập nhật khi mở là đủ cho Word,
   nhưng bản preview/PDF vẫn hiện mục lục cũ. → thêm bước kết xuất PDF (LibreOffice) → đọc
   **bookmark outline** để lấy số trang thật → ghi lại phần cache của field. Chạy **2 vòng**
   vì số dòng mục lục thay đổi làm lệch phân trang.

### 7.4 Bằng chứng đã kiểm chứng

`demo_edit.py` sửa mục *4.3.3 Security* trên tài liệu 74 mục:

```
Mục bị thay đổi : ['system-features-and-non-requirements',
                   'non-functional-requirements', 'security']
                   ← chỉ mục đích + 2 mục cha bao ngoài (đúng theo định nghĩa)
Mục mất / thêm  : [] / []
Vá lại bằng checksum cũ → bị từ chối đúng như thiết kế.
```

---

## 8. Danh sách thay đổi theo file (checklist tích hợp)

### Backend

| File | Thay đổi |
|---|---|
| `domain/reporting/brd_docx.py` | **mới** — `index_document`, `replace_section`, `append_to_section`, `insert_section_after`, `delete_section`, `set_table`, `build_block`, `refresh_toc` |
| `domain/reporting/brd_assembler.py` | **mới** — `assemble_brd_context()`, `DEFAULT_BRD_SECTIONS`, `SECTION_ALIASES`, `normalize_brd_sections()`, `section_recipes` |
| `tools/schemas/brd.py` | **mới** — các model ở §5.2 |
| `tools/analysis/brd_gates.py` | **mới** — 9 tool |
| `tools/__init__.py` | thêm `BRD_WRITER_TOOLS`; nối 3 tool gate vào `MAIN_TOOLS`, `GATE_TOOL_NAMES`, `GATE_DECISIONS`, `ROLE_GATE_PERMISSIONS`, `_MAIN_TOOL_SELECTOR_ALWAYS_INCLUDE` |
| `agent/subagents/brd_writer.py` | **mới** |
| `agent/subagents/__init__.py` | thêm vào `build_subagent_specs()` |
| `agent/constants.py` | `BRD_CALL_LIMIT = 60`, `BRD_SKILL_PATHS` |
| `agent/middleware/phase_filter.py` | thêm phase `brd`, `_PHASE_TOOLS["brd"]`, span `[[PHASE brd]]` trong prompt |
| `session/gate_decisions.py` | thêm nhánh `_card_for` cho 3 thẻ mới |
| `session/artifacts.py` | thêm khoá state `brd_docx_base64`, `brd_outline`, `brd_validation`, `brd_revision` |
| `session/followups.py` | thêm `_is_brd_followup()` — **đặt TRƯỚC `_is_pdf_followup()`** vì hàm đó đã bắt các từ trần `doc` / `document` |
| `config.yaml` | thêm role `brd_writer` |
| `pyproject.toml` | `python-docx>=1.1` |

### Frontend

| File | Thay đổi |
|---|---|
| `components/BrdOutlineApproval.tsx` | **mới** — cây mục + nhãn xử lý |
| `components/BrdRenderApproval.tsx` | **mới** |
| `components/BrdEditApproval.tsx` | **mới** — diff trước–sau ở mức đoạn |
| `components/chat/MessageList.tsx` | 3 nhánh dispatch theo `pendingInterrupt.data.type` |
| `components/canvas/ArtifactTabs.tsx` | tab **BRD**: xem theo mục + nút tải |
| `hooks/agent-utils.ts` | mở rộng type `AgentState` |
| `lib/downloadBase64.ts` | thêm MIME `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |

---

## 9. Skill `brd-writing`

```
skills/brd-writing/
├── SKILL.md                       # khi nào dùng, thứ tự tool bắt buộc, luật vàng
└── reference/
    ├── template-map.md            # ý nghĩa từng mục của template BRD công ty
    ├── section-recipes.md         # mỗi section_id ↦ nguồn dữ liệu + khuôn nội dung
    └── style-contract.md          # được phép / không được phép đụng gì trong OOXML
```

Khung `SKILL.md`:

```markdown
# Viết BRD từ template công ty

## Thứ tự tool bắt buộc
inspect_brd_template → load_brd_context → draft_brd_outline
  → [GATE B1] → draft_section_content (theo lô ≤ 5 mục)
  → validate_brd → [GATE B2] → out.brd.docx
Chỉnh sửa: read_brd_outline → edit_brd_section → [GATE B3].  KHÔNG BAO GIỜ render lại từ đầu.

## Luật vàng
1. Không bao giờ đoán `section_id` — luôn lấy từ read_brd_outline/inspect_brd_template.
2. Luôn gửi `expect_checksum` vừa đọc. Nếu bị từ chối, đọc lại rồi thử lại — không bỏ qua.
3. Mọi phát biểu định lượng phải trỏ về một thực thể CSM hoặc được ghi rõ là giả định.
4. Không viết mục nào mà template không có; cần mục mới thì dùng operation='insert_after'.
5. Bảng: dòng 0 luôn là header. Ảnh: luôn kèm 1 block caption ngay sau.

## Công thức nội dung theo mục
| section_id | nguồn | khuôn |
|---|---|---|
| purpose | diagram_brief.objective | 1 đoạn dẫn + 4–6 bullet mục tiêu |
| scope | brief + blueprint | 2 khối "Trong phạm vi" / "Ngoài phạm vi" |
| user-needs | CSM stakeholders | bảng No./Name/Type/Description |
| functional-requirements-list | CSM Requirement × Component | bảng ID/NAME/Step/Description |
| FRxx | Requirement + Component + WorkItem | 3 tiểu mục Description/Interface/Data |
| performance | NFR nhóm perf | bảng Functions × Performance requirements |
| analysis-models | danh sách hình đã nhúng | bảng Document/Description/Location |
```

---

## 10. Kế hoạch eval

Theo đúng khuôn `evals/_core.py`: `dataset/*.json` + `judge.py` + `run_eval.py` + `baseline.json`,
hồi quy khi trung bình tụt quá **0.02**. Tất cả **không cần API key** để chạy được trong CI.

| Suite | Lớp | Không cần key | Chỉ số |
|---|---|---|---|
| `evals/brd_structure` | L1 | ✅ | Sau khi vá 1 mục: (a) đúng 1 mục đích đổi checksum, (b) không mục nào mất/thêm, (c) `styles.xml` + `numbering.xml` **giống hệt byte-for-byte**, (d) file mở lại được bằng python-docx |
| `evals/brd_coverage` | L1 | ✅ | Tỉ lệ mục `status=fill` thực sự có nội dung; tỉ lệ Requirement trong CSM xuất hiện ở chương 3 |
| `evals/brd_traceability` | L2 | ✅ | Mỗi FR trỏ đúng về REQ/COMP; phát hiện FR mồ côi và REQ không được phủ |
| `evals/brd_conflict` | L1 | ✅ | Gửi checksum cũ → **phải** bị từ chối; gửi `section_id` không tồn tại → lỗi rõ ràng, không tạo mục mới |
| `evals/brd_quality` (opt-in) | L3 | ❌ cần key | Rubric LLM: đúng ngữ cảnh, đúng văn phong tiếng Việt trang trọng, không bịa số liệu, không lặp |

Bổ sung unit test:

```
tests/test_brd_index.py          # anchor map trên 3 template khác nhau
tests/test_brd_patch.py          # 5 operation × trường hợp biên (mục rỗng, mục cuối, mục có ảnh)
tests/test_brd_style_contract.py # so sánh zip entry styles.xml/numbering.xml trước–sau
tests/test_brd_gate_flow.py      # 3 gate approve/reject, resume đúng
tests/test_brd_followup_order.py # "sửa lại tài liệu" → BRD, không rơi vào _is_pdf_followup
```

---

## 11. Rủi ro và biện pháp

| # | Rủi ro | Mức | Biện pháp |
|---|---|---|---|
| R1 | Template khác nhau giữa các khách hàng làm `section_id` đổi | Cao | `section_id` sinh từ slug tiêu đề + `template_map.json` cache theo hash template; `find()` có fallback so khớp tiêu đề gần đúng |
| R2 | Model bịa `section_id` | Cao | Tool trả danh sách id hợp lệ trong thông báo lỗi; prompt cấm đoán; eval `brd_conflict` chặn hồi quy |
| R3 | Vá song song từ hai phiên làm hỏng file | Trung bình | Khoá lạc quan bằng checksum + snapshot `REV-n.docx` trước mỗi lần ghi |
| R4 | Chi phí token khi soạn 40+ mục | Trung bình | Soạn theo lô ≤ 5 mục/lời gọi; `BRD_CALL_LIMIT=60`; `ClearToolUsesEdit` loại nội dung mục đã ghi khỏi context |
| R5 | Nhận diện ý định "sửa tài liệu" rơi nhầm sang luồng PDF | Trung bình | `_is_brd_followup()` đặt trước `_is_pdf_followup()`; có test thứ tự |
| R6 | TOC lệch khi bàn giao | Thấp | `w:dirty=true` + bước làm mới cache TOC 2 vòng qua bookmark PDF |
| R7 | Ảnh nhúng làm file phình to | Thấp | Giới hạn bề rộng 6.1 inch, nén PNG trước khi nhúng, cảnh báo khi file > 15 MB |

---

## 12. Lộ trình

| Sprint | Hạng mục | Đầu ra nghiệm thu | Effort (man-day) |
|---|---|---|---|
| **S1** | Lớp OOXML: `brd_docx.py` + `template_map.json` + 5 patch op + style contract | `tests/test_brd_index.py`, `test_brd_patch.py`, `test_brd_style_contract.py` xanh | 5 |
| **S1** | Bộ làm mới TOC (2 vòng qua bookmark PDF) | TOC đúng số trang trên tài liệu ≥ 25 trang | 2 |
| **S2** | `brd_assembler.py` + skill `brd-writing` + 6 tool không-gate | Sinh được `brd_outline.json` + `brd_sections/*.json` từ workspace mẫu | 5 |
| **S2** | Subagent `brd_writer` + phase `brd` + đăng ký tool | Main agent uỷ nhiệm được, `usage.json` tách chi phí | 3 |
| **S3** | 3 gate + thẻ giao diện + tab BRD + tải file | Chạy trọn luồng B1→B2→B3 trên UI | 6 |
| **S3** | `_is_brd_followup` + resume + khôi phục phiên | `test_brd_gate_flow.py`, `test_brd_followup_order.py` xanh | 2 |
| **S4** | 4 suite eval không cần key + baseline + nối vào CI | `uv run python -m evals.run_all --gate` xanh | 4 |
| **S4** | Eval L3 opt-in, tài liệu hướng dẫn, dọn nợ ISS-05 | README cập nhật, demo nội bộ | 3 |
| | **Tổng** | | **30 man-day (dev)** |

Theo tỉ lệ định mức đang dùng trong `wbs_effort.py` (BA/QC/PM suy ra từ dev), tổng quy đổi
xấp xỉ **44–48 man-day** cho toàn bộ vai trò.

---

## 13. Bước tiếp theo đề xuất

1. Chốt template BRD chuẩn duy nhất, đưa vào `backend/templates/brd_template.docx`.
2. Bê nguyên `docx_edit.py` (prototype đã chạy) thành `domain/reporting/brd_docx.py`, viết test trước.
3. Song song: viết `section-recipes.md` — đây là thứ quyết định chất lượng nội dung, không phải code.
4. Chỉ sau khi S1 + S2 xanh mới đụng tới frontend.

---

### Phụ lục — tệp prototype kèm theo

| Tệp | Nội dung |
|---|---|
| `docx_edit.py` | Thư viện index + 5 patch op + style borrowing (~430 LOC, chạy được) |
| `brd_content.py` | Toàn bộ nội dung BRD dạng block — mô phỏng đầu ra của `draft_section_content` |
| `build_brd.py` | Điền template → `out/BRD_Diagram_Code_Agent_v1.0.docx` |
| `toc_rebuild.py` | Làm mới cache TOC 2 vòng qua bookmark PDF |
| `demo_edit.py` | Bằng chứng sửa 1 mục + khoá lạc quan |
| `make_figs.py` | Sinh 8 hình bằng `diagrams` + Graphviz |
