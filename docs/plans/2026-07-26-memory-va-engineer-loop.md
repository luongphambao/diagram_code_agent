# Kế hoạch — Cải thiện Memory & Engineer Loop của luồng vẽ diagram

**Ngày:** 2026-07-26
**Trạng thái:** approved, chưa triển khai

## Context

Luồng vẽ diagram có bốn tầng chất lượng lồng nhau: **tầng 0** tất định (`layout_plan.py` → `repair.py` → `production_scorecard`), **tầng 1** vision (`inspect_render_quality`), **tầng 2** sửa XML (`read_drawio` → `edit_drawio`), **tầng 3** vòng người (`critic` → `finalize_diagram` → `DrawerReviseGateMiddleware`). ADR `0003` chọn tầng 0 làm đường chính — đúng, và tầng đó được viết tốt. Vấn đề nằm ở chỗ **ba tầng còn lại không đóng vòng**, và **cơ chế memory thì có sẵn một learning loop hoàn chỉnh nhưng chưa từng chạy một lần nào**.

Sau khi rà code, năm vấn đề gốc:

### 1. Trần budget được tính theo "mỗi lần export", còn vòng revise thì theo "mỗi lần dispatch"
`_reset_drawio_edit_rounds()` (`tools/rendering_tools.py:1249-1256`) xoá **cả hai** counter `.drawio_edit_rounds` và `.engineer_rounds`, và được gọi ở cuối **mọi** `_render_native_from_spec` (`:836`, `:883`, `:1030`) — tức mọi `export_drawio_native` / `upgrade_drawio`. Nhưng **không có counter nào trên chính `export_drawio_native`**.

Hệ quả kép:
- Một drawer đang bị `EDIT BUDGET EXHAUSTED` chỉ cần gọi `export_drawio_native()` là có lại 2 inspection + 2 edit batch. Thứ duy nhất chặn việc đó là một câu **văn xuôi**: "never re-export hoping for a different geometry" (`prompts/drawer_agent.py:170-171`). So sánh: đường Graphviz có `RENDER_HARD_CAP` **cưỡng chế bằng code** (`:108`).
- Ngược lại, một drawer **tuân thủ** prompt (không re-export) khi vào vòng revise sau khi user reject thì **không được cấp lại budget**: `DrawerReviseGateMiddleware._decide` chỉ gọi `reset_render_count()` (`agent/middleware/drawer_gate.py:109`), không reset hai counter kia. Nó gặp `EDIT BUDGET EXHAUSTED` ngay ở `edit_drawio` đầu tiên.

Tức là: **cách duy nhất để vòng revise hoạt động là model phá luật prompt.** Cùng loại lỗ: `_reset_revision_count()` ở `blueprint_tools.py:732` làm một lần re-propose blueprint reset luôn `CRITIC_REVISION_HARD_CAP`.

### 2. Tầng sửa không có phanh, không có mốc, và không có ký ức
- `edit_drawio` ghi đè `out.drawio` ở `:1760` **không snapshot**. Guard semantic-loss ở `:1763-1782` phát hiện sau khi đã ghi, và lời khuyên duy nhất là "undo or re-export" — không có gì để undo.
- Điểm sau khi sửa được tính lại (`:1804-1808`) nhưng **không so với điểm trước**. Một batch làm **giảm** điểm được nhận âm thầm. Tầng 0 thì có bảo đảm rõ ràng "không bao giờ tệ hơn baseline" (`repair.py:6-8`); hai tầng LLM không có gì tương đương.
- `KeepLatestImagesEdit` (`agent/middleware/context_edits.py:22-54`) xoá mọi ảnh trừ ảnh mới nhất → drawer **về mặt cấu trúc không thể** so sánh ảnh trước/sau. Kết hợp với việc không có delta số, hồi quy thị giác là không thể phát hiện.
- Drawer là một `create_deep_agent` **mới toanh mỗi lần `task()`** (`_blocks.py:401-402`: "use a fresh task each time"), và `DrawerContextInjectMiddleware._FILES` (`drawer_context_inject.py:17`) chỉ inject `render_spec.json, icon_plan.json, style_plan.json, label_fits.json` — **không có** `critique.json`, `engineer_report.json`, hay bất kỳ log op đã thử. Round 2 không biết round 1 đã làm gì, ngoài những gì main agent chép tay vào prose.
- `critique.json` (`blueprint_tools.py:809`) **không được code nào đọc lại**. Finding của critic tới được drawer hay không phụ thuộc hoàn toàn vào việc main model có chép đúng vào `description` hay không.
- `read_drawio` cắt ở **250 cell** (`:1522`). Một trang refined dày (~48 card × các sub-cell `__sh/__ac/__ic/__pill` + zone + edge) vượt ngưỡng đó thường xuyên → "one batched fix" được lập kế hoạch từ một inventory **thiếu**.

### 3. Scorecard có thể PASS khi phép đo bị hỏng, và `iconography` gần như không thể trượt
- `production_scorecard` (`validate_drawio.py:1668-1821`) theo convention "absent metrics score neutral … never a false fail" (`:1675-1676`): `composition` trả `10.0` khi `ratio is None` (`:1719-1720`), `arrow_score` mặc định `100.0` (`:1708`), `iconography` mặc định full khi thiếu metric. Nhưng `audit_layout_metrics` được gọi trong một `try/except Exception: pass` trần (`validate_xml:1555-1567`) → **một exception trong code đo làm cả gate xanh**.
- `_bake_icon_plan` bước 4 (`rendering_tools.py:795-797`) gán `_category_glyph` cho **mọi** node còn lại, nên `icon_coverage` ≈ 1.0 kể cả khi toàn bộ icon là glyph xám generic. Số miss thật nằm ở `stats["fallback_icons"]` — mà `production_scorecard` **không hề đọc**. Một diagram 30 glyph xám vẫn đạt full điểm iconography.
- 45/100 điểm là **miễn phí** cho mọi native render: `semantic_completeness` (25) + `relationship_correctness` (15) + `editability` (5) — recall = 1.0 do cách builder dựng. Thêm `layer_clarity` 10 + `iconography` 10 là 65 điểm trước khi đo bất cứ thứ gì về *bố cục*. Chỉ 35 điểm (`connector_readability` 15, `spacing_alignment` 10, `composition` 10) thật sự đo cái người ta nhìn.
- Ngưỡng kích hoạt tầng 1 là `< 85` — **đúng bằng** ngưỡng PASS (`drawer_agent.py:173`). Một diagram đúng 85 điểm với 3 crossing, ratio 1.9, 40% icon placeholder **không được thanh tra lần nào**.

### 4. Vòng lặp kết thúc bằng cách gọi thất bại là thành công
- `submit_critique` **đổi REVISE thành PASS** khi hết trần revision (`blueprint_tools.py:822-828`).
- `finalize_diagram` (`rendering_tools.py:2328-2361`) chỉ kiểm `out.png` tồn tại. Nó **không tính scorecard, không đọc `critique.json`, và không thể fail**. Một diagram 40/100 finalize giống hệt một diagram 95/100.
- `_diagram_gate_note()` (`tools/analysis/gates.py:132-207`) — thứ biến lint finding thành `SolutionFinding` bền trong `findings_log.json` và in scorecard tại gate — được gọi từ **đúng một chỗ**: `rendering_tools.py:473-475`, tức `export_drawio`, tức **đường Graphviz đã deprecated**. Đường native (mặc định) không bao giờ persist finding, không bao giờ waivable, không bao giờ vào `quality_summary`.
- Tương tự `_archive_session()` (`stage_markers.py:217-264`) cũng chỉ được gọi từ `rendering_tools.py:464` (`export_drawio`) → **`agent_space/outputs/` rỗng** trên máy này, và tool `list_saved_diagrams` (đã có trong `MAIN_TOOLS`, đã bật ở phase `draw`) không có gì để trả về.

### 5. Memory: learning loop đã được viết sẵn, chưa từng chạy, và có bug làm mất dữ liệu
- `backend/agent_space/memories/AGENTS.md` (32 dòng, sửa lần cuối **2026-06-20**) được nạp vào system prompt của **mọi** agent, **mỗi lượt** (`agent/builder.py:138,163`). Toàn bộ `## Do Not Do` + `## Style Preferences` là kiến thức thời mingrammer/Graphviz: "read and edit existing `diagram.py`, then re-render", `taillabel`, `ltail`/`lhead`. Đó **chính xác** là những gì `drawer_agent.py:61` cấm cho đường native. Memory đang nói ngược lại engine.
- **`backend/scripts/refine_memory.py` tồn tại và đúng là cái learning loop cần có**: `_fetch_outcomes()` (97-143) đọc `conversations.outcomes_json`, giữ **chỉ** các `decision == "reject"` có note (`:126`), lọc theo watermark `<!-- last_analyzed: … -->`, `_route()` (201-215) phân loại theo gate + keyword, `_synthesize()` (176-194) gọi LLM một lần mỗi section (≤15 bullet, format nghiêm), rồi ghi lại section trong AGENTS.md. Dữ liệu vào nó đã được ghi **bằng code**, không phụ thuộc model: `record_gate_outcome()` (`conversations.py:251-291`) được gọi từ `routers/chat.py:305-311` cho **mọi** gate.
- Nhưng: file AGENTS.md **không có watermark** ⇒ script chưa từng chạy. Nó cũng **không chạy được trong container**: `.dockerignore:75` loại `scripts/` khỏi image, và `scripts/` không nằm trên import path của app. Không cron, không hook, không CI job, không route nào tham chiếu nó.
- Và nó có **bug làm mất dữ liệu**: `_SECTIONS` (`:35`) khai **3** section, còn file thật có **4** (`## Learned WBS Norms` được thêm tay). `_replace_section` (`:62-77`) tìm "section kế tiếp" chỉ trong `_SECTIONS`, nên khi synthesize vào `## Learned Icon & Tech Notes` (section cuối trong danh sách) nó sẽ **xoá sạch mọi thứ phía sau**, bao gồm `## Learned WBS Norms`.
- Không có **memory nào hình dạng diagram**: corpus 116 solution + Qdrant `bnk_solutions` chỉ nối vào `MAIN_TOOLS` cho phase `intake/blueprint/wbs` (`phase_filter.py:78-124`) — **bị lọc ra ở phase `draw`**. Diagram chỉ có **3** template JSON tĩnh chấm bằng keyword (`domain/diagram/template_library.py`, `resources/diagram_templates/`). Một diagram đã PASS scorecard và được người thật duyệt bị **bỏ đi hoàn toàn**.
- Không có test nào chạm memory (67 file test).

**Mục tiêu:** vòng revise hoạt động mà không cần phá luật; mọi lần sửa có phanh + mốc so sánh + ký ức; scorecard không PASS khi phép đo hỏng; và memory tự tích luỹ được từ chính cái người duyệt/từ chối.

> **Ghi chú phạm vi:** phần "scorecard nói thật" (GĐ2) rộng hơn câu hỏi ban đầu về memory/loop. Nó nằm trong kế hoạch vì nó là **tiền đề**: mọi cải thiện loop đều được điều khiển bởi `production_scorecard`, nên nếu scorecard PASS được khi phép đo hỏng thì cải thiện loop chỉ làm nó tự tin hơn về một con số không đáng tin. GĐ2 land riêng được nếu cần tách.

---

## Giai đoạn 1 — Vòng lặp hoạt động mà không cần phá luật

### 1.1 Đưa các counter về `stage_markers.py` và cấp lại budget đúng chỗ
`_reset_drawio_edit_rounds` / `_bump_drawio_edit_rounds` / `_drawio_edit_rounds` / `_bump_engineer_rounds` hiện nằm ở `tools/rendering_tools.py:1249-1290`. Chuyển sang `tools/stage_markers.py` — đúng nơi mọi counter file-based khác đã sống (`AGENTS.md`: "Bộ đếm nằm ở file JSON trong workspace … qua `tools/stage_markers.py`"). Giữ **nguyên tên file counter** (`.drawio_edit_rounds`, `.engineer_rounds`) để resume cũ không vỡ; `rendering_tools.py` import lại từ đó. Đây là di chuyển thuần, tránh vòng import khi `drawer_gate.py` cần gọi.

Rồi trong `agent/middleware/drawer_gate.py::_decide`, ngay cạnh `reset_render_count()` ở `:109`, reset cả hai counter đó. Đây là điểm duy nhất trong hệ thống biết chắc "đây là một vòng revise thật sau khi người dùng reject".

### 1.2 Cưỡng chế luật "không re-export" bằng code
Thêm `_NATIVE_EXPORT_CAP` (2, env-overridable) + counter `.native_export_rounds` trong `stage_markers.py`. `export_drawio_native` và `upgrade_drawio` kiểm counter trước khi chạy; vượt trần → trả `status="error"` giải thích rõ: dùng `read_drawio` + `edit_drawio` để sửa, không re-export. Counter này **chỉ** được reset ở cùng chỗ 1.1 (vào vòng revise) và ở `clear_stage_markers` (run mới) — **không** reset bởi chính export.

Quan trọng: pre-render tất định trong `propose_blueprint` (`blueprint_tools.py:647-649`) gọi `_render_native_from_spec` **trực tiếp**, không qua tool, nên nó không tiêu trần — giữ nguyên như vậy.

Cùng lúc, bỏ `_reset_revision_count()` khỏi `blueprint_tools.py:732`: re-propose blueprint không được xoá trần `CRITIC_REVISION_HARD_CAP`. Nếu có test canh hành vi này thì đọc trước (`tests/test_drawer_revise_gate.py`).

### 1.3 `edit_drawio` có phanh: snapshot + revert khi tệ hơn
Trong `tools/rendering_tools.py::edit_drawio`:
1. Đầu hàm: `before_xml = out.read_text()`, và tính `before_score` (`validate_file` + `production_scorecard`).
2. Áp op, ghi, validate, tính `after_score` (khối `:1784-1808` đã có).
3. Nếu `after.total < before.total` **hoặc** guard semantic-loss (`:1774-1782`) bắt được mất node/edge: ghi lại `before_xml`, re-render PNG, **không** `_bump_drawio_edit_rounds()`, trả `status="error"` kèm điểm hai bên + đúng op nào đã áp. Model còn nguyên lượt edit để thử cách khác.
4. Ngược lại: giữ, bump round.

Chú ý thứ tự hiện tại: `_bump_drawio_edit_rounds()` ở `:1761` nằm **trước** khối validate — phải chuyển xuống sau bước quyết định.

### 1.4 Điểm dạng delta, bù cho việc không so được ảnh
Thêm `quality_history.json` (qua `stage_markers.py`, cùng kiểu `render_count.json` để sống sót resume): append `{step_no, step, total, pass, breakdown}` mỗi lần export / edit / inspect. Không dùng `datetime.now()` argless — theo convention của `memory/stores/decisions.py`, số thứ tự bước là đủ.
- `edit_drawio`: in `Production scorecard: <before> → <after> (Δ<±n>)`.
- `inspect_render_quality`: in một dòng lịch sử ngắn (`export 78 → edit1 81`), và nếu lần edit trước bị revert thì nói thẳng.

Đây là thứ **duy nhất** bù được cho `KeepLatestImagesEdit`: model không so được ảnh, nên phải cho nó so bằng số.

### 1.5 Inject phản hồi vòng trước vào drawer
`agent/middleware/drawer_context_inject.py:17` — thêm `critique.json`, `engineer_report.json`, `quality_history.json` vào `_FILES`. `_MAX_EMBED_CHARS = 20_000` đã có sẵn làm van an toàn, và `_read_workspace_file` bỏ qua file thiếu, nên đây là thay đổi 1 dòng + kiểm kích thước.

Đây là fix rẻ nhất trong cả kế hoạch cho vấn đề lớn nhất: nó biến "critic finding tới drawer qua việc main model chép tay" thành "tới bằng code", và cho drawer round 2 biết round 1 đã thử gì.

Sửa `_blocks.py` (khối hướng dẫn dispatch drawer, `:396-402`) để không còn yêu cầu main chép finding vào prose — chỉ cần trỏ tới `critique.json` đã được inject.

### 1.6 `read_drawio` không lập kế hoạch từ inventory thiếu
Trần 250 cell ở `:1522`: thay vì cắt cụt im lặng, (a) bỏ các cell decorative (`__sh/__ac/__ic/__pill`) khỏi output — chúng không phải mục tiêu edit hợp lệ, và đó chính là thứ làm trang refined vượt trần; (b) nếu vẫn vượt, nói rõ đã cắt bao nhiêu và theo tiêu chí gì, để model biết inventory là một phần.

---

## Giai đoạn 2 — Scorecard nói thật

Toàn bộ ở `backend/src/domain/validation/validate_drawio.py` + `tools/rendering_tools.py`. Đổi điểm → **bắt buộc** `uv run python -m evals.run_all --gate`; điểm sẽ **giảm** ở một số diagram (đó là mục đích), nên chốt bằng `--update-baseline` trong cùng change và ghi lý do vào PR body.

### 2.1 Phân biệt "đo được và tốt" với "không đo được"
`validate_xml:1555-1567` bọc `audit_layout_metrics` trong `except Exception: pass`. Thay bằng: bắt exception nhưng **ghi cờ** `layout_metrics = {"error": str(exc)[:200]}`. Trong `production_scorecard`, khi thấy cờ đó: giữ nguyên cách tính điểm neutral (không làm điểm tụt vô cớ) nhưng đặt `sc["metrics_ok"] = False` và **loại PASS** — thêm `metrics_ok` vào điều kiện PASS ở `:1803-1810`. Một phép đo hỏng không được biến thành một gate xanh.

### 2.2 `iconography` phản ánh icon thật, không phải glyph placeholder
`_bake_icon_plan` đã đếm và đặt `stats["fallback_icons"]` (`rendering_tools.py:831`, `:878`). Cho `production_scorecard` đọc nó: trong nhánh refined (`:1739-1748`) và nhánh icon, tính `real_coverage = (leaves - fallback_icons) / leaves` và dùng nó cho phần `cov_pts` thay vì `icon_coverage` thuần. Giữ `icon_coverage` trong output để không mất tín hiệu cũ.

### 2.3 Tách ngưỡng kích hoạt tầng 1 khỏi ngưỡng PASS
`prompts/drawer_agent.py:173` nói "ONLY if the reported Production scorecard is below 85" — đúng bằng PASS. Đổi thành: thanh tra khi `< 90` **hoặc** khi bất kỳ dimension bố cục nào (`connector_readability`, `spacing_alignment`, `composition`) dưới 70% trọng số của nó. Con số này chỉ nằm trong prompt, nhưng nên **in ra từ tool** (`export_drawio_native` in một dòng "inspection recommended: yes/no + lý do") để model không phải tự suy luận — cùng kỹ thuật mà `edit_drawio`/`read_drawio` đã dùng.

### 2.4 `finalize_diagram` biết diagram nó đang finalize tệ đến đâu
`rendering_tools.py:2328` — trước `_snapshot_diagram`, tính scorecard và đọc `critique.json`. **Không block** (nó là HITL gate, người duyệt là người quyết — và block sẽ đổi hợp đồng gate), nhưng: đưa `{scorecard_total, pass, breakdown, residual_findings}` vào `record_report_step` data và vào chuỗi trả về, để card gate ở frontend hiển thị được. Người duyệt hiện đang approve mà không thấy điểm.

### 2.5 Đường native persist finding như đường deprecated
`_diagram_gate_note(block=False)` hiện chỉ được gọi từ `export_drawio` (`:473-475`). Gọi thêm từ `export_drawio_native` và `upgrade_drawio` (cùng vị trí: sau khi có stats, trước khi trả về). Đây là thứ làm lint finding của đường mặc định trở thành `SolutionFinding` bền, waivable qua `waive_finding`, và hiện lên `quality_summary` — cùng máy móc mà `findings_from_validation` (`:1856`) và cả eval suite `evals/diagram_quality/` đang test trên một code path production không còn dùng.

---

## Giai đoạn 3 — `auto_repair` thành loop thật (vẫn 0 token)

`prettygraph/native/repair.py` + `layout_plan.py`. Cũng cần eval gate (đổi hình học output).

### 3.1 Nhiều vòng, sinh biến thể từ winner hiện tại
`auto_repair` (`:174-230`) hiện sinh biến thể **chỉ từ symptom của baseline** rồi chọn max — một bước leo đồi, không phải loop. Bọc phần sinh-và-chấm trong `for round in range(_MAX_ROUNDS)` (`_MAX_ROUNDS = 2`), mỗi vòng gọi `_variants_for(best_plan, spec, best_metrics)`. Dừng khi PASS, hoặc không sinh được plan mới, hoặc chạm `_MAX_CANDIDATES`.

Giữ hai bất biến: `planned` + `unplanned` luôn là candidate (sàn không bao giờ tệ hơn hôm nay — `repair.py:6-8`), và `_rank_key` (`:161-171`) nguyên trạng. Dedup candidate bằng `json.dumps(plan, sort_keys=True)`.

Nâng `_MAX_CANDIDATES` 6 → 10: mỗi candidate là một `build_drawio_from_spec` + scorecard **thuần XML, không render PNG** (`:53-61`), nên chi phí là CPU chứ không phải token. Đo thời gian thật trên spec lớn nhất trong fixture trước khi chốt; nếu một build > ~150ms thì để 8.

### 3.2 Đưa `band_order` vào không gian biến thể
`band_order` là yếu tố sinh crossing lớn nhất nhưng `_variants_for` không hề thay đổi nó. `order_bands` (`layout_plan.py:100-127`) đã có hàm chi phí `_order_cost` (`:89`) — cho nó trả thêm phương án nhì: `order_bands_ranked(...) -> list[list[str]]`, giữ `order_bands` như wrapper để không vỡ call site. Trong `_variants_for`, khi symptom là crossing/arrow, thêm candidate `band-order-2`.

Chỉ áp cho preset **không**-refined ở bước đầu (nhánh refined `return` sớm ở `:137`); refined dùng zone rows chứ không dùng band order theo cách đó. Đọc `tests/test_refined_builder.py` trước khi mở rộng.

### 3.3 Tổ hợp knob thay vì một cặp hardcode
Hiện chỉ có đúng một tổ hợp viết tay (`aggressive-bundles-zpr4`, `:113-116`). Thay bằng tích Descartes hẹp (tối đa 2 knob cùng lúc) trên các knob mà symptom chỉ định, rồi cắt theo `_MAX_CANDIDATES`. Vẫn symptom-gated — spec khoẻ vẫn chỉ tốn 1 build như hôm nay (`:209` giữ nguyên: baseline PASS → thoát ngay).

### 3.4 Ghi nhớ knob nào thắng, chỉ để xếp thứ tự
`agent_space/memories/layout_wins.json` (cross-thread): key = chữ ký rẻ của spec (`style_preset`, bucket số node, số band, bucket số edge, có sidebar hay không), value = `{candidate_label: {wins, avg_score}}`. `auto_repair` dùng nó **chỉ để sắp thứ tự** candidate (thử knob từng thắng trước) → tiết kiệm build khi chạm `_MAX_CANDIDATES`. Không bao giờ ghi đè `_rank_key`, và `planned`/`unplanned` vẫn luôn được chấm → **không thể** làm output tệ hơn. Ghi sau khi chọn xong.

---

## Giai đoạn 4 — Memory tự tích luỹ

### 4.1 Viết lại global memory cho engine hiện tại
Thay nội dung `backend/agent_space/memories/AGENTS.md`: bỏ mọi dòng thuộc đường mingrammer (`diagram.py`, `taillabel`, `ltail`/`lhead`, "re-render"), viết lại `## Do Not Do` / `## Style Preferences` bằng từ vựng native (zone, band, card, `read_drawio`→`edit_drawio` một batch, bundling thay vì pin tay từng edge). Giữ `## Learned WBS Norms` (vẫn đúng). Thêm watermark `<!-- last_analyzed: … -->` để 4.2 có mốc bắt đầu.

Thêm `backend/tests/test_memory_hygiene.py`: assert (a) không chứa token của đường deprecated, (b) tồn tại đúng 4 section header mà `_blocks.py:282-289` và `refine_memory._SECTIONS` dùng làm anchor, (c) kích thước dưới ngưỡng (~6KB — file này vào prompt mỗi lượt), (d) mỗi section không quá N bullet. Đây là thứ duy nhất chặn được memory drift.

### 4.2 Làm `refine_memory` chạy được — và sửa bug mất dữ liệu của nó
Dữ liệu vào đã đúng và đã được ghi bằng code (`record_gate_outcome` ← `routers/chat.py:305-311`, mọi gate, không phụ thuộc model). Chỉ thiếu người tiêu thụ. **Không viết lại từ đầu** — `refine_memory.py` đã có đúng hình dạng cần (lọc reject-có-note, watermark, route theo gate, LLM synthesize, cap 15 bullet).

Cần làm:
1. **Sửa bug mất section**: `_SECTIONS` (`:35`) thêm `## Learned WBS Norms`; và sửa `_replace_section` (`:62-77`) để biên "section kế tiếp" quét **mọi** header `^## ` thật có trong file, không chỉ các header trong `_SECTIONS`. Test hồi quy: file 4 section → synthesize vào section thứ 3 → section thứ 4 còn nguyên.
2. **Chuyển vào import path của app**: `scripts/` bị `.dockerignore:75` loại khỏi image nên script hiện **không thể chạy trong container**. Chuyển sang `backend/src/memory/refine.py` với CLI `python -m memory.refine [--dry-run]`, và dùng `config.make_llm` thay cho raw `openai` SDK (giữ nguyên logic prompt/temperature). Để lại `scripts/refine_memory.py` như một stub gọi module mới, hoặc xoá — kiểm `grep` trước.
3. **Cách gọi**: thêm một dòng vào `docs/runbook.md` (chạy tay sau mỗi đợt dự án) **và** `--dry-run` để xem diff trước khi ghi. **Không** tự động hoá bằng cron trong change này: nó gọi LLM và ghi vào một file vào prompt mọi lượt — nên bước đầu để người xem diff, giống mọi thứ khác trong sản phẩm này đều qua một gate.

### 4.3 Harvest diagram đã duyệt — dùng lại `agent_space/outputs/` đã có
Cơ chế archive đã tồn tại và đang **chết vì không được gọi**: `_archive_session()` (`stage_markers.py:217-264`) copy `_SESSION_ARTIFACTS` (`tools/constants.py:41`) + `meta.json` sang `agent_space/outputs/<ts>_<title>/`, và `list_saved_diagrams()` (`rendering_tools.py:1846-1881`) đã nằm trong `MAIN_TOOLS` + đã bật ở phase `draw`. Nhưng nó chỉ được gọi từ `export_drawio` (`:464`) — đường deprecated → dir rỗng.

Làm ba việc:
1. Gọi `_archive_session()` từ `finalize_diagram` (sau `_snapshot_diagram`) — tức **chỉ archive cái người thật đã duyệt**, chứ không phải mọi lần export. `finalize_diagram` là gate và deepagents interrupt **trước** khi tool chạy, nên code trong nó chạy sau approve. Đúng điểm cần.
2. Mở rộng `_SESSION_ARTIFACTS` + `meta.json`: thêm `render_spec.json`, `layout_plan.json`, `engineer_report.json`, và `{scorecard_total, pass, breakdown, provider, style_preset, node_count, band_count}` vào `meta.json`. `list_saved_diagrams` trả thêm scorecard + chữ ký spec → tool đó lần đầu có nội dung dùng được thay vì chỉ danh sách path.
3. **Template học được (strip chặt, tự động)**: khi finalize và scorecard PASS, ghi thêm `template.json` vào cùng dir archive — bản **đã làm sạch** của `render_spec.json`: giữ cấu trúc (clusters/nodes/edges/provider/style_preset/plan thắng cuộc + `node.type`), **thay mọi label tự do** bằng nhãn generic suy từ `node.type`, xoá `slide_title`/`diagram_title`/tên khách. Nếu một label không map được sang `type` chắc chắn → **không harvest diagram đó** (mặc định là bỏ, không đoán). Kèm `{"scorecard": total, "source": "learned"}`.
   `domain/diagram/template_library.py::_load_all()` (`:66`) đọc **hai** nguồn: `resources/diagram_templates/` (3 file repo, như hiện tại) + `agent_space/outputs/*/template.json`. `_score_entry` (`:40`) giữ nguyên; thêm tie-break ưu tiên scorecard cao hơn. Cap số template learned (50, LRU theo scorecard) để `_load_all` (`@lru_cache(1)`) không phình.
   `find_diagram_template` (`blueprint_tools.py:236-255`) không cần đổi — nó tự có thêm corpus.

Lý do strip chặt: template được dùng cho **khách khác**; rò tên khách là sự cố dữ liệu, không phải lỗi thẩm mỹ. Đánh đổi đã chấp nhận: template mất một phần ngữ nghĩa nhãn, nhưng giữ được cấu trúc — mà cấu trúc mới là thứ `find_template` cần.

### 4.4 Dọn dẹp nhỏ đi kèm
- Xoá 17 dir thread test còn sót trong `agent_space/workspaces/` (`thread-drawer-gate-test_*`, `evil`, `abc-123`, `verify-thread-2`).
- `similar_solutions.json` (`rag_tools.py:97`) là sidecar chỉ-ghi, không ai đọc: **giữ** (rẻ, hữu ích khi debug) nhưng thêm một câu comment nói rõ nó là debug artifact, để lần audit sau không phải điều tra lại.

---

## File then chốt

`backend/src/tools/stage_markers.py` (nhận các counter + `quality_history.json` + `_archive_session` mở rộng) · `backend/src/tools/rendering_tools.py` (`edit_drawio`, `read_drawio`, `inspect_render_quality`, `export_drawio_native`, `upgrade_drawio`, `finalize_diagram`) · `backend/src/agent/middleware/drawer_gate.py` · `backend/src/agent/middleware/drawer_context_inject.py` · `backend/src/domain/validation/validate_drawio.py` (`validate_xml`, `production_scorecard`) · `backend/src/prettygraph/native/repair.py` · `backend/src/prettygraph/native/layout_plan.py` · `backend/src/domain/diagram/template_library.py` · `backend/src/memory/refine.py` (mới, từ `backend/scripts/refine_memory.py`) · `backend/src/prompts/drawer_agent.py` + `_blocks.py` · `backend/agent_space/memories/AGENTS.md` · `AGENTS.md`

Test: `test_memory_hygiene.py` (mới), `test_memory_refine.py` (mới), `test_drawer_revise_gate.py`, `test_drawio_edit.py`, `test_diagram_quality.py`, `test_layout_plan.py`, `test_native_engine.py`, `test_refined_builder.py`

## Verification

Sau mỗi giai đoạn:
```bash
cd backend && uv run ruff format --check . && uv run ruff check . && uv run pytest tests/ -q --cov=src --cov-fail-under=60
```

Kiểm chứng riêng:
- **1.1/1.2** — `pytest tests/test_drawer_revise_gate.py -q`: sau khi gate cho phép revise, cả 3 counter (`.drawio_edit_rounds`, `.engineer_rounds`, `.native_export_rounds`) = 0. Thêm case: gọi `export_drawio_native` lần thứ 3 trong cùng round → `status="error"`.
- **1.3** — `tests/test_drawio_edit.py`: một batch op cố ý làm tệ (ví dụ `move` một card chồng lên card khác → collisions > 0) phải trả `status="error"`, `out.drawio` **byte-identical** với bản trước, `.drawio_edit_rounds` **không** tăng.
- **1.4** — dòng `Δ` xuất hiện trong output `edit_drawio`; `quality_history.json` có ≥2 entry sau 1 export + 1 edit.
- **1.5** — unit test trên `_build_context_block()`: workspace có `critique.json` → block chứa nội dung file đó.
- **2.1** — monkeypatch `audit_layout_metrics` raise → `production_scorecard(...)["pass"] is False` dù `total` vẫn ≥85. Đây là test quan trọng nhất của GĐ2.
- **2.2** — spec mà mọi node rơi về `_category_glyph` → điểm `iconography` giảm rõ so với spec có icon thật.
- **2.4/2.5** — sau `finalize_diagram`, `report_evidence.json` có `scorecard_total`; sau `export_drawio_native`, `findings_log.json` có finding từ lint.
- **3.x** — `pytest tests/test_layout_plan.py tests/test_native_engine.py tests/test_refined_builder.py tests/test_diagram_quality.py -q`. Thêm assert: với một spec crossing-heavy đã biết, `engineer_report["final_score"]` **≥** giá trị hiện tại (chụp trước khi sửa) và `len(iterations) > 1`. Đo thời gian `auto_repair` trên spec lớn nhất — không quá gấp đôi hôm nay.
- **4.1** — `pytest tests/test_memory_hygiene.py -q`; thêm `taillabel` vào file memory → test đỏ.
- **4.2** — `test_memory_refine.py`: file 4 section, synthesize section thứ 3 → section thứ 4 còn nguyên (hồi quy cho bug `_SECTIONS`). Rồi `python -m memory.refine --dry-run` trong container in ra diff.
- **4.3** — chạy luồng thật tới `finalize_diagram` approve → `agent_space/outputs/<ts>_*/` có `template.json` + `meta.json` có scorecard; `find_diagram_template(<query gần spec vừa duyệt>)` trả về template đó; `grep -ri "<tên khách>" backend/agent_space/outputs/*/template.json` → **rỗng**.

Đụng prompt hoặc điểm (GĐ2, 2.3, 1.5, 3.x):
```bash
cd backend && uv run python -m evals.run_all --gate
```
Điểm sẽ giảm ở một số diagram do 2.1/2.2 — đó là chủ đích, nên `--update-baseline` và commit `baseline.json` **trong cùng change** (`AGENTS.md:31`), ghi lý do vào PR body.

End-to-end (sau GĐ1 và sau GĐ4):
```bash
docker compose up --build     # FE :5173, BE :8001
```
Luồng thật: upload tài liệu → blueprint gate approve → diagram render → **reject ở `finalize_diagram` kèm một góp ý cụ thể** ("gộp 3 mũi tên monitoring lại") → xác nhận vòng drawer thứ hai **sửa được thật** (`edit_drawio` chạy, có Δ, không cần re-export) → approve → kiểm `agent_space/outputs/` có archive + `template.json`, và `python -m memory.refine --dry-run` thấy góp ý reject đó trong diff đề xuất.

> **Bắt buộc rebuild container**, không chỉ restart — thay đổi nằm trong image backend.

## Thứ tự & phụ thuộc

```
GĐ1  1.1 → 1.2 (cùng đụng stage_markers) → 1.3 → 1.4          1-1.5 ngày
     1.5, 1.6 độc lập, làm song song
GĐ2  2.1 → 2.2 (cùng đụng production_scorecard)               1 ngày
     2.3 phụ thuộc 2.1/2.2 (ngưỡng mới cần điểm mới)
     2.4, 2.5 độc lập
GĐ3  3.1 → 3.2/3.3 (cùng đụng _variants_for) → 3.4            1-1.5 ngày
GĐ4  4.1 → 4.2 (4.2 cần watermark từ 4.1)                     1-1.5 ngày
     4.3 độc lập; 4.4 lúc nào cũng được
```
GĐ1 nên land trước và đứng một mình được. GĐ2 land riêng vì nó đổi baseline eval. GĐ3 và GĐ4 độc lập với nhau; chỗ chồng lấn duy nhất là `agent_space/memories/` giữa 3.4 và 4.1 (khác file, không xung đột).

Tổng: ~5-6 ngày, 4 PR độc lập revert được (GĐ1, GĐ2, GĐ3, GĐ4).

Khi GĐ4 land, viết thêm ADR `docs/decisions/0010-memory-duoc-ghi-bang-code.md` — nó **bổ sung** ADR `0001` (memory vẫn là file, Qdrant vẫn chỉ là tool) và ghi lại quyết định mới: *cách ghi* chuyển từ "model tự `edit_file`" sang "consolidator tất định đọc `outcomes_json`".

## Không làm (và lý do)

- **Không nới `CRITIC_REVISION_HARD_CAP`, `_DRAWIO_EDIT_CAP`, `_ENGINEER_INSPECT_CAP`.** Vấn đề không phải trần thấp mà là trần bị reset sai chỗ (1.1/1.2) và một lượt bị đốt vào edit làm tệ đi (1.3). Nới trần trước khi sửa hai cái đó chỉ mua thêm token.
- **Không để `finalize_diagram` block theo scorecard.** Nó là HITL gate — người duyệt là người quyết. 2.4 chỉ làm điểm **hiện ra** cho người duyệt thấy.
- **Không đưa memory vào Qdrant, không kích hoạt LangGraph store.** ADR `0001` tách đôi có lý: memory bền phải diff/audit được. LangGraph `AsyncPostgresStore` hiện hoàn toàn dormant (0 read, 0 write, không `index=`) — **để nguyên**; nó không phải nợ kỹ thuật mà là một hằng số của deepagents. Kế hoạch này giữ memory ở hình dạng "một file .md", chỉ đổi *cách ghi*.
- **Không tự động hoá `memory.refine` bằng cron** ở change này — nó gọi LLM và ghi vào file vào prompt mọi lượt. `--dry-run` + chạy tay trước; cron là quyết định riêng.
- **Không thêm vòng vision.** ADR `0003` đã loại. Mọi thứ ở GĐ3 là 0-token; GĐ1 làm 2 lượt vision hiện có *hiệu quả hơn* chứ không thêm lượt.
- **Không ghi template learned vào `resources/`.** Đó là nội dung repo; dữ liệu runtime đi vào `agent_space/` (đã gitignore).
- **Không đụng z-order và bảo toàn số node/edge** trong `native/builder.py` — bất biến có test canh (`ADR 0003:39`).
- **Không bật lại prompt caching** — phase prompt filter đã làm prompt biến thiên (`agent-design.md:121`); vấn đề riêng.
- **Không hợp nhất 4 drawio emitter**, không migrate `native/registry.py` sang single-route — `ADR 0003:19` và docstring registry ghi rõ là strangler-fig có chủ ý.

## Đã phát hiện, cố ý để ngoài phạm vi

Ba thứ tìm thấy khi rà nhưng không thuộc luồng diagram/memory — nên là change riêng, ghi lại để không mất:
1. **`backend/data/case_library.json` (79 entry) dormant** — không loader nào đọc; mọi caller `pick_case_study` truyền `library=[]` (`domain/deck/deck.py:440,469`), nên keyword fallback mà `ADR 0001:21` mô tả là **code chết**. Nếu Qdrant và embeddings cùng không có, section Success Story im lặng rỗng.
2. **`clear_stage_markers()` bất đối xứng** (`tools/stage_markers.py:89-136`): xoá `solution_model.json` + `evidence_log.json` nhưng **giữ** `decision_log.json`. Decision log được giữ lại rồi project lên một CSM vừa mint lại `ASM-*`/`RISK-*` từ đầu → `project_into_csm` bỏ link dangling âm thầm (`decisions.py:231-241`), nên accept-risk / confirmed-assumption có thể biến mất qua một lần reset run.
3. **`find_similar_solutions` degrade âm thầm** (`rag_tools.py:49-59`): trả `status:"ERROR"` và run tiếp mà không có grounding nào từ dự án cũ. Không assert, và `health_checks.py` không có probe cho Qdrant / `OPENAI_API_KEY`.
