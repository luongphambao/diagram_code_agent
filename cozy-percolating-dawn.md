# Kế hoạch: Kết hợp diagram-as-code + next-ai-draw-io để tạo diagram chuẩn production

## Bối cảnh

Repo hiện có **hai engine vẽ diagram** bổ sung cho nhau, không phải thay thế:

- **`backend/` — diagram-as-code (bộ não).** Kiến trúc Deep Agents (LangGraph):
  phân tích yêu cầu → tech stack → blueprint → **drawer** subagent → **critic** subagent →
  finalize, tất cả qua luồng HITL (human-in-the-loop). Pipeline phân giải icon thực sự
  (`resolve_icons`/`search_icons`/`fetch_logo` trên 2.465 icon local + fallback Iconify),
  renderer house-style `prettygraph`, và bộ eval (F1 cấu trúc + vision judge).
  **Đây là hệ thống vượt trội hơn.**
- **`next-ai-draw-io/` — raw mxGraph XML (lớp rendering).** LLM sinh XML draw.io native
  dùng **vector stencil chuẩn** (`shape=mxgraph.aws4.resourceIcon;resIcon=…`,
  `image=img/lib/azure2/…svg`), auto-fix XML 27 bước, browser preview, VLM validation.
  33 thư viện shape / ~4.281 stencil, hiện chỉ được document dưới dạng markdown
  (`docs/shape-libraries/*.md`) — **chưa có index dạng machine-readable**.

**Vấn đề chất lượng (tại sao output trông "ổn nhưng chưa production"):** backend xuất
`.drawio` qua [gv_to_drawio.py](backend/src/diagram_mcp/gv_to_drawio.py) và
[prettygraph.dot_to_drawio](backend/src/diagram_mcp/prettygraph.py#L535), đặt mỗi node là
`shape=image;image=data:image/png,<base64>` — **ảnh PNG raster nhòe trong layout cứng của
Graphviz**. next-ai thì có **vector stencil sắc nét, chỉnh sửa được** nhưng LLM phải tự đoán
tên stencil (dễ sai) và không có blueprint/critic.

**Quyết định (đã xác nhận với người dùng):** giữ **backend làm bộ não**, nâng cấp output
draw.io sang **native vector stencil**, và biến next-ai thành **dịch vụ render+validate
headless** mà agent gọi. Kết hợp toàn bộ, chia phase để mỗi giai đoạn đều có giá trị
độc lập.

Kế hoạch này trả lời trực tiếp ba câu hỏi ban đầu:
1. **Kết hợp hai approach như thế nào** — orchestration của backend giữ nguyên; ta bridge
   catalog stencil của next-ai vào icon resolver của backend và emit native stencil khi export.
   (Component 1–3.)
2. **Có nên custom MCP của next-ai không** — có, nhưng dưới dạng **microservice render/validate
   stateless qua HTTP**, không phải một bộ não cạnh tranh. (Component 4.)
3. **Cải thiện baseline (search/fetch icon + hơn nữa)** — `resolve_icons`/`search_icons` có
   thêm tầng native stencil với style đã verify; emitter chuyển sang vector; critic review
   render draw.io *thật*. (Component 1–5.)

---

## Component 1 — Stencil catalog (dữ liệu cầu nối)

**Mới:** `backend/scripts/build_stencil_catalog.py` → ghi ra `resources/stencils_catalog.json`.

Parse từng file `next-ai-draw-io/docs/shape-libraries/*.md`:
- Block `## Usage` → **template style** chính xác (khác nhau theo loại thư viện:
  `resourceIcon`+`resIcon` cho aws4, `shape=` thuần cho gcp2, `image=…svg` cho azure2,
  `prIcon` cho kubernetes).
- Danh sách `## Shapes` → tên shape hợp lệ (azure2 còn có `### {category}`).

Cấu trúc output (một entry mỗi thư viện, nhóm theo provider đã chuẩn hóa):
```json
{
  "aws":   {"library":"aws4","kind":"resIcon","style":"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{shape};fillColor=#ED7100;strokeColor=#fff;verticalLabelPosition=bottom;verticalAlign=top;align=center;","shapes":["ec2","s3",...]},
  "gcp":   {"library":"gcp2","kind":"shape","style":"shape=mxgraph.gcp2.{shape};fillColor=#4285F4;...","shapes":[...]},
  "azure": {"library":"azure2","kind":"image","style":"image;aspect=fixed;image=img/lib/azure2/{category}/{shape}.svg;...","shapes_by_cat":{...}},
  "k8s":   {"library":"kubernetes","kind":"prIcon","style":"shape=mxgraph.kubernetes.icon;prIcon={shape};fillColor=#326CE5;...","shapes":[...]}
}
```
Bảng chuẩn hóa provider (`aws→aws4, azure→azure2, gcp→gcp2, k8s→kubernetes, alibabacloud→alibaba_cloud, …`).
Catalog sinh một lần rồi commit; sinh lại khi `docs/shape-libraries/` thay đổi.

## Component 2 — Icon resolution có bridge stencil (cải thiện baseline)

**Mới:** `backend/src/diagram_mcp/stencils.py`
- Load `stencils_catalog.json` một lần (theo pattern load manifest ở
  [tools.py:_search_icon_hits](backend/src/diagram_mcp/tools.py#L77)).
- `resolve_stencil(provider, keyword) -> {style, library, shape} | None` — tái dùng logic
  match tokenized all-terms đang dùng cho raster pack, so với tên shape trong catalog; điền
  vào template style.
- `search_stencils(query, provider) -> list[{shape, style}]` cho trường hợp miss.

**Sửa** [tools.py:resolve_icons](backend/src/diagram_mcp/tools.py#L244) để mỗi entry trả về
**cả hai tầng** (PNG preview vẫn hoạt động *và* export đi vector):
- `drawio_style`: style native stencil đã verify (ưu tiên khi export), khi catalog có kết quả.
- `path`/`icon`: hit raster pack (hiện tại) — vẫn dùng cho PNG preview Graphviz và fallback
  export cho brand logo.

Thứ tự phân giải icon: **(1)** catalog stencil native → `drawio_style` (+ raster cho preview);
**(2)** raster pack local (hiện tại); **(3)** `fetch_logo` (Iconify/favicon). Ghi tất cả vào
`icon_plan.json` để revision run tái dùng. Thêm tool `search_stencils` vào `DRAWER_TOOLS`
([tools.py:503](backend/src/diagram_mcp/tools.py#L503)).

## Component 3 — Drawio emitter xuất native stencil

Truyền `drawio_style` của node qua sidecar hiện có để export ra vector trong khi Graphviz
vẫn tính layout:
- **Mở rộng** `prettygraph._write_sidecar` ([prettygraph.py:405](backend/src/diagram_mcp/prettygraph.py#L405))
  — record mỗi node (hiện tại là `{label, sublabel, kind, fill, stroke, icon}`) thêm field
  `drawio_style`, phân giải từ catalog theo provider/icon của node.
- **Sửa** `dot_to_drawio` ([prettygraph.py:535](backend/src/diagram_mcp/prettygraph.py#L535))
  và `gv_to_drawio.convert` ([gv_to_drawio.py](backend/src/diagram_mcp/gv_to_drawio.py)): khi
  node có `drawio_style`, emit cell native stencil đó; nếu không thì fallback về cell raster
  `shape=image;image=data:…` hiện tại (cho brand logo). Giữ nguyên x/y Graphviz + cluster
  box + edge.
- **Sửa** data-URI sai định dạng ở cả hai emitter: `data:image/png,` → `data:image/png;base64,`
  ([gv_to_drawio.py:34](backend/src/diagram_mcp/gv_to_drawio.py#L34),
  [prettygraph.py:438](backend/src/diagram_mcp/prettygraph.py#L438)).

Sau bước này, file `.drawio` mở trong draw.io sẽ hiển thị stencil AWS/Azure/GCP/K8s sắc nét,
đổi màu được — **đây là bước nhảy "trông production" lớn nhất** — với raster chỉ còn cho
brand logo gap.

## Component 4 — Custom headless MCP của next-ai (dịch vụ render + validate)

Tùy biến `next-ai-draw-io/packages/mcp-server` thành **microservice render/validate stateless**
mà Python backend gọi qua HTTP (next-ai đã có sẵn `electron/` + `playwright.config.ts` nên
headless render là khả thi):
- Thêm **HTTP endpoint/transport** song song với stdio server hiện tại.
- **Headless render** mxGraph XML → PNG qua drawio-desktop CLI hoặc Playwright (không cần tab
  browser của người dùng).
- Tool mới: `resolve_stencil(provider, keyword)` (đọc cùng `stencils_catalog.json`),
  `render_drawio_png(xml)`, `validate_drawio(xml)` (tái dùng `validateMxCellStructure`/
  `autoFixXml` từ `lib/utils.ts`, + VLM tùy chọn với category `icon_broken` bổ sung).
- **Critic của backend** sau đó inspect **render draw.io thật** (native stencil, font thật)
  thay vì PNG Graphviz — lấp lỗ hổng "người dùng mở thấy khác với những gì critic review".
  Kết nối qua HTTP client mỏng ở backend; `inspect_diagram`/critic prompt trỏ vào PNG headless.

## Component 5 — Prompts, skills, evals

- **Drawer prompt** ([prompts.py](backend/src/diagram_mcp/prompts.py) `build_drawer_prompt`) +
  `skills/drawer/diagrams-as-code` & `pro-style`: "resolve_icons giờ trả `drawio_style` native
  stencil — ưu tiên dùng; không bao giờ tự gõ tên stencil; raster chỉ cho brand logo gap."
- **Critic** ([skills/critic/SKILL.md](backend/skills/critic/SKILL.md)): thêm check
  `blank_icon` / raster-khi-đã-có-stencil; review PNG headless drawio.
- **Evals** ([backend/evals/diagram/judge.py](backend/evals/diagram/judge.py)): thêm metric
  `icon_native_ratio` (tỷ lệ node vector vs raster) và đếm blank-icon vào rubric.

---

## Phân phase (mỗi phase có thể ship độc lập)

1. **Phase 1 — Catalog + resolver bridge** (Component 1–2). Đòn bẩy cao nhất, chưa đổi gì
   ở rendering: `resolve_icons`/`search_stencils` trả về style native đã verify. Diệt tận gốc
   việc đoán tên stencil.
2. **Phase 2 — Native emitter** (Component 3). File `.drawio` xuất ra trở thành vector. Đây là
   bước nhảy "trông production" rõ nhất.
3. **Phase 3 — Headless next-ai MCP** (Component 4). Critic review render draw.io thật.
4. **Phase 4 — Prompts/skills/evals** (Component 5) + kiểm tra hồi quy.

## File quan trọng

- **Tạo mới:** `backend/scripts/build_stencil_catalog.py`, `resources/stencils_catalog.json`,
  `backend/src/diagram_mcp/stencils.py`.
- **Sửa:** [tools.py](backend/src/diagram_mcp/tools.py) (`resolve_icons`, `search_icons`,
  `DRAWER_TOOLS`), [prettygraph.py](backend/src/diagram_mcp/prettygraph.py) (`_write_sidecar`,
  `dot_to_drawio`, `_b64_image`), [gv_to_drawio.py](backend/src/diagram_mcp/gv_to_drawio.py),
  [prompts.py](backend/src/diagram_mcp/prompts.py), `backend/skills/drawer/*`,
  `backend/skills/critic/SKILL.md`, [judge.py](backend/evals/diagram/judge.py).
- **next-ai:** `next-ai-draw-io/packages/mcp-server/src/` (HTTP transport, headless render,
  tool mới).

## Kiểm tra

- **Catalog:** chạy generator; kiểm tra số provider và tổng shape (~4.281 trên 33 thư viện);
  spot-check `aws.shapes` có `ec2`, `azure.shapes_by_cat` có `compute/Virtual_Machine`.
- **Unit test resolver:** `resolve_stencil("aws","ec2")` → style resIcon aws4; `resolve_icons`
  cho node aws/azure/gcp/k8s trả `drawio_style` không null; brand product (vd "Supabase")
  rơi xuống `fetch_logo` raster.
- **Emitter:** render một eval case (vd
  [case_04](backend/evals/diagram/dataset/case_04_document_understanding_slide.json)) →
  `export_drawio` → `grep` thấy cell `mxgraph.aws4`/`image=img/lib/azure2` và `data:image/png`
  chỉ cho gap logo. Mở trong draw.io: icon sắc nét, đổi màu được.
- **Headless MCP:** `render_drawio_png(xml)` trả PNG không cần tab browser; `validate_drawio`
  bắt được tên stencil sai cố ý.
- **Evals:** chạy `backend/evals/diagram/run_eval.py`; `icon_native_ratio` tăng, blank-icon
  count bằng 0, structural F1 không giảm.
