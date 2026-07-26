# Plan: Nâng cấp Proposal Deck lên "VIP Pro"

## Context

Người dùng muốn deck proposal (.pptx) chuyên nghiệp & đa dạng hơn — hiện "toàn chữ". Các yêu
cầu cụ thể (đã chốt qua hỏi-đáp):
1. Bổ sung **cụm slide Use Cases** (dự án tương tự đã làm).
2. Thêm **cả 4 loại diagram** vào deck (process-flow, sequence, ERD, module/component) — mỗi
   loại 1 slide riêng.
3. Phần **WBS trong deck = chụp ảnh chính file `wbs_filled.xlsx` hệ thống sinh ra** (giữ look
   Excel đẹp), KHÔNG render lại bằng bảng python-pptx (xấu). Engine render: **LibreOffice
   headless** (trung thực nhất).
4. Slide cần **nhiều ảnh + thiết kế đẹp, có NHIỀU PHONG CÁCH (style preset) cho user chọn**.
5. **Tận dụng luồng icon** (`resolve_tech_stack_icons`) làm lại slide tech-stack cho đẹp.
6. Bổ sung **slide giải thích Architecture** (annotate/diễn giải diagram kiến trúc).
7. Ưu tiên: đủ nội dung trước, nhưng visual/đa-style là co-priority (user nhấn mạnh).

Khảo sát code (3 Explore agents) — điểm mấu chốt: **hạ tầng phần lớn đã có nhưng đang "ngủ"**:
- **Pipeline sống**: `plan_deck`→`deck.build_deck_plan` (chuỗi ~20 slide viết tay, chỉ 8 block
  gốc)→`deck_plan.json`→`generate_ppt_proposal_file` render python-pptx trên
  `backend/templates/bnk_proposal_template.pptx`. Toàn bảng/bullet native, chưa có chart.
- **Registry đã xây, CHƯA nối**: `deck_sections.py::SECTION_CONTENT_CONTRACTS` (~30 contract:
  success_story, case_study, methodology, post_launch, feature_list, risk_table, opex, kpis…) +
  `deck_resolver.py` (`csm_to_slide_params`, `pick_case_study` **đã nâng cấp semantic RAG**).
  Grep xác nhận **không có caller runtime** — "spec — not yet applied". Renderer `new_block`
  **chưa tồn tại**.
- **Diagram**: engine render 5 loại (architecture, bpmn/process, sequence, erd, state_machine)
  nhưng deck **chỉ nhúng 1** `out.png`; typed diagram GHI ĐÈ cùng `out.png` → chưa có đa-diagram.
- **WBS→deck**: Effort/Gantt/CAPEX data-bound; **Team & Payment Milestones HARDCODE**.
- **Icon**: `resolve_tech_stack_icons`→`tech_icons.json`, `_tech_stack_icon_slide` (logo grid)
  đã có nhưng chỉ là fallback, chưa chạy mặc định trong pipeline deck.
- **Container**: chỉ có **Chromium headless (Playwright)** để rasterize; KHÔNG có LibreOffice/
  aspose/poppler.

## Nguyên tắc: KÍCH HOẠT lớp đang ngủ, không rebuild
Design-doc của user (`files/01`) đề xuất rebuild edit-based (normalizer/induct/catalog/…) —
chưa tồn tại. Plan tái dùng pipeline native + registry đã xây (~80% sẵn, rủi ro thấp).

---

## Workstreams

### WS1 — Nối registry/resolver vào `build_deck_plan` (xương sống)
Đổi `build_deck_plan` lái theo `SECTION_CONTENT_CONTRACTS` + `csm_to_slide_params` +
`plannable_contracts`/`resolve_missing` (skip-and-warn khi thiếu input) thay chuỗi viết tay.
Giữ `SlideSpec`/`DeckPlan` + `generate_ppt_proposal_file` để không phá QA. Fallback chuỗi cũ
nếu registry lỗi.
- Files: `deck.py`, `deck_sections.py`, `deck_resolver.py`.

### WS2 — Cụm Use Cases / dự án tương tự (auto top-k + HITL)
- `_b_success_story` (top-1) → **top-k 2-3** qua `pick_case_study`/`find_similar_solutions` trên
  `solution_memory.json`; mỗi dự án 1 slide (bài toán/giải pháp/kết quả/tech/effort thật + **ảnh
  `image_ref`** đã có trong solution_memory).
- Renderer `_case_study_slide` mới trong `ppt_reporting.py`.
- **HITL**: hiện danh sách dự án chọn trong gate `propose_deck_plan` để duyệt/sửa.
- Files: `deck_resolver.py`, `ppt_reporting.py`, `deck.py`, `reporting_gates.py`.

### WS3 — WBS trong deck = ẢNH từ `wbs_filled.xlsx` (LibreOffice)
- **Hạ tầng**: thêm `libreoffice`/`soffice` + `poppler-utils` (pdftoppm) vào `backend/Dockerfile`.
- Module mới `wbs_excel_render.py`: `wbs_filled.xlsx` → (soffice --headless --convert-to pdf) →
  (pdftoppm → png) → crop theo từng sheet. Set **print_area/fit-to-page per sheet** (openpyxl)
  trước khi convert để mỗi sheet ra 1 trang gọn.
- Chỉ render 3 sheet có giá trị: **`1. Effort`, `2. WBS`, `3. Delivery Plan`** (bỏ How-to-use /
  Master Data). Ghi `wbs_sheet_images.json` (manifest kind→png).
- Deck: thay các slide WBS native (delivery_effort/gantt table) bằng slide **nhúng ảnh** các
  sheet này (dùng `_image_fit` sẵn có). Giữ renderer native làm **fallback** khi LibreOffice
  không sẵn (không bao giờ chặn).
- Sửa hardcode còn lại: `_team_slide`→`wbs.team_composition`; `_payment_milestones_slide`→
  `wbs.milestones` (giữ 30/30/30/10 fallback) — cho slide text đi kèm ảnh.
- Files: `wbs_excel_render.py` (mới), `wbs_tools.py` (gọi render sau `export_wbs_excel`),
  `ppt_reporting.py`, `deck_resolver.py`, `backend/Dockerfile`.

### WS4 — Đa diagram + slide giải thích Architecture
- **Hạ tầng đa-diagram**: "diagram manifest" cho phép 1 dự án render nhiều diagram ra file riêng
  (`out.<kind>.png`) + mỗi cái 1 slide. Sửa `_render_drawio_png` callers để không ghi đè `out.png`.
- Nối 5 loại: architecture (có), **process/bpmn** (Methodology+SLA), **sequence** (1 luồng chính),
  **erd** (data model), **module/component** (architecture nhóm-cluster). Agent chọn loại phù hợp
  qua `diagram_brief`, có cap số lượng.
- **Slide "Architecture | Explanation"** mới: diễn giải component/data-flow/key decisions từ
  `blueprint.json.key_decisions` + CSM components (bullet/callout cạnh ảnh diagram).
- Files: `rendering_tools.py`, `deck_resolver.py` (`_b_architecture`→`_b_diagrams` list +
  `_b_architecture_explain`), `ppt_reporting.py` (`_diagram_slide` lặp manifest + explain slide),
  `deck.py`.

### WS5 — Hệ visual: đa style preset + icon tech-stack + nhiều ảnh + charts
- **Style presets chọn được**: thêm `deck_style` (vd `corporate` / `modern` / `minimal`) — mỗi
  preset là bộ màu/layout/spacing/imagery. Mirror pattern `style_preset="refined"` đã có ở
  diagram engine. Param trên `plan_deck`/`generate_ppt_proposal`, hiện ở gate cho user chọn.
- **Tech-stack qua icon flow**: chạy `resolve_tech_stack_icons` trong pipeline deck →
  `_tech_stack_icon_slide` (logo-per-tech theo layer) thành **mặc định** thay bảng chữ.
- **Nhiều ảnh + bớt chữ**: dùng imagery của diagram (WS4), icon (tech), ảnh WBS (WS3), ảnh
  use-case `image_ref` (WS2); thêm numbered cards / colored callouts / icon bullet cho slide
  nội dung (Exec Summary, Solution, Methodology) thay bullet-wall.
- **Charts native** python-pptx: donut effort theo role, bar cost theo module (từ `effort_totals`).
- Files: `ppt_reporting.py` (preset system + renderer), `deck.py`, `icon_tools.py` (tái dùng).

### WS6 — QA mở rộng
`deck_visual_qa.py` + `deck.score_deck_structure` nhận diện block/ảnh mới (đừng cảnh báo nhầm
slide ảnh là "empty_body"); eval `backend/evals/deck/judge.py` so điểm Design/Coherence trước-sau.

---

## Critical files
- `backend/src/domain/deck/deck.py` — `build_deck_plan`, `score_deck_structure`
- `backend/src/domain/deck/deck_sections.py` — `SECTION_CONTENT_CONTRACTS`
- `backend/src/domain/deck/deck_resolver.py` — builders, `pick_case_study`, `csm_to_slide_params`
- `backend/src/domain/reporting/ppt_reporting.py` — renderer + `VALID_BLOCKS` + preset system
- `backend/src/domain/wbs/wbs_excel_render.py` (mới) + `wbs_tools.py` — WBS→ảnh
- `backend/src/tools/rendering_tools.py` — đa-diagram render + manifest
- `backend/src/tools/analysis/reporting_gates.py` — HITL gate (use-case + style)
- `backend/Dockerfile` — thêm libreoffice + poppler-utils
- `backend/src/tools/icon_tools.py` — tái dùng icon flow
- `backend/src/domain/deck/deck_visual_qa.py`, `backend/evals/deck/judge.py` — QA

## Tái dùng (đừng viết lại)
- `pick_case_study` + `rag/solution_memory.py` + `find_similar_solutions` + `image_ref` (WS2)
- `render_typed_diagram` + `prettygraph/native/{sequence,erd,state_machine,bpmn}.py` + registry (WS4)
- `_render_drawio_png_playwright` (Chromium) — rasterize diagram (WS4)
- `resolve_tech_stack_icons` + `_tech_stack_icon_slide` + `tech_icons.json` (WS5)
- `wbs_excel._module_schedule` + `wbs_effort.delivery_grid`; template `wbs_template.xlsx` (WS3)
- `_add_table/_style_cell/_image_fit`, `bnk_proposal_template.pptx` (mọi WS)
- Gate pattern `propose_* → interrupt → resume` (WS2 HITL)

## Verification
- **WS1**: `plan_deck` trên workspace thật → `deck_plan.json` từ registry, số slide tăng, không
  slide rỗng; `validate_deck` + `score_deck_structure` PASS.
- **WS2**: CSM có domain → 2-3 slide use-case đúng dự án tương tự (đối chiếu
  `find_similar_solutions`); gate hiện danh sách duyệt.
- **WS3**: sau `export_wbs_excel` → `wbs_sheet_images.json` có 3 ảnh; deck nhúng ảnh sheet Excel
  đúng look (mở `out.pptx` kiểm mắt); tắt LibreOffice → fallback bảng native, không crash.
- **WS4**: 1 dự án sinh ≥2 diagram (architecture + sequence/erd) thành slide riêng, ảnh khác
  nhau; có slide Architecture Explanation.
- **WS5**: đổi `deck_style` ra look khác nhau rõ rệt; tech-stack là logo grid; có chart đúng số
  WBS.
- **WS6**: `deck_visual_qa` không cảnh báo nhầm slide ảnh; eval VLM so điểm trước-sau.
- Suốt các WS: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q` xanh (trừ 3 test
  `modal.Image` hỏng sẵn). WS3 cần rebuild container (Dockerfile đổi).

## Ghi chú thứ tự
WS1 nền tảng. WS2 (use-case) ưu tiên 1 sau WS1. WS3/WS4/WS5 song song được (WS3 cần rebuild
Docker). WS6 cuối. Mỗi WS ship độc lập, registry chạy song song + fallback chuỗi cũ nếu lỗi;
WBS-ảnh fallback bảng native nếu LibreOffice thiếu → không bao giờ chặn pipeline.
