# Plan: Skill "drawio-mcp-adapter" cho `.agents/skills/`

## Context

Repo `diagram_code_agent` gồm 3 phần:
- **`backend/`** — deep agent (deepagents + LangGraph, `gpt-5.4-mini`). Drawer subagent viết code `diagrams` (mingrammer) → `render_diagram` chạy subprocess → **Graphviz** sinh `out.png` (raster) + `out.dot`; `export_drawio` convert `out.dot`→`out.drawio` (`gv_to_drawio.py`/`prettygraph.py`). Icon là **PNG raster** từ icon-pack (`search_icons`/`fetch_logo`). Critic soi PNG raster.
- **`frontend/`** — Vite+React, **display-only**: nhận `png_base64` qua AG-UI SSE (`/agui`), render `<img>`, cho download `.drawio` + mở diagrams.net ngoài. KHÔNG embed editor.
- **`next-ai-draw-io/`** — project tham khảo độc lập (frontend thật KHÔNG import). Chứa `packages/mcp-server` = `@next-ai-drawio/mcp-server` (stdio), drive draw.io embed thật → cho ra **vector** mxgraph shapes + 33 docs shape-library (`docs/shape-libraries/*.md`, gồm AWS2025/azure2/gcp2/material_design).

**Vấn đề chất lượng hiện tại:** pipeline backend cho ra icon raster + layout Graphviz cơ học → kém "production". Cửa thắng lớn nhất là **render qua draw.io thật** (icon vector crisp, layout/edge-routing draw.io, round-trip edit theo cell ID). Bạn muốn dùng `langchain-mcp-adapters` để backend gọi được các tool của draw.io MCP server, và muốn **một skill** ghi lại cách làm này trong `.agents/skills/`.

**Outcome:** một skill knowledge/recipe trong `.agents/skills/drawio-mcp-adapter/` để bất kỳ ai (Claude Code) làm trong repo này đều biết cách wire `@next-ai-drawio/mcp-server` vào deepagents backend qua `langchain-mcp-adapters` — đúng pattern, kèm cạm bẫy và lý do về quality. Skill là tài liệu + recipe copy-paste; KHÔNG sửa code backend trong phạm vi này (sẽ làm sau nếu bạn muốn).

## Phạm vi: tạo files (read-only mọi thứ khác)

1. `.agents/skills/drawio-mcp-adapter/SKILL.md`
2. `.agents/skills/drawio-mcp-adapter/references/integration-recipe.md`

Theo đúng format skill hiện có (frontmatter `name`/`description`, body markdown — xem `langchain-fundamentals/SKILL.md`).

## Nội dung `SKILL.md`

Frontmatter:
```
name: drawio-mcp-adapter
description: INVOKE khi muốn deep agent backend render/chỉnh draw.io "thật" (vector icons, layout draw.io) qua @next-ai-drawio/mcp-server bằng langchain-mcp-adapters. Covers persistent-session pattern, load_mcp_tools, wiring vào drawer subagent, và các caveat headless/stdio.
```

Các section:
- **Khi nào dùng** — khi cần icon vector + look draw.io thật thay cho Graphviz raster; authoring local/desktop hoặc eval. KHÔNG mặc định cho mọi request multi-tenant (xem caveat).
- **Tools có sẵn** từ server: `start_session`, `create_new_diagram(xml)`, `edit_diagram(operations[])`, `get_diagram()`, `export_diagram(path, format)` (drawio/png/svg). Nhắc XML là mxGraphModel; `edit_diagram` BẮT BUỘC gọi `get_diagram` trước (server reject nếu >30s).
- **Pattern BẮT BUỘC: persistent session.** Server giữ `currentSession` in-process (singleton, port 6002) → phải dùng `async with client.session("drawio") as session: tools = await load_mcp_tools(session)`. KHÔNG dùng `MultiServerMCPClient.get_tools()` (tạo stdio session MỚI mỗi tool-call → mất `currentSession`, mọi `edit_diagram` fail "No active session"). Snippet config stdio: `{"command":"npx","args":["@next-ai-drawio/mcp-server@latest"],"transport":"stdio"}`.
- **Caveats (đặt nổi bật):**
  - Server gọi `open()` mở browser thật + export PNG/SVG đi qua browser iframe → trên server headless phải point một Chromium headless vào `http://localhost:6002?mcp=<sessionId>`; chỉ `export_diagram(format=drawio)` (ghi XML thuần) chạy được không cần browser.
  - Single-session/process → mỗi thread cần 1 process+port riêng; không an toàn cho concurrency mặc định.
  - LangChain docs tự cảnh báo stdio MCP dành cho máy người dùng, không nên dùng trong web-server context — cân nhắc lift phần XML thuần (validate/ops) thành `@tool` native thay vì phụ thuộc server stdio per-request.
- **Quality wins** (lý do): icon vector (`mxgraph.aws4.resourceIcon`, azure2, gcp2, material_design SVG) > raster; tận dụng 33 `docs/shape-libraries/*.md`; `validateAndFixXml` + `applyDiagramOperations` đã được tôi luyện; round-trip critic↔drawer trên cell ID thật.
- Trỏ tới `references/integration-recipe.md` cho code đầy đủ.

## Nội dung `references/integration-recipe.md`

Recipe copy-paste để wire vào backend deepagents (dựa trên `backend/src/diagram_mcp/agent.py` + `tools.py`):
- Cách mở persistent `client.session("drawio")` ở scope sống suốt 1 run, `load_mcp_tools(session)`, gom vào `DRAWER_TOOLS` của drawer subagent (`_drawer_subagent` trong `agent.py:283`).
- Phương án **"native draw.io render path"** song song với path Graphviz hiện tại: drawer tự viết mxGraphModel XML (tham chiếu shape-library docs) → `create_new_diagram`/`edit_diagram` → `export_diagram(png)` cho critic soi → `export_diagram(drawio)`.
- Lưu ý map `out.png`/`out.drawio` vào artifact mà `server.py` đang surface (giữ contract AG-UI `png_base64`/`drawio`).
- Stub headless-browser attach (Playwright point vào `?mcp=<id>`) cho server mode; ghi rõ đây là phần cần thêm hạ tầng.

## Verification

- `head -5 .agents/skills/drawio-mcp-adapter/SKILL.md` — đúng frontmatter `name`/`description`.
- Đối chiếu format với `.agents/skills/langchain-fundamentals/SKILL.md` (frontmatter + body).
- Đọc lại SKILL.md xác nhận pattern persistent-session + 3 caveat (browser/headless, single-session, stdio-warning) đều có mặt.
- (Tùy chọn, ngoài plan) PoC chạy thật: `claude mcp add drawio -- npx @next-ai-drawio/mcp-server@latest` rồi thử `start_session`→`create_new_diagram` để xác nhận recipe — sẽ làm khi bạn muốn wire vào backend.
