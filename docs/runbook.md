# Runbook

Chạy, cấu hình, deploy, và gỡ lỗi môi trường.
Bẫy cụ thể theo từng lỗi: `gotchas.md`. Nguồn env đầy đủ có chú thích: `backend/.env.example`.

---

## 1. Chạy toàn bộ (khuyến nghị)

```bash
cp backend/.env.example backend/.env    # tối thiểu: OPENAI_API_KEY
docker compose up --build
```

| Service | Cổng | Ghi chú |
|---|---|---|
| `postgres` | (không expose) | postgres:16-alpine, volume `pgdata` |
| `artifacts-init` | – | busybox chạy một lần, `chmod 777 /app/artifacts` — **bắt buộc**, xem `gotchas.md` |
| `backend` | `8001` | `dns: 8.8.8.8, 1.1.1.1` (workaround DNS cho Modal — đừng xoá) |
| `copilot-runtime` | (nginx proxy) | Node CopilotKit runtime, **1 replica duy nhất** |
| `frontend` | `5173:80` | nginx phục vụ build tĩnh + proxy |

Kiểm tra: `http://localhost:5173` (UI), `http://localhost:8001/health` (backend).

---

## 2. Chạy local từng phần (dev)

Cần **cả ba** process thì chat mới hoạt động:

```bash
# 1. backend
cd backend && uv sync --frozen && cp .env.example .env && uv run diagram-agent-server   # :8001

# 2. runtime  (vite proxy /api/copilotkit → :3001)
cd runtime && npm ci && npm run dev                                                     # :3001

# 3. frontend
cd frontend && npm ci && npm run dev                                                    # :5173
```

Không có `DATABASE_URL` thì backend rơi về `MemorySaver` + `InMemoryStore` (có log cảnh báo) — đủ cho dev, mất hết khi restart.

---

## 3. Env var

Đầy đủ + chú thích: **`backend/.env.example`**. Bảng dưới là tên biến để tra nhanh.

| Nhóm | Biến |
|---|---|
| Server | `APP_ENV`, `DIAGRAM_AGENT_PORT`, `ALLOWED_ORIGINS`, `DATABASE_URL`, `ARTIFACTS_DIR`, `MAX_UPLOAD_BYTES`, `GIT_SHA`, `BUILD_TIME` |
| Model | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `MIMO_API_KEY`, `AIAND_API_KEY`, `FALLBACK_MODEL` |
| Auth | `AUTH_MODE`, `AUTH_HEADER_EMAIL`, `AUTH_HEADER_ROLE`, `AUTH_BEARER_TOKENS` |
| Sandbox | `SANDBOX_PROVIDER`, `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `MODAL_SANDBOX_APP` |
| RAG | `QDRANT_URL`, `QDRANT_API_KEY` |
| Web search | `TAVILY_API_KEY` |
| Composio | `COMPOSIO_API_KEY`, `GMAIL_CONNECTED_ACCOUNT_ID`, `GOOGLE_CALENDAR_CONNECTED_ACCOUNT_ID`, `GOOGLE_MEET_CONNECTED_ACCOUNT_ID`, `EMAIL_BRAND_NAME`, `EMAIL_SENDER_LINE` |
| Jira (delivery export) | `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY`, `JIRA_EFFORT_FIELD` |
| Budget agent | `RUN_CALL_LIMIT`, `CRITIC_CALL_LIMIT`, `ICON_CALL_LIMIT`, `DRAWER_CALL_LIMIT`, `WBS_CALL_LIMIT`, `PPT_CALL_LIMIT`, `TASK_CALL_LIMIT`, `WARN_CALL_COUNT`, `WARN_INPUT_TOKENS`, `MAIN_TOOL_SELECTOR`, `STAGE_BUDGET_USDCENT_*` |
| Render / vision | `VISION_RELAY_MAX_B64_CHARS`, `MIMO_IMAGE_BLOCK_TEXT`, `DRAWIO_CLI`, `ICONS_ROOT`, `LOGO_OUT` |
| Tracing | `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT` |
| Runtime (Node) | `BACKEND_URL`, `PORT`, `ALLOWED_ORIGINS`, `ASSERT_MESSAGE_INTEGRITY` |
| Frontend (build) | `VITE_BACKEND_URL`, `VITE_RUNTIME_URL` — **thường để trống**, mặc định là đường same-origin `/api/backend` và `/api/copilotkit` |

Model không đặt bằng env — đặt trong `backend/config.yaml` theo role (`main`, `drawer`, `critic`, `wbs_planner`, `icon_resolver`, `ppt_outline`, `ppt_generator`).

**Tư thế fail-closed ở prod:** với `APP_ENV=production`, CORS phải có `ALLOWED_ORIGINS` tường minh, `AUTH_MODE` không được là `none`, và `SANDBOX_PROVIDER=local` bị từ chối. Đây là chủ ý, không phải bug.

---

## 4. Deploy

Cả ba image build với **context là repo root** (backend Dockerfile `COPY backend`, `COPY resources`, `COPY logo`).

```bash
docker compose build --build-arg GIT_SHA=$(git rev-parse --short HEAD) \
                     --build-arg BUILD_TIME=$(date -u +%FT%TZ) backend
```
`GET /version` sẽ trả lại hai giá trị này.

Trước khi deploy, kiểm tra thủ công điều CI đã kiểm tự động:
```bash
docker run --rm --entrypoint sh <backend-image> -c 'test -f /app/backend/.env && echo LEAK || echo ok'
```
Ra `LEAK` là dừng ngay — `.dockerignore` đã hồi quy và key nằm trong layer.

**Ràng buộc scale:** `copilot-runtime` **stateful** — nó giữ map run đang chạy theo `threadId` và một LRU artifact in-memory (512 MB / TTL 30 phút). Chạy đúng **một** replica, hoặc bổ sung sticky session theo `threadId` + store dùng Redis trước khi scale out.

---

## 5. Sự cố thường gặp

| Triệu chứng | Nguyên nhân thường gặp | Xử lý |
|---|---|---|
| Chat không phản hồi, `/health` vẫn OK | Chưa chạy `runtime/` (dev) hoặc container `copilot-runtime` chết | Bật service; kiểm tra `GET /healthz` trên :3001 |
| Render treo ~300s rồi fail, chỉ trong Docker | DNS nhúng của Docker với zone Modal | Giữ `dns:` trên service backend |
| `AuthError: Token missing` khi render/test | `SANDBOX_PROVIDER=modal` mà không có token | Đặt token, hoặc `SANDBOX_PROVIDER=local` khi `APP_ENV != production` |
| Backend không ghi được artifact | Bind mount thuộc `0:0` trong container | Giữ service `artifacts-init` |
| `find_similar_solutions` trả `status: "ERROR"` | Qdrant đang bị comment trong compose | Bật lại service + `QDRANT_URL`, hoặc chấp nhận chạy không RAG |
| Backend mất sạch lịch sử sau restart | Không có `DATABASE_URL` → `MemorySaver` | Cấu hình Postgres |
| Ảnh/PPTX/PDF không tải được ở UI | Artifact LRU đã hết TTL 30 phút hoặc runtime vừa restart | Sinh lại artifact; đây là hạn chế đã biết của store in-memory |
| Container backend chạy code cũ | Image chưa rebuild sau khi sửa | `docker compose up --build backend` — **bắt buộc**, backend chạy bản `pip install -e` trong image |
| Frontend build đỏ với `ERR_UNKNOWN_FILE_EXTENSION` | Node 20 chạy `scripts/build-tokens.mjs` (cần TS stripping của Node 24) | Dùng Node 24 cho build image |
| Email/lịch được gửi ngoài ý muốn | Ai đó chạy `evals/e2e/run_full_flow.py` | Không bao giờ chạy suite này tự động |

---

## 6. Dữ liệu & script offline

```bash
cd backend
uv run python scripts/build_case_library.py       # → data/case_library.json  (corpus tự sự cũ)
uv run python scripts/build_solution_memory.py    # → data/solution_memory.json (corpus hợp nhất)
uv run python -m rag.indexer                      # nạp vào Qdrant (bnk_solutions, …)
```

Hai script đầu đọc `DATA/SLIDE_IMAGES/*/analysis.md` và các file WBS lịch sử — nằm ngoài git, cần bộ dữ liệu nội bộ. Không có chúng thì hệ thống vẫn chạy, chỉ mất phần tham chiếu dự án cũ.

---

## 7. Quan sát

- **Tracing:** đặt `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY` + `LANGSMITH_PROJECT`. Đây là công cụ chính để truy vết token blowout — mọi vụ trong `gotchas.md` đều được root-cause từ trace thật.
- **Usage:** `UsageLoggingMiddleware` ghi `usage.json` trong workspace của thread; `tool_budget_summary.json` tổng kết bộ đếm.
- **Health:** `/health`, `/health/live` (liveness), `/health/ready` (kiểm Postgres + Modal), `/version`.
