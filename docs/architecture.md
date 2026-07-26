# Architecture

Ranh giới service, luồng dữ liệu, và **lý do** mọi thứ nằm ở chỗ nó đang nằm.
Chi tiết về tool/subagent/gate: `agent-design.md`. Schema dữ liệu: `data-contracts.md`.

---

## 1. Bốn process

```
Browser (React 19 + CopilotKit v2)
   │  /api/copilotkit   (chat, AG-UI)          ┌─ nginx (prod) hoặc vite proxy (dev)
   │  /api/backend/*    (upload, conversations, comments)
   ▼
runtime/  — Node ESM, CopilotKit runtime, :3001
   │  POST /agui  (AG-UI SSE)
   ▼
backend/ — FastAPI + Deep Agent, :8001
   ├── PostgreSQL 16      checkpointer + store + bảng conversations
   ├── Modal Sandbox      chạy code render do LLM sinh ra
   ├── Qdrant (tuỳ chọn)  RAG past-project
   └── Composio           Gmail / Google Calendar / Google Meet
```

**Vì sao có hop `runtime/`.** Browser không nói chuyện trực tiếp với backend cho luồng chat. Node runtime làm ba việc backend không nên làm: (1) giữ trạng thái run đang chạy theo `threadId` (`passthrough-runner.ts`), (2) **artifact substitution** — thay 4 field base64 lớn (`png_base64`, `pdf_base64`, `pptx_base64`, `wbs_xlsx_base64`) bằng `ArtifactRef` trỏ tới `GET /api/artifacts/:key`, để payload SSE không phình, (3) chuẩn hoá message + kiểm tra byte-identity của message người dùng cuối. Xem ADR `docs/decisions/0006-copilotkit-runtime-hop.md`.

**Hệ quả vận hành:** `runtime/` **stateful, chỉ chạy 1 replica**. Artifact store là LRU in-memory (512 MB, TTL 30 phút). Scale out cần sticky session theo `threadId` hoặc store dùng Redis. Xem `runtime/README.md`.

**Đường đi same-origin.** Prod: nginx (`frontend/nginx.conf`) proxy `/api/copilotkit/` → `copilot-runtime:3001`, `/api/backend/` → `backend:8001/`. Dev: `frontend/vite.config.ts` proxy tương đương sang `localhost:3001` / `localhost:8001`. Không bake `VITE_BACKEND_URL` lúc build trừ khi thật sự cần.

---

## 2. Backend — cấu trúc gói (`backend/src/`)

| Thư mục | Vai trò |
|---|---|
| `server.py` | Tạo FastAPI app, lifespan (persistence → `build_agent` → `conv_db.setup`), CORS + security headers, `/health*`, `/version` |
| `routers/` | `chat.py` (`POST /agui`, SSE + HITL resume — file lớn nhất), `upload.py`, `conversations.py`, `comments.py` |
| `agent/` | `builder.py::build_agent()` gọi `create_deep_agent(...)`; `constants.py` (limit, skill path); `harness.py` (tuỳ biến deepagents harness, kill switch general-purpose); `persistence.py`; `streaming.py` (relay tool-call của subagent ra stream ngoài) |
| `agent/middleware/` | Chuỗi middleware — **thứ tự là contract**, xem `agent-design.md` §5 |
| `agent/subagents/` | 5 `SubagentSpec`: `icon_resolver`, `drawer`, `critic`, `wbs_planner`, `ppt_generator` |
| `tools/` | Tool LangChain hướng agent + các list `*_TOOLS` + bảng gate (`GATE_TOOL_NAMES`, `GATE_DECISIONS`, `ROLE_GATE_PERMISSIONS`) |
| `prompts/` | Builder system prompt theo agent; `_blocks.py` chứa các khối prose dùng chung + span `[[PHASE ...]]` |
| `domain/diagram|deck|reporting|wbs|validation/` | Logic nghiệp vụ thuần, không phụ thuộc LLM |
| `prettygraph/` + `prettygraph/native/` | Engine render sơ đồ: layout engine, router, repair, theme, topology, drawio writer |
| `memory/stores/` | CSM (`csm.py`, `csm_adapter.py`) + log append-only: findings, evidence, decisions, comments |
| `runtime/` | `safe_path.py`, `subprocess_utils.py`, và `runtime/sandbox/` (provider, guards, runners local/modal) |
| `session/` | Ghép state phiên: label, SSE, follow-up, normalize, gate decision, artifact |
| `security/` | `auth.py` (AUTH_MODE header/bearer/none, fail-closed ở prod), `ownership.py` (chủ sở hữu thread) |
| `config/` | `settings.py` (đọc `config.yaml` + stage budget), `models.py` (`make_llm`), `cors.py` |
| `rag/` | `indexer.py` (Qdrant), `solution_memory.py`, `benchmarks.py` |
| `integrations/` | Composio: `email.py`, `calendar.py`, `meet.py` |
| `codevis/`, `document_parsers/`, `compliance/` | Code→diagram, parser upload, control pack |

**Nguyên tắc tầng.** `domain/*` và `prettygraph/*` là code thuần, test được không cần LLM. `tools/*` là lớp vỏ mỏng bọc `domain/*` thành `@tool`. `agent/*` chỉ lắp ráp. Đặt logic nghiệp vụ vào `tools/` là sai tầng — nó sẽ không eval được.

---

## 3. Vòng đời một request `/agui`

1. `routers/chat.py` resolve `Identity` từ header (không bao giờ từ body), `ensure_owner(thread_id)`.
2. `set_current_workspace(resolve_workspace(thread_id))` — bind ContextVar workspace cho request.
3. Nếu body kết thúc bằng tool message → đây là **resume gate**: `Command(resume={"decisions": [...]})`. Ngược lại là lượt chat thường.
4. `AGENT.astream(...)` với `stream_mode` gồm `custom` để relay activity của subagent.
5. Event LangGraph → sự kiện AG-UI (`session/sse.py`), artifact lớn được `runtime/` thay bằng `ArtifactRef` ở hop kế tiếp.
6. Khi approve một gate: `archive_approved_revision(ws)` (snapshot CSM `REV-<n>`), `record_report_step(...)`, `conv_db.record_gate_outcome(...)`.

---

## 4. Filesystem ảo & trạng thái

`backends.py::make_local_backend()` trả về một `CompositeBackend` (deepagents), mọi route `virtual_mode=True`:

| Route ảo | Trỏ tới |
|---|---|
| mặc định + `/workspace/` | thư mục workspace của thread hiện tại |
| `/app/workspace/`, `/app/` | alias phòng khi model bịa prefix Docker |
| `/memories/` | `<workspace>/memories/` — bền theo thread |
| `/global-memories/` | `backend/agent_space/memories/` — bền xuyên thread |
| `<SKILLS_DIR>/` | `backend/skills/` (các `SKILL.md` đóng gói) |

Workspace mặc định `backend/agent_space/workspaces/<thread_id>`, override bằng `ARTIFACTS_DIR` (Docker: `/app/artifacts/<thread_id>`).

**Điểm tinh tế:** `_current_workspace` là một `contextvars.ContextVar`; `PerThreadFilesystemBackend.cwd` là **property** đọc ContextVar đó. Nhờ vậy một instance backend duy nhất dựng lúc startup phục vụ được mọi thread đồng thời. Đừng cache `cwd` vào biến thường, và đừng định nghĩa ContextVar này ở hai module (rò rỉ chéo thread — có test canh).

Bốn tầng trạng thái:
- **Ngắn hạn** — LangGraph state + checkpointer (Postgres), tự động.
- **Semantic** — `/memories/AGENTS.md` + `/global-memories/AGENTS.md`, luôn nạp vào system prompt. Giữ ngắn.
- **Procedural** — `backend/skills/*/SKILL.md`, đọc description lúc start, đọc full khi khớp task.
- **Episodic / corpora** — `solution_memory.json` + Qdrant, truy cập **qua tool** (`find_similar_solutions`), không nhét vào prompt.

---

## 5. Phase machine

`agent/middleware/phase_filter.py` suy ra phase từ **file có trong workspace**, không từ biến trạng thái:

```
out.pdf                    → report
deck_plan.json             → ppt
wbs.json                   → wbs
out.png | blueprint.json   → draw
tech_stack.json | architecture_analysis.json → blueprint
(không có gì)              → intake
```

Phase quyết định tập tool và phần prompt được nạp (tiết kiệm ~2.5–3K token/lượt). "Phase tiến xa nhất thắng" — nên có hai van an toàn: `_ARTIFACT_BACKFILL_TOOLS` giữ tool sản xuất một artifact còn sống chừng nào file đó chưa tồn tại, và `_pending_gate_tools` giữ tool sống để gate đang hiện có thể sửa lại.

---

## 6. Sandbox

Code render do LLM sinh ra **không chạy trong process backend**. `runtime/sandbox/provider.py` chọn runner:
- `SANDBOX_PROVIDER=modal` (mặc định) → Modal Sandbox, `block_network=True`.
- `SANDBOX_PROVIDER=local` → subprocess, **chỉ khi `APP_ENV != production`**.

Không có fallback tự động Modal→local: Modal chết thì render fail, chứ không chạy code không tin cậy trên host API. Output của sandbox (`.drawio`, SVG, DOT, tên file, stdout) vẫn là **dữ liệu không tin cậy** — phải validate trước khi phục vụ hoặc nhúng. Xem ADR `0004`.

---

## 7. Model

`backend/config.yaml` map role → model: `main`, `icon_resolver`, `drawer`, `critic`, `wbs_planner`, `ppt_outline`, `ppt_generator`. `config/models.py::make_llm()` chọn provider theo prefix tên model (`gpt-`/`o1-` → openai, `claude-` → anthropic, `mimo-` → mimo, `deepseek-ai/` → aiand) và đọc API key từ env tương ứng. Không hardcode model ở call site — luôn qua `get_model(role, fallback)`.
