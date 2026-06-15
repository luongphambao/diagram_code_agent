# Bổ sung phần "Update PDF report" vào plan federated-greeting-mccarthy.md

## Context

User so sánh 2 PDF sinh ra từ hệ thống:
- `architecture_report (2).pdf` — **13 trang đầy đủ**: cover, executive summary, requirements analysis, traceability, solution, tech stack, blueprint, WAF review, step results, risks, diagram, appendix.
- `architecture_report (4).pdf` — **chỉ 3 trang**: blueprint (với dòng "No key decisions were recorded in the blueprint."), diagram, appendix. Mất cover/title, mất toàn bộ phần phân tích.

### Root cause đã xác minh trong code

1. **LLM truyền `include_sections` rút gọn thay vì `{}`.** Template ([reporting.py:562-825](backend/src/diagram_mcp/reporting.py#L562-L825)) chỉ render section có trong `report.sections` — section vắng mặt = **không có trang nào**, không phải trang trống. PDF (4) đúng 3 trang vật lý ⇒ lần đó tool được gọi với `include_sections ≈ ["blueprint", "diagram"]`. Prompt dặn gọi `generate_pdf_report({})` ([prompts.py:279](backend/src/diagram_mcp/prompts.py#L279)) nhưng schema `PdfReportConfig` ([tools.py:1726-1733](backend/src/diagram_mcp/tools.py#L1726-L1733)) phơi field `include_sections` với description mơ hồ ("Ordered list of sections to include" — không liệt kê tên hợp lệ) → model thỉnh thoảng tự điền subset.
2. **`normalize_sections` drop âm thầm tên sai** ([reporting.py:56-63](backend/src/diagram_mcp/reporting.py#L56-L63)): tên không khớp `DEFAULT_REPORT_SECTIONS`/aliases bị lọc bỏ không cảnh báo (vd `"tech_stack"` ≠ `"techstack"` → mất trang Technology Stack). Luồng HITL approve chạy lại đúng args gốc ([server.py:534-543](backend/src/diagram_mcp/server.py#L534-L543)) — user không có cách sửa.
3. **`blueprint.key_decisions` rỗng** — field optional `default_factory=list` ([tools.py:1291-1295](backend/src/diagram_mcp/tools.py#L1291-L1295)), `propose_blueprint` không warn khi thiếu (khác với các density-mismatch warning vừa thêm) → "No key decisions", executive summary/traceability/risks nghèo nàn theo.

## Thay đổi: thêm section mới vào `federated-greeting-mccarthy.md`

Chèn section **"## Update PDF report (PDF (4) tụt chất lượng so với (2))"** vào sau phần `### P3` và trước `## Files sửa`, đồng thời bổ sung các file/mục verification tương ứng vào 2 phần đó. Nội dung section (tóm tắt root cause ở trên + các fix theo ưu tiên):

### PDF-1. Khóa mặc định full section — `tools.py` + `prompts.py`
- `PdfReportConfig.include_sections`: description liệt kê đúng 11 tên hợp lệ + "Leave EMPTY to include ALL sections (recommended). Only pass a subset when the USER explicitly asked to omit sections."
- `prompts.py` (block tool + stage 9): "ALWAYS call `generate_pdf_report({})`. KHÔNG tự ý truyền `include_sections`/`title` trừ khi user yêu cầu."

### PDF-2. Không drop section âm thầm — `reporting.py` + `tools.py`
- `normalize_sections` trả thêm danh sách tên không nhận diện được; nếu list LLM truyền có >50% tên không hợp lệ → fallback `DEFAULT_REPORT_SECTIONS` (coi như hallucination).
- `generate_pdf_report` return message nêu rõ section bị bỏ/không nhận diện để agent tự sửa.

### PDF-3. Warn khi blueprint thiếu dữ liệu report — `tools.py` `propose_blueprint`
Cùng pattern với density-mismatch warnings hiện có: warn khi `key_decisions` < 3 hoặc `pillar_coverage` rỗng → agent bổ sung TRƯỚC khi user approve blueprint (dữ liệu này nuôi executive summary, traceability, WAF review, risks).

### PDF-4. Gate card cảnh báo thiếu section — `server.py` + `PdfReportApproval.tsx`
- `_card_for` ([server.py:517-530](backend/src/diagram_mcp/server.py#L517-L530)): thêm `missing_sections` (= DEFAULT − requested) vào card.
- `PdfReportApproval.tsx`: hiển thị cảnh báo vàng các section bị thiếu để user reject kèm feedback. (Optional P2: cho tick chọn section ngay trong UI và gửi kèm payload approve.)

### Verification cho phần PDF
- Unit test `normalize_sections`: tên sai → không drop âm thầm; >50% sai → full default.
- Chạy lại `generate_report` trên workspace có đủ artifacts mẫu → `out.pdf` đủ 12 trang (11 section + appendix); gọi với `include_sections=["blueprint","diagram"]` → message cảnh báo các section bị bỏ.
- Run end-to-end 1 scenario có yêu cầu PDF → so trang/nội dung với `architecture_report (2).pdf`.

## File thực thi của plan này
Chỉ sửa 1 file: [federated-greeting-mccarthy.md](federated-greeting-mccarthy.md) — thêm section trên + bổ sung `## Files sửa` (thêm `reporting.py`, `server.py`, `frontend/src/components/PdfReportApproval.tsx`) và `## Verification` (thêm mục PDF). KHÔNG sửa code trong bước này — code sẽ sửa khi thực thi plan đó.
