# Progress — Kết hợp diagram-as-code + next-ai-draw-io

Kế hoạch đầy đủ: [cozy-percolating-dawn.md](cozy-percolating-dawn.md)

---

## Component 1 — Stencil catalog ⬜ TODO

**File cần tạo:** `backend/scripts/build_stencil_catalog.py` → `resources/stencils_catalog.json`

- Parse `next-ai-draw-io/docs/shape-libraries/*.md`
- Output JSON với structure: `{aws: {library, kind, style, shapes}, azure: {…, shapes_by_cat}, gcp, k8s, …}`
- Chạy một lần, commit, sinh lại khi docs thay đổi

**Kiểm tra:** tổng ~4.281 shapes trên 33 thư viện; spot-check `aws.shapes` có `ec2`, `azure.shapes_by_cat` có `compute/Virtual_Machine`.

---

## Component 2 — Icon resolution bridge stencil ⬜ TODO

**File cần tạo:** `backend/src/diagram_mcp/stencils.py`
**File cần sửa:** `backend/src/diagram_mcp/tools.py` (`resolve_icons`, `search_icons`, `DRAWER_TOOLS`)

- Load `stencils_catalog.json` một lần
- `resolve_stencil(provider, keyword)` → `{style, library, shape} | None`
- `search_stencils(query, provider)` → `list[{shape, style}]`
- `resolve_icons` trả thêm field `drawio_style` (ưu tiên khi export)
- Thêm `search_stencils` vào `DRAWER_TOOLS`

---

## Component 3 — Drawio emitter native stencil ⬜ TODO

**File cần sửa:**
- `backend/src/diagram_mcp/prettygraph.py` (`_write_sidecar`, `dot_to_drawio`, `_b64_image`)
- `backend/src/diagram_mcp/gv_to_drawio.py`

- `_write_sidecar` thêm field `drawio_style` cho mỗi node
- `dot_to_drawio` / `gv_to_drawio.convert`: emit native stencil nếu có, fallback raster cho brand logo
- Fix data-URI: `data:image/png,` → `data:image/png;base64,`

---

## Component 4 — Custom headless MCP ✅ DONE

**Folder mới:** `mcp/` (copy codebase next-ai-draw-io/packages/mcp-server + modify)

```
mcp/
├── package.json
├── tsconfig.json
└── src/
    ├── index.ts              # MCP stdio + HTTP REST API
    ├── logger.ts             # copy
    ├── history.ts            # copy
    ├── diagram-operations.ts # copy
    ├── xml-validation.ts     # copy
    ├── http-server.ts        # copy + registerRestHandler + /api/rest/* routes
    ├── render.ts             # NEW: headless PNG (drawio CLI → Playwright fallback)
    └── stencil-resolver.ts   # NEW: resolve/search stencil từ catalog
```

**MCP tools mới (interactive):**
- `validate_drawio(xml)` — validate + auto-fix, + icon_broken check
- `render_drawio_png(xml)` — headless render → base64 PNG
- `resolve_stencil(provider, keyword)` — native stencil style từ catalog
- `search_stencils(query, provider?, limit?)` — fuzzy search khi miss

**REST API cho Python backend** (port 6002):
- `GET  /api/rest/health`
- `POST /api/rest/validate`       `{xml}` → `{valid, error, fixed, fixes, icon_broken_count}`
- `POST /api/rest/render`         `{xml}` → `{png: "<base64>", size}`
- `POST /api/rest/resolve-stencil` `{provider, keyword}` → `StencilMatch | null`
- `POST /api/rest/search-stencils` `{query, provider?, limit?}` → `StencilMatch[]`

**Còn lại để hoàn chỉnh Component 4:**
- HTTP client mỏng ở Python backend (`backend/src/diagram_mcp/mcp_client.py`) để gọi REST API
- Cập nhật critic prompt trỏ vào PNG headless thay vì PNG Graphviz
- `stencils_catalog.json` phải được build (Component 1) thì `resolve_stencil` mới có data

---

## Component 5 — Prompts, skills, evals ⬜ TODO

**File cần sửa:**
- `backend/src/diagram_mcp/prompts.py` — `build_drawer_prompt`: ưu tiên `drawio_style`, không tự gõ stencil
- `backend/skills/drawer/diagrams-as-code` & `pro-style`
- `backend/skills/critic/SKILL.md`: thêm check `blank_icon` + review PNG headless
- `backend/evals/diagram/judge.py`: thêm metric `icon_native_ratio`, đếm blank-icon

---

## Phân phase

| Phase | Components | Trạng thái |
|-------|-----------|-----------|
| Phase 1 — Catalog + resolver bridge | 1, 2 | ⬜ TODO |
| Phase 2 — Native emitter | 3 | ⬜ TODO |
| Phase 3 — Headless MCP | 4 | ✅ DONE (cần build catalog + HTTP client) |
| Phase 4 — Prompts/skills/evals | 5 | ⬜ TODO |
