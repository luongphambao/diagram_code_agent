# 0003 — Engine draw.io tất định làm đường mặc định; `DiagramSpec` thay vì nới `Blueprint`

**Ngày ghi lại:** 2026-07-26 (quyết định có từ trước, ADR hồi tố)
**Trạng thái:** accepted

## Bối cảnh

Sơ đồ kiến trúc là sản phẩm khách nhìn thấy — chất lượng trình bày là yêu cầu, không phải điểm cộng. Ba đường đã thử:

1. Để LLM viết thẳng XML draw.io.
2. Sinh code Python `diagrams` → Graphviz → chuyển sang draw.io (`gv_to_drawio.py`).
3. Builder tất định trong Python từ một spec có cấu trúc.

Đồng thời, mỗi kiểu sơ đồ mới (BPMN, sequence, ERD, state machine) lại đẻ thêm field optional trên `Blueprint` — `Blueprint.process` là ví dụ đã tồn tại của đúng cái anti-pattern đó.

## Quyết định

**Đường mặc định cho architecture là native engine tất định** (`prettygraph/native/`): spec → .drawio, **0 token LLM**. Preset mặc định là `refined`. Đường Graphviz/codegen giữ lại cho C4 và poster.

Chất lượng do một **tầng 0-token** đảm bảo, không do thêm vòng vision:
- `layout_plan.py` + `repair.py` dựng ≤6 phương án layout, luôn giữ một baseline "unplanned" làm sàn — nên nó **không bao giờ** cho ra kết quả tệ hơn bản dựng thẳng.
- `production_scorecard` (`validate_drawio.py`) chấm 8 chiều; PASS đòi total ≥85 **và** node_recall=1 **và** edge_recall=1 **và** 0 lỗi XML **và** 0 va chạm card **và** `arrow_clarity_score` ≥75.
- Vòng critic/vision còn lại, nhưng bị chặn cứng (`CRITIC_REVISION_HARD_CAP = 2` + `DrawerReviseGateMiddleware`).

**Kiểu sơ đồ mới đi vào union `DiagramSpec`** (`tools/schemas/diagram_spec.py`), phân biệt theo `kind`, không thêm field vào `Blueprint`. `propose_blueprint(blueprint: Blueprint)` giữ nguyên chữ ký.

## Phương án đã loại

- **LLM viết XML draw.io** — loại: tốn token khủng khiếp, hình học không tin cậy, không cách nào kiểm tra bảo toàn số lượng node/edge.
- **Graphviz làm đường chính** — loại: không kiểm soát được z-order, padding, kích thước card và bundling ở mức cần cho bản giao khách. Giữ cho codegen.
- **Nhiều vòng critic/vision hơn để đạt chất lượng** — loại: chậm, đắt, không lặp lại được. Kiểm tra tất định bắt được đúng loại lỗi mà vision-self-check hay bỏ sót (đếm sai, va chạm, cạnh mất).
- **Thêm field optional vào `Blueprint`** — loại: đó là con đường tới god object; `Blueprint.process` là bằng chứng.

## Hệ quả

- **Dễ hơn:** render lặp lại được và gần như miễn phí; chất lượng đo được bằng số; thêm kiểu sơ đồ mới không đụng schema của kiểu cũ.
- **Khó hơn:** mọi cải thiện thẩm mỹ đều là code Python trong `prettygraph/native/`, không phải chỉnh prompt. Layout mới phải viết tree builder + đăng ký `RendererEntry`, và nếu tiêu chí chấm khác thì phải thêm profile scorecard (BPMN là ví dụ — nó phải bỏ qua các thanh icon/zone/ratio, nếu không mọi sơ đồ BPMN đều trượt gate).
- **Đã biết còn thiếu:** topology `hub_spoke`/`hierarchy`/`mesh` **luôn** rơi về preset `icon` vì chưa có layout refined cho chúng. `layout_intent="grid"` còn thử nghiệm.
- Z-order và bảo toàn số lượng node/edge là bất biến — có test canh; đừng "tối ưu" chúng đi.
