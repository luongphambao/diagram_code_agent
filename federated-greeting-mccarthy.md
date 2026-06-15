# Tối ưu cost full luồng agent (5M → ~1M tokens/diagram)

## Context — phân tích từ trace thực tế (run-019ebc15...json)

Một diagram tốn ~5M cumulative input tokens. Trace cho thấy:
- **Main agent**: 16 model calls = 450K input (400K cached). Baseline context ~15K/call.
- **Drawer**: chết ở **80/80 calls** (kỳ vọng thiết kế chỉ 12-18 calls) — đây là nơi đốt tiền chính.
- User đúng: tool results cứ append vào messages, mỗi model call gửi lại toàn bộ.

### 4 root cause đã xác minh trong code

1. **Ảnh render "tàng hình" với cơ chế clear context.** `ClearToolUsesEdit` đếm token bằng
   `count_tokens_approximately` — tính ảnh **flat 85 tokens** (`langchain_core/messages/utils.py:2228`),
   trong khi ảnh JPEG 800px thực tế tốn **7-27K tokens** qua Responses API. Trigger 30K chỉ đo text
   → ảnh cũ tích lũy gần như không kiểm soát. Đây là nguyên nhân chính drawer phình to.

2. **Vòng lặp churn tự gây**: `keep=6` + `clear_at_least=1M` xóa sạch mọi tool result cũ
   (kể cả SKILL.md 27K chars vừa đọc và code args của render) → agent phải đọc lại → đẩy kết quả
   khác ra → đọc lại tiếp. 80 calls là do churn, không phải do cần.

3. **Blueprint/tech-stack bị serialize 3 lần** vào history main agent: gate args (~9K tokens,
   bị exclude khỏi clearing nên ở lại mãi mãi) + task(drawer) description 12.4K chars +
   task(critic) description.

4. **Fact quan trọng cho an toàn**: `ContextEditingMiddleware` chỉ edit **deepcopy per-request**
   (`context_editing.py:251`), không động vào checkpointed state → mọi edit tùy biến đều an toàn
   với HITL gates và resume.

## Các thay đổi (theo thứ tự ưu tiên)

### P0-1. Usage logging — `agent.py`
`UsageLoggingMiddleware` (wrap_model_call): đọc `usage_metadata` từ AI message, cộng dồn vào
`WORKSPACE/usage.json` theo agent name (main/drawer/critic). `_middleware()` thêm param `agent_name`.
→ Đo được trước/sau từng thay đổi. Risk: không có.

### P0-2. `KeepLatestImagesEdit` — `agent.py` (fix lớn nhất)
Implement `ContextEdit` protocol (giống `ClearToolUsesEdit`), đặt ĐẦU list edits của
`ContextEditingMiddleware` hiện có:
- Strip image blocks khỏi mọi ToolMessage của `render_diagram`/`inspect_diagram` TRỪ ảnh mới nhất,
  thay bằng text `"[older render image cleared — see latest]"`.
- **GIỮ text block (layout audit)** của render cũ → không mất guidance, quality giữ nguyên.
- Không cần trigger — chạy mọi call, deterministic, HITL-safe (per-request copy).
- Cache-friendly: history byte-stable giữa các render.
**Tiết kiệm: 0.5-1.5M trên run bệnh lý; ~100-250K trên run khỏe.** Risk: thấp (drawer chỉ cần ảnh mới nhất).

### P0-3. Sửa clearing churn — `agent.py` `_middleware()`
- `clear_at_least=1_000_000` → `8_000` (clear theo chunk lớn rồi DỪNG, không xóa sạch), `keep=6` → `8`.
- KHÔNG hạ trigger 30K (sau P0-2 counter đã trung thực; trigger thấp hơn = nhiều cache break hơn).
→ Cùng P0-2 + P1-2, biến 80 calls về ~15-18 calls.

### P1-1. File-based handoff — `tools.py` + `prompts.py`
- `propose_blueprint` ghi thêm **`render_spec.json`** (nodes/clusters/edges/density/slide fields +
  map compact `{layer: choice + capacity_sizing}` từ tech_stack.json; bỏ pillar_coverage/nfr_mapping/
  rationales — không cần cho render). Deterministic, không tốn LLM.
- `_STAGED_FLOW` stage 6-7 + `_MAIN_TOOLS_BLOCK` + `build_drawer_prompt` + `_CRITIC_BODY`:
  task description chỉ còn ~500 chars (provider, style notes, critic findings, pointer tới file).
  Drawer step 1 = đọc `render_spec.json`; critic đọc blueprint.json từ disk.
**Tiết kiệm: ~100-250K/diagram** (3K tokens × mỗi call của main sau stage 6 + mỗi call drawer/critic).

### P1-2. Drawer call budget + batching + icon pre-seed — `prompts.py`, `tools.py`
- Thêm budget line vào drawer prompt: "~18 tool calls cho initial render, ~8 cho revision. Batch:
  MỘT search_diagrams_nodes, MỘT resolve_icons, MỘT plan_style_sizes, MỘT fit_labels.
  Nếu result hiện '[cleared]' → artifact đã ở trên disk (diagram.py, icon_plan.json, style_plan.json),
  đọc file 1 lần, KHÔNG re-run tool."
- Pre-seed icons: lúc approve blueprint, chạy `_search_icon_hits` (deterministic) trên node labels
  để tạo sẵn `icon_plan.json`; drawer chỉ resolve các miss.
**Đây là multiplier lớn nhất: mỗi call tránh được = 10-30K input.**

### P2 (sau khi P0/P1 đo OK)
- Bỏ `exclude_tools=GATE_TOOL_NAMES` khỏi ClearToolUsesEdit của main (an toàn per root-cause #4;
  thêm 1 dòng prompt: gate bị reject thì đọc lại artifact JSON). ~70-90K.
- Dedup output `resolve_icons` (bỏ echo input, cap alternatives=2) + `fit_labels` (chỉ trả entries
  fits=false). 1-4K/run.
- `CRITIC_CALL_LIMIT` 20 → 10.

### P3 (cuối, cẩn thận — text mang quality)
- Dedup `_PRETTY_DIAGRAM_DETAIL` (11.1K chars) vs `skills/drawer/pro-style/SKILL.md` (27.3K chars):
  mỗi rule có MỘT chỗ canonical; không xóa rule không tồn tại nơi khác. Trim gate-tool docstrings.
- Hạ call limits: MAIN=60, DRAWER=40 sau khi usage.json xác nhận drawer ≤20 calls.

## Update PDF report (PDF (4) tụt chất lượng so với (2))

### Root cause
1. **LLM truyền `include_sections` rút gọn thay vì `{}`.** Template (`reporting.py:562-825`) chỉ render section có trong `report.sections` — section vắng mặt = không có trang nào, không phải trang trống. PDF (4) đúng 3 trang ⇒ lần đó tool được gọi với `include_sections ≈ ["blueprint", "diagram"]`. Prompt dặn gọi `generate_pdf_report({})` (`prompts.py:279`) nhưng schema `PdfReportConfig` (`tools.py:1726-1733`) phơi field `include_sections` với description mơ hồ → model thỉnh thoảng tự điền subset.
2. **`normalize_sections` drop âm thầm tên sai** (`reporting.py:56-63`): tên không khớp `DEFAULT_REPORT_SECTIONS`/aliases bị lọc bỏ không cảnh báo → mất trang. Luồng HITL approve chạy lại đúng args gốc (`server.py:534-543`) — user không có cách sửa.
3. **`blueprint.key_decisions` rỗng** — field optional `default_factory=list` (`tools.py:1291-1295`), `propose_blueprint` không warn khi thiếu → "No key decisions", executive summary/traceability/risks nghèo nàn.

### PDF-1. Khóa mặc định full section — `tools.py` + `prompts.py`
- `PdfReportConfig.include_sections`: description liệt kê đúng 11 tên hợp lệ + "Leave EMPTY to include ALL sections (recommended). Only pass a subset when the USER explicitly asked to omit sections."
- `prompts.py` (block tool + stage 9): "ALWAYS call `generate_pdf_report({})`. KHÔNG tự ý truyền `include_sections`/`title` trừ khi user yêu cầu."

### PDF-2. Không drop section âm thầm — `reporting.py` + `tools.py`
- `normalize_sections` trả thêm danh sách tên không nhận diện được; nếu list LLM truyền có >50% tên không hợp lệ → fallback `DEFAULT_REPORT_SECTIONS` (coi như hallucination).
- `generate_pdf_report` return message nêu rõ section bị bỏ/không nhận diện để agent tự sửa.

### PDF-3. Warn khi blueprint thiếu dữ liệu report — `tools.py` `propose_blueprint`
Cùng pattern với density-mismatch warnings hiện có: warn khi `key_decisions` < 3 hoặc `pillar_coverage` rỗng → agent bổ sung TRƯỚC khi user approve blueprint (dữ liệu này nuôi executive summary, traceability, WAF review, risks).

### PDF-4. Gate card cảnh báo thiếu section — `server.py` + `PdfReportApproval.tsx`
- `_card_for` (`server.py:517-530`): thêm `missing_sections` (= DEFAULT − requested) vào card.
- `PdfReportApproval.tsx`: hiển thị cảnh báo vàng các section bị thiếu để user reject kèm feedback. (Optional P2: cho tick chọn section ngay trong UI và gửi kèm payload approve.)

## Files sửa
- `backend/src/diagram_mcp/agent.py` — P0-1/2/3, P2, P3-2
- `backend/src/diagram_mcp/prompts.py` — stage 6/7, drawer budget, trims; PDF-1 prompt rules
- `backend/src/diagram_mcp/tools.py` — render_spec.json, icon pre-seed, output dedup; PDF-1 schema, PDF-3 blueprint warn
- `backend/src/diagram_mcp/reporting.py` — PDF-2 normalize_sections fallback + unknown-name reporting
- `backend/src/diagram_mcp/server.py` — PDF-4 missing_sections in gate card
- `frontend/src/components/PdfReportApproval.tsx` — PDF-4 missing-section warning UI
- Tham chiếu protocol: `backend/.venv/.../langchain/agents/middleware/context_editing.py`

## Verification
1. Sau P0-1: chạy 1 scenario chuẩn → ghi baseline usage.json (đối chiếu LangSmith).
2. Sau mỗi phase: chạy lại CÙNG scenario → so sánh usage.json (target: drawer ≤20 calls,
   cache_read/input ≥60%).
3. Unit test: `KeepLatestImagesEdit.apply` (multi-image, content str vs blocks, edge cases);
   render_spec derivation từ fixture blueprint.
4. HITL: approve/reject vẫn pause+resume, approval UI vẫn hiện đủ gate args.
5. Quality (KHÔNG được giảm): 3 scenario (standard/detailed/poster) — critic PASS trong ≤2 revisions,
   diff out.png bằng mắt; mọi check sublabel/density/legend giữ nguyên.
6. Unit test `normalize_sections`: tên sai → không drop âm thầm; >50% sai → full default.
7. Chạy lại `generate_report` trên workspace có đủ artifacts mẫu → `out.pdf` đủ 12 trang (11 section + appendix); gọi với `include_sections=["blueprint","diagram"]` → message cảnh báo các section bị bỏ.
8. Run end-to-end 1 scenario có yêu cầu PDF → so trang/nội dung với `architecture_report (2).pdf`.

## Kết quả kỳ vọng
**5M → ~0.8-1.2M cumulative input tokens/diagram** (P0-2 + P0-3 + P1-2 đóng góp chính),
quality không đổi vì chỉ cắt dữ liệu thừa/lặp trong context, không cắt quality checks.
