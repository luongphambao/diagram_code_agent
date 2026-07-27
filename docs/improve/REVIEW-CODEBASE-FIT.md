# Đối chiếu `NANGCAPDIAGRAMAGENT.md` với codebase — đọc trước khi code

`NANGCAPDIAGRAMAGENT.md` (và hai drop-in `text_metrics.py` / `semantic_gates.py`
cạnh nó) là bản phân tích ngoài, viết trước khi đối chiếu với `diagram_code_agent`
thật. Chẩn đoán tổng thể đúng và có giá trị — nhưng có 6 điểm sai/lỗi thời so với
code hiện tại, trong đó **một điểm nếu implement y nguyên sẽ làm hỏng pipeline**
(vòng REVISE vô tận). Tài liệu này là bản vá lỗi trước khi bất kỳ ai copy hai
drop-in đó vào repo.

Việc thi công thật nằm trong plan `plans/replicated-riding-thimble.md` (Sprint
1–2 đã hiệu chỉnh) — file này chỉ ghi lại **tại sao** plan đó khác bản gốc.

---

## Những gì plan gốc nói ĐÚNG (đã xác nhận trong code)

| Khẳng định | Xác nhận |
|---|---|
| Hình học dựng trên hằng số đoán độ rộng ký tự | Đúng, và tệ hơn mô tả: **5 estimator khác nhau** rải rác — `layout_engine.py` (`6.6`/`7.2`/`5.8`), `refined.py` (char-count `32` + `6.6`/`6`/`8`/`6.5`), `builder.py` (`7`/`7.2`/`6.5`), `graph_builder.py` (ratio `0.62`/`0.54`), `drawio_ingest.py` (`_wrap_body(width=32)`) |
| Validator đồng thuận với cùng hằng số sai | Đúng — `validate_drawio.py:1423` `len(e["label"]) * 6.6`; `refined.py:194` tự nhận "mirrors validate_drawio's edge-label estimate" |
| Repo đã có font metrics thật nhưng sai chỗ | Đúng — `slide.py:25-44` dùng `PIL.ImageFont` cho hero-band text; `pillow>=9.0` đã có sẵn trong `pyproject.toml` |
| Validator không có invariant liên kết (degree/orphan) | Đúng — chỉ có ở nhánh BPMN (`validate_drawio.py:987,1041`) |
| Critic bị cấm ép REVISE về ngữ nghĩa | Đúng — `skills/critic/SKILL.md:16-18,92` |
| Hai từ vựng màu edge đánh nhau | Đúng — `_blocks.py:492-493` vs `refined_theme.py:75-82 EDGE_CLASSES` |
| PNG phụ thuộc mạng/Electron | Đúng — `rendering_tools.py:547,634` |
| Note rỗng nghĩa `"Consumers act on these results."` | Đúng, hardcode tại `refined.py:165-169` |

## Sáu điểm đã hiệu chỉnh

1. **🔴 "39% orphan / edge-per-card 0.74" phần lớn do renderer tự tạo, không phải lỗi sinh diagram.** `layout_plan.py:34` `_BUNDLE_EDGE_CAP = 0.4` cố ý ẩn tới 40% edge thành "bundle representative" — đây là feature (canvas dày vẫn đọc được), không phải bug. Đo trên `.drawio` là đo sai artifact: 3 edge trong spec bị bundle-suppress cả 3 sẽ hiện ra như orphan dù spec hoàn toàn đúng. Gate I1/I2 phải chạy ở **tầng spec** (trước bundling), không phải trên `.drawio`.

2. **🔴 `(×N flows)` / `(all layers)` / `governed APIs` / `systems sync` không phải placeholder LLM bịa — code sinh ra chúng có chủ đích** (`layout_plan.py:461-477 _label_for()`, `refined.py:922-924`, `topology.py:896-898`). Regex `_PLACEHOLDER` của Patch 2 gốc sẽ tấn công chính feature bundling của mình. Sửa đúng: representative mang nhãn thật của member + đăng ký vào Interface Register, không cấm chuỗi.

3. **🟠 Patch 1 gốc nhắm sai file đầu tiên.** `refined` là preset mặc định (`rendering_tools.py:897-903`) nhưng dùng `_wrap(text, width=32)` (đếm ký tự, `refined.py:70`) + `_CARD_W=200` cố định, không dùng `len*6.6`. `layout_engine.py` là đường legacy/`icon`. Phải sửa `refined.py` trước.

4. **🟠 Skill trùng (`skills/drawer/*`) đã được fix ở tầng load** — `agent/constants.py:29-32` đã hợp nhất, không code nào còn load hai thư mục con trùng đó. Việc cần làm là xoá file chết, không phải symlink.

5. **🟠 Patch 3 (anchor) mô tả sai cơ chế.** `router.py:916-919` luôn phát `exitX/entryX`; `bake = d.contract == "bake"` chỉ quyết định có emit waypoint hay không, và `refined.py:519` luôn truyền `contract="bake"`. Case "waypoint không anchor" gần như không tự sinh ra từ router hiện tại → hạ xuống mức warn, không phải "lỗ ngầm nghiêm trọng".

6. **🟡 Đường dẫn & số dòng đã lỗi thời** (`refined_theme.py` nằm ở `prettygraph/native/`, validator 1998 dòng không phải 1633) và `refined_theme.as_json()` **đã tồn tại** — Patch 5 phải tái sử dụng, không viết dumper mới.

---

⚠ Nếu bạn định copy `text_metrics.py` hoặc `semantic_gates.py` từ thư mục này vào
`backend/src/`: **đừng copy nguyên văn**. Bản thật đã implement nằm ở
`backend/src/prettygraph/text_metrics.py` (đã hiệu chỉnh font-path cho đúng
`liberation2/` như `slide.py`) và invariant ngữ nghĩa chạy ở tầng spec, bundle-aware
— xem `plans/replicated-riding-thimble.md` phần B2.
