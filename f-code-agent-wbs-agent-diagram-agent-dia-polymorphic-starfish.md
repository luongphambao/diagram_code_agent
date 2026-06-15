# Áp dụng Deep Agent Context Management vào Diagram Agent

## Context (vì sao làm việc này)

Note `deep_agent_context_management.md` mô tả 13 nguyên tắc context engineering cho Deep Agent (LangGraph/LangChain). Sau khi phân tích codebase, phát hiện then chốt:

> **Codebase này đã được xây trực tiếp trên `deepagents` — đúng framework mà note mô tả.** Phần lớn nguyên tắc đã có sẵn.

**Đã triển khai sẵn (không cần làm):**
- Filesystem-first: `CompositeBackend` (workspace + /memories) — `backends.py`
- Subagent isolation: 3 subagent `icon_resolver`, `drawer`, `critic` — `agent.py`
- Compaction: `ClearToolUsesEdit` (30k token), `KeepLatestImagesEdit`, `InjectVisionAsUserEdit`
- Long-term memory: `/memories/AGENTS.md` append-only, route riêng
- Skills modular load theo role; tool search top-k + budget caps

**3 gap còn lại (mục tiêu của plan này — production, nhiều user đồng thời):**

1. **🔴 Scoping workspace (gap lớn nhất, note §3/§4/§10):** `WORKSPACE` là hằng số global cấp module (`backends.py:26`), tham chiếu **89 lần / 5 file**. Mọi thread/user dùng **chung** `agent_space/workspace/` → chạy đồng thời sẽ **đè artifact của nhau** (out.png, blueprint.json, render_count.json...). **Chưa hề có** `context_schema`/`ToolRuntime` (0 match), dù `thread_id` đã được truyền vào `config["configurable"]` (`server.py:805-815`).
2. **🟡 Vài tool output nặng vẫn inline (note §11/§12).**
3. **🟢 Phase-based compaction tại HITL gate (note §6).**

**Outcome:** các run đồng thời cô lập artifact theo thread; giảm token do output nặng đẩy ra file; context được compact tại mốc phase thay vì chỉ theo ngưỡng token.

---

## Sự thật kỹ thuật đã verify trong package `deepagents` đã cài

- `create_deep_agent` nhận `backend: BackendProtocol | BackendFactory` và `context_schema`. `BackendFactory = Callable[[ToolRuntime], BackendProtocol]`, được middleware gọi per-run qua `runtime.config` (xem `summarization.py:_get_backend`).
- Custom tool **không** dùng deepagents backend: `render_diagram` ghi thẳng `Path` global và `subprocess.run(..., cwd=str(WORKSPACE))`. → **Có 2 hệ path độc lập, cả hai phải cùng resolve về thư mục per-thread.**
- `thread_id` đọc được trong tool/middleware qua `langgraph.config.get_config()` (đã import sẵn ở `agent.py`). Ngoài graph (SSE endpoint) thì `get_config()` không có → phải truyền `thread_id` tường minh.
- deepagents có sẵn `compact_conversation` tool + `SummarizationMiddleware`, nhưng có **eligibility gate ~50%** nên gọi sớm sẽ no-op.

---

## CHANGE 1 — Per-thread workspace scoping (khó nhất)

**Ý tưởng (ít xâm lấn nhất):** giữ nguyên 89 chỗ đọc một `Path`, nhưng khiến `Path` đó **resolve theo thread** tại thời điểm gọi, thay vì sửa 89 call-site.

### 1.1 `backends.py` — thêm resolver per-thread
- Đổi `WORKSPACE = AGENT_SPACE / "workspace"` thành base private `_WORKSPACE_ROOT`.
- Thêm `current_thread_id() -> str`: gọi `get_config()`, đọc `configurable.thread_id`, **fallback ổn định `"_default"`** (KHÔNG dùng uuid ngẫu nhiên — nếu không, server đọc ngoài graph sẽ trật thư mục). Bắt `RuntimeError` khi ngoài runnable context.
- Thêm `workspace_for(thread_id=None) -> Path` = `_WORKSPACE_ROOT / (thread_id or current_thread_id())`, `mkdir(parents=True, exist_ok=True)`.
- Biến `make_local_backend` thành **BackendFactory**: nhận `runtime`, đọc thread_id, trả `CompositeBackend(default=FilesystemBackend(root_dir=str(workspace_for(thread_id))), routes={"/memories/": FilesystemBackend(root_dir=str(AGENT_SPACE), virtual_mode=True)})`. **/memories giữ global** (learnings dùng chung); chỉ default route thành per-thread.

### 1.2 `agent.py` — truyền factory (callable) thay vì instance
- Thay `backend = make_local_backend()` → truyền `backend=make_local_backend` (callable) vào **cả 4** `create_deep_agent` (main + 3 subagent). Subagent chạy trong cùng run nên `get_config()` trả **cùng thread_id** với parent ⇒ icon_resolver ghi `icon_plan.json`, drawer đọc lại, cùng thư mục.
- `workdir` trong system prompt giờ chỉ còn cosmetic (agent dùng tên file trần): đổi `workdir = str(WORKSPACE)` → `workdir = "/workspace"` (`agent.py:~530`).
- `UsageLoggingMiddleware._log` đọc `WORKSPACE / "usage.json"` → chuyển `workspace_for()`.

### 1.3 `tools.py` — chuyển hằng số import-time thành lazy resolution (phần lớn công việc, mang tính cơ học)
- Thêm helper `def _ws() -> Path: return workspace_for()`.
- Thay mọi token `WORKSPACE` → `_ws()`, và ~14 hằng `_*_FILE` (`tools.py:46-59`: `_BLUEPRINT_FILE`, `_ICON_PLAN_FILE`, `_ARCH_ANALYSIS_FILE`...) → inline `_ws() / "blueprint.json"`.
- Cập nhật helper dùng các hằng đó (`_read_json_file`/`_write_json_file`/`_bump_*`/`_render_count`/`_stage_helpers`/`_layout_audit`).
- **Quan trọng:** `render_diagram` đổi `cwd=str(WORKSPACE)` → `cwd=str(workspace_for())` (mọi `out.*` rơi vào dir per-thread); cleanup/read/`record_report_step(...)` cùng dùng `_ws()`. `_PRETTYGRAPH_SRC` (nội dung source) giữ global; chỉ chỗ **ghi** `prettygraph.py` đổi sang `workspace_for()`.

### 1.4 `server.py` — scope các reader chạy NGOÀI graph
- `_artifacts()`, `_stage_artifacts()`, `_run_metrics()`, `clear_stage_markers()`, phần `requirements.md`/`out.png`, `record_report_step(...)` → thêm tham số `thread_id`, đọc `workspace_for(thread_id)`. Caller `agui_endpoint` đã có `thread_id` (`server.py:805`) — luồn qua các call-site (≈1016, 1071, 1078, 1089, 1103-1118, 836, 861).
- `email_tools.py` (2 ref) → cùng cách `_ws()`.
- `OUTPUTS_DIR`/archive giữ global (archive chung theo timestamp+title) để giữ backward-compat.

### Rủi ro / gotcha CHANGE 1
- **Concurrency-correct:** `get_config()` dùng contextvar theo run của LangGraph ⇒ run đồng thời resolve đúng thread_id (cùng cơ chế deepagents tự dùng).
- **Backward-compat:** fallback `_default` giữ nguyên hành vi hiện tại cho test/CLI/headless; artifact cũ ở `workspace/*` thành orphan (chấp nhận được vì là scratch).
- Per-thread cũng **sửa luôn bug ngầm** va chạm budget file (`render_count.json`...) giữa các thread.

---

## CHANGE 2 — Compact heavy tool outputs (nhỏ, rủi ro thấp)

Prompt đã coi file JSON là nguồn sự thật nên thay đổi này an toàn.

- **`visualize_code_structure`** (`tools.py:1247-1279`): đang `return json.dumps(graph, indent=2)` (10-20k token). Đổi: ghi `code_structure.json` rồi trả summary gọn `{status, file, nodes, edges, groups, hint}`. Cập nhật câu ở `prompts.py:683-685` thành "ghi `code_structure.json`; drawer đọc file đó" + sửa docstring.
- **`resolve_icons`** (`tools.py:880-933`): đã ghi `icon_plan.json` nhưng vẫn trả full list. Đổi: trả summary (đếm FOUND/NOT_FOUND + path + danh sách nhãn NOT_FOUND để agent xử lý tiếp). Prompt (803, 874) đã bảo "đọc file" ⇒ an toàn.
- **`plan_style_sizes`** (`tools.py:936-1070`): giữ `pretty_kwargs` + `sizes` + `grid_cols` + 1-2 note đầu inline (load-bearing per `prompts.py:884`), đẩy phần `notes` dài còn lại vào file.
- **`fit_labels`** (`tools.py:1119-1198`): chỉ trả các node overflow + suggestion (`{overflowing, max_*_chars, fixes:[...]}`), bỏ các dòng "fit" không cần hành động; tùy chọn ghi `fit_labels.json`.

**File sửa:** `tools.py` (4 hàm return), `prompts.py` (cập nhật mô tả tương ứng).

---

## CHANGE 3 — Phase-based compaction tại HITL gate (nhỏ-vừa)

**Cách khuyến nghị (deterministic):** thêm `PhaseCompactionMiddleware(AgentMiddleware)` trong `agent.py`:
1. Dựng engine qua `create_summarization_middleware(model, backend, summary_prompt=...)` (tái dùng offload `/conversation_history/{thread_id}.md` + cơ chế `_summarization_event`).
2. Mỗi model call, soi `request.state["messages"]` tìm `ToolMessage` của gate vừa được duyệt (`name ∈ GATE_TOOL_NAMES`, status không lỗi) chưa compact; nếu có thì **bỏ qua eligibility gate 50%** và buộc summarize phần trước đó (giữ lại: decisions, artifact paths, open questions, conclusions).
3. Chỉ gắn cho **main agent** (subagent là single-phase, không cần). Phối hợp tốt với `ClearToolUsesEdit` (khác nhịp).

**Phương án nhẹ thay thế (nếu ngại middleware):** thêm `create_summarization_tool_middleware` để lộ `compact_conversation` + 1 dòng prompt bảo agent gọi sau mỗi gate. *Nhược điểm:* eligibility gate 50% khiến compact sớm bị no-op + phụ thuộc model tự gọi (kém tin cậy). → Ưu tiên phương án deterministic.

**File sửa:** `agent.py` (class mới + thêm vào `_middleware()`), tùy chọn `prompts.py` (1 dòng ghi chú context được compact sau gate).

---

## Thứ tự thực hiện đề xuất

1. **CHANGE 2** trước (cô lập, rủi ro thấp) — lợi token ngay, validate pattern "summary + path" với prompt.
2. **CHANGE 1 — lớp backends** (`workspace_for`/`current_thread_id` + factory, wire vào 4 `create_deep_agent`). Test 1 thread vẫn chạy (fallback `_default`).
3. **CHANGE 1 — lớp tools** (`_ws()`, hằng `_*_FILE`, `render_diagram` cwd). Test 2 thread đồng thời ra 2 dir riêng.
4. **CHANGE 1 — lớp server** (luồn `thread_id`). Test end-to-end concurrency.
5. **CHANGE 3** cuối (phụ thuộc per-thread backend cho offload key theo thread_id).

---

## Verification (kiểm chứng end-to-end)

- **Concurrency:** gửi 2 request `/agui` đồng thời với `threadId` khác nhau → ghi vào `agent_space/workspace/{id}/` khác nhau, không đụng `out.png`/`blueprint.json` của nhau.
- **Subagent:** `drawer` gọi qua `task` resolve **cùng thread_id** với parent (đọc được `icon_plan.json` của parent).
- **Out-of-band reader:** `_artifacts(thread_id)` đọc đúng dir agent vừa ghi (không phụ thuộc `get_config()`).
- **Backward-compat:** chạy single-thread/CLI (không có thread_id) vẫn xanh nhờ fallback `_default`.
- **CHANGE 2:** với project lớn, log token của `visualize_code_structure` giảm mạnh; agent vẫn render được nhờ đọc `code_structure.json`.
- **CHANGE 3:** sau khi duyệt `propose_blueprint`, kiểm tra context bị compact (chỉ còn decisions/paths/open questions) và `/conversation_history/{thread_id}.md` chứa bản đầy đủ.

## File then chốt
- `backend/src/diagram_mcp/backends.py`
- `backend/src/diagram_mcp/tools.py`
- `backend/src/diagram_mcp/agent.py`
- `backend/src/diagram_mcp/server.py`
- `backend/src/diagram_mcp/prompts.py`
- `backend/src/diagram_mcp/email_tools.py` (2 ref nhỏ)
