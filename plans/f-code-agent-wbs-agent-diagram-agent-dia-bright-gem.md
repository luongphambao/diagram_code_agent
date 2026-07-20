# Nâng chất lượng diagram: fix render sparse + nâng giới hạn độ phức tạp

## Context

User thấy diagram sinh ra (vd. `diagram (12).png` — IoT poster, 7 section) nhìn "sơ sài": body nhỏ lọt thỏm giữa panel trắng, node bé, kiến trúc thật phải chi tiết hơn. Phân tích luồng agent (main → drawer → critic) tìm ra 2 nhóm nguyên nhân:

1. **Bug render (nguyên nhân chính):** `_compose_slide_png` ([prettygraph.py:993](backend/src/diagram_mcp/prettygraph.py#L993)) dùng `body.thumbnail(...)` — PIL thumbnail **chỉ downscale, không bao giờ upscale**. Body nhỏ hơn vùng panel (~1920×1130px, aspect ≈1.70) thì bị paste nguyên size và căn giữa → diagram nhỏ giữa khoảng trắng lớn. Body rộng (poster aspect 2.0–2.5, audit hiện chấp nhận tới 2.3) bị co theo chiều ngang → chỉ lấp ~55–70% chiều cao. Không có metric nào đo body-to-panel fill: `audit_layout` chỉ check aspect + edge stranding, critic nhìn JPEG 800px, eval `judge.py` không đo density.
2. **Giới hạn độ phức tạp:** `Blueprint.density` chỉ có 2 mức `standard` (12-18 node, ≤5 cột) / `poster` (25-40 node, grid 2 hàng cứng — `declare_poster_grid` validate row1 3-6, row2 2-5 section). Không có mức trung gian 18-26 node; LLM tự chọn density chỉ qua prose; `plan_style_sizes` warn >18 node đẩy agent xoá bớt nội dung; blueprint có field `tech`/`protocol` nhưng prompt không bắt buộc surface thành sublabel/edge label → card chỉ có title, nhìn "sketch".

Mục tiêu: diagram lấp đầy panel, hỗ trợ kiến trúc lớn chi tiết hơn, nội dung "engineered" (tech sizing, protocol), và đo lường được qua eval.

## Files chính

- `backend/src/diagram_mcp/prettygraph.py` — `_compose_slide_png` (954-1022), `render_slide` (1145-1186), `Pretty.render` (~398: đã có `self.dpi`, mặc định 192/168), `audit_layout` (~566)
- `backend/src/diagram_mcp/tools.py` — `plan_style_sizes` (752-841), `Blueprint.density` (1232), `propose_blueprint` (1508-1569), `declare_poster_grid` (1716-1770), `_layout_audit` (154-164)
- `backend/src/diagram_mcp/prompts.py` — density prose (441-456, 501, 623-626), `_PRETTY_DIAGRAM_DETAIL` hard rules (553-576), `_CRITIC_BODY` (733-838), `_STAGED_FLOW` step 6
- `backend/evals/diagram/judge.py` — metric mới
- `agent.py` — KHÔNG cần sửa (max_tokens 16000 chỉ là nhánh Anthropic fallback; render caps không phải bottleneck)

## P0 — Fix render sparse (impact cao nhất)

1. **Scale-to-fit hai chiều trong `_compose_slide_png`** (prettygraph.py:990-997): thay `body.thumbnail(...)` bằng
   ```python
   scale = min(max_w / body.width, max_h / body.height)
   if abs(scale - 1.0) > 0.01:
       body = body.resize((round(body.width*scale), round(body.height*scale)), Image.LANCZOS)
   ```
   Thêm `fill_w`, `fill_h`, `panel_fill_pct` vào dict `layout` trả về.
2. **Upscale sắc nét bằng DPI re-render trong `render_slide`** (prettygraph.py:1145-1186): pixel upscale >~1.3× sẽ mờ. Sau `g.render(...)`, tính scale cần thiết so với vùng panel; nếu >1.15 thì re-render qua `dot -Tpng out.dot -Gdpi=<dpi*scale>` (thêm tham số `dpi_override` vào `Pretty.render`, layout Graphviz không đổi nên lossless).
3. **Surface PANEL FILL vào layout audit:**
   - `render_slide`: ghi dict `layout` (panel box, body box, fill pct) vào `out.slide.json`.
   - `_layout_audit` (tools.py:154-164): đọc `out.slide.json`, append dòng `PANEL FILL: NN% — body leaves large white margins...` khi area fill < ~65%.
   - Siết aspect verdict slide-mode trong `audit_layout` (prettygraph.py ~627-630): ideal body aspect ~1.5–1.8 (panel 1.70); flag >2.1 là "TOO WIDE for the slide panel" thay vì 2.3.
4. **Critic enforcement** (`_CRITIC_BODY` prompts.py): thêm bullet — file finding `panel_underfill` mức `medium` khi audit báo PANEL FILL thấp hoặc body nhỏ giữa panel trắng (generalize bullet poster ở dòng 772 cho mọi slide output).

## P1 — Nâng giới hạn độ phức tạp, density theo blueprint

5. **Thêm tier `detailed`** (tools.py):
   - `Blueprint.density` → `Literal["standard","detailed","poster"]`: standard 12–18 node/≤5 cột; **detailed 18–26 node/≤6 cột, sublabel bắt buộc** (single-grid slide engineering-grade); poster 25–45 node.
   - `plan_style_sizes`: retier ≤8 sparse / ≤14 medium / ≤22 dense / ≤28 detailed (node_h 50, title 13) / poster. Thay warning >18 node (dòng 811) bằng: chỉ warn khi vượt cap của density đã khai báo, và gợi ý lên tier kế tiếp thay vì xoá node.
6. **Blueprint size tự quyết density** (`propose_blueprint` tools.py:1508-1569): sau validation, tính `n = len(blueprint.nodes)` và warn deterministic khi mismatch: `n ≥ 22 & density != poster` → dùng poster; `17 ≤ n ≤ 21 & density == standard` → dùng detailed; `n < 13 & density == poster` → poster sẽ trống, dùng standard. Echo density + node count vào chuỗi APPROVED; thêm 1 dòng vào `_STAGED_FLOW` step 6: task description cho drawer PHẢI ghi rõ density + node count.
7. **Poster 3 hàng / nhiều section hơn** (`declare_poster_grid` tools.py:1716-1770): thêm optional `row3`; relax row1 3–7, row2 2–6, row3 0–5; emit `g.poster_grid(...)` 2 hoặc 3 hàng (`Pretty.poster_grid` đã nhận `*rows`, không cần sửa renderer). Update prose poster trong prompts.py (444-456, 626) + note trong `plan_style_sizes` (tools.py:815-822): "25–45 nodes, 6–12 numbered sections, 2–3 rows".

## P2 — Nội dung "engineered" (chỉ sửa prompt)

8. **Bắt buộc sublabel + protocol edge label** (prompts.py):
   - Mục Blueprint quality (608-645 pretty, 387-417 plain): mọi node compute/data/network phải điền `tech` (service + sizing, vd. "Fargate 0.5 vCPU ×2–6", "PostgreSQL 15 Multi-AZ"); mọi edge primary-flow có `protocol` hoặc nhãn operation ngắn.
   - `_PRETTY_DIAGRAM_DETAIL` Hard rules: mọi card hiển thị PHẢI có sublabel (từ blueprint `tech` + tech-stack `capacity_sizing`); card chỉ-title là defect. Nhãn protocol ≤3 từ trên primary flow; side-channel được phép không nhãn.
   - `_CRITIC_BODY`: file finding `medium` khi đa số card chỉ-title hoặc primary flow không nhãn trong diagram detailed/poster.
   - `fit_labels`/`plan_style_sizes` đã tính sublabel width — không cần sửa tool.

## P3 — Eval đo lường được

9. **Metric density/fill trong `judge.py`:**
   - Structural: đọc `out.slide.json` layout → `panel_fill_pct`, body aspect, `sublabel_coverage` (tỉ lệ node có `tech` không rỗng), tỉ lệ node produced/expected.
   - Vision rubric: thêm dimension `visual_density` ("diagram lấp panel với node đúng cỡ hay trôi nhỏ giữa whitespace? node có tech detail?").
   - Thêm 1–2 case dataset với `min_nodes: 22+` để exercise đường detailed/poster.

## Verification

1. Re-render script IoT poster đang fail (workspace `diagram.py`) sau P0 — body phải chạm mép panel; `out.slide.json` báo `panel_fill_pct ≥ 0.8`. Test parametric: render diagram 5 node và poster 2.5:1 — cả hai lấp ≥80% một chiều panel, không mờ (đường DPI kích hoạt cho diagram nhỏ).
2. Confirm output tool `render_diagram` có dòng `PANEL FILL` và layout cố tình quá rộng sẽ trigger nó.
3. End-to-end: chạy `backend/evals/diagram/run_eval.py` trước/sau; so sánh `micro_f1`, `panel_fill_pct`, `visual_density`, vision `readability`/`overall`.
