# Diagram Code Agent

Agent AI nội bộ của BnK: nhận tài liệu yêu cầu của khách → sinh **sơ đồ kiến trúc** (.drawio/.png), **WBS + ước lượng effort** (Excel theo template BnK), và **bộ đề xuất** (PPTX/PDF).
Người dùng là solution architect / BA / PM nội bộ. Mọi artifact khách sẽ nhìn thấy đều phải qua một **HITL gate** (người duyệt) trước khi tạo.
Backend là một Deep Agent (LangGraph + deepagents) điều phối 5 subagent chuyên trách; frontend là UI chat + canvas artifact.

## Stack
- **Backend**: Python 3.11, FastAPI + uvicorn, LangGraph 1.2 / `deepagents`, Pydantic. Import root là `backend/src` (import phẳng: `import backends`, `from tools import ...`).
- **Frontend**: React 19 + Vite 6 + Tailwind 4 + TypeScript, CopilotKit v2 (`@copilotkit/react-core`) trên giao thức AG-UI.
- **Runtime hop**: Node ESM service `runtime/` — CopilotKit runtime, proxy chat của browser sang `POST /agui` của backend. **Không phải** sandbox chạy code.
- **DB**: PostgreSQL 16 — LangGraph checkpointer + store, cộng bảng `conversations` do dự án tự quản.
- **Hạ tầng**: Docker Compose (postgres, backend, copilot-runtime, frontend/nginx), Modal Sandbox cho code sinh ra, Qdrant (tuỳ chọn) cho RAG past-project, Composio cho Gmail/Calendar/Meet.

## Phạm vi code
| Vùng | Trạng thái |
|---|---|
| `backend/`, `frontend/`, `runtime/`, `docker-compose.yml`, `.github/`, `scripts/` | **Code chính** — sửa ở đây |
| `CopilotKit/`, `Paper2Any/`, `open-design/`, `openwiki/`, `officecli/`, `drawio-skill/`, `.agents/skills/` | Repo/skill tham khảo được vendor về. **Không đọc, không sửa, không tính vào build.** |
| `DATA/`, `DATA.zip`, `WBS_image/`, `artifacts/`, `backend/agent_space/` | Dữ liệu nguồn & output runtime, gitignored |
| `*.drawio`, `*.png`, `scratch_*.txt`, các `.md` tên ngẫu nhiên ở root | Rác phiên làm việc cũ. Bỏ qua. |

## Lệnh
| Việc | Lệnh |
|---|---|
| Chạy tất cả (khuyến nghị) | `cp backend/.env.example backend/.env` rồi `docker compose up --build` → FE `:5173`, BE `:8001` |
| Backend dev | `cd backend && uv sync --frozen && uv run diagram-agent-server` |
| Frontend dev | `cd frontend && npm ci && npm run dev` (cần `runtime` chạy song song) |
| Runtime dev | `cd runtime && npm ci && npm run dev` (:3001) |
| Test backend | `cd backend && uv run pytest tests/ -q` |
| Eval gate | `cd backend && uv run python -m evals.run_all --gate` |
| Lint / format backend | `cd backend && uv run ruff format --check . && uv run ruff check .` |
| Lint / typecheck frontend | `cd frontend && npm run lint && npm run typecheck && npm run format:check` |
| Test frontend / runtime | `cd frontend && npm run test` · `cd runtime && npm run test` |

## Luật cấm (không ngoại lệ)
- **Không** hardcode secret/token vào code, prompt, hay Docker layer. `.dockerignore` chặn `backend/.env` — CI có assertion chặn build nếu file này lọt vào image; đừng nới lỏng.
- **Không** thêm module `backend/src/agent.py` hay biến `backend/src/backends.py` thành shim re-export — cả hai đều có test canh (`test_no_legacy_agent_module.py`, `test_workspace_isolation.py`). Xem `docs/gotchas.md`.
- **Không** cấm hành vi của subagent bằng prompt khi việc đó đụng tới file: subagent luôn nhận đủ filesystem tool bất kể `tools` khai báo. Chặn ở **permission layer** (`FilesystemPermission`).
- **Không** hardcode đường dẫn host tuyệt đối vào prompt — dùng root ảo `/workspace`.
- **Không** sửa `frontend/src/styles/tokens.css` (auto-gen từ `tokens.ts`), `runtime/dist/`, `backend/evals/*/results.json`.
- **Không** đổi ratio effort trong Python mà không đổi công thức tương ứng trong `backend/src/data/wbs_template.xlsx` — hai nơi mã hoá cùng một mô hình.
- **Không** nới `--cov-fail-under=60`, không đổi `uv sync --frozen` thành có fallback, không mở blocking ruff set thành `ALL` (xem `docs/decisions/0005-*`).
- **Không** thêm dependency mới khi chưa hỏi. `@ag-ui/client` + `@ag-ui/core` phải pin đúng `0.0.57` ở **cả** `frontend/` và `runtime/`.
- **Không** chạy `backend/evals/e2e/` trong CI hay khi test vặt — nó gửi **email thật** và đặt **lịch Google thật**.
- Cẩn thận: hook `Stop` trong `.claude/settings.json` **tự động commit** mọi thay đổi trong `backend/`, `frontend/`, `runtime/`, `.github/`, `docs/`, `docker-compose.yml`, `AGENTS.md`, `CLAUDE.md`, `.dockerignore`, `.gitignore` vào **một commit gộp mỗi lượt** (`git add -A` theo danh sách đường dẫn trên rồi commit một lần khi kết thúc lượt), message `auto: session <timestamp>`. Đã đổi từ commit-mỗi-file (PostToolUse, dựa theo đuôi file) sang batch theo lượt vì allowlist đuôi file từng bỏ sót file không đuôi (như `Dockerfile`) khiến chúng không bao giờ được track.

## Trước khi commit
1. `cd backend && uv run pytest tests/ -q` — phải xanh.
2. `cd backend && uv run ruff format --check . && uv run ruff check .` — phải sạch.
3. Nếu đụng prompt hoặc model: chạy `uv run python -m evals.run_all --gate`; nếu chất lượng đổi có chủ đích thì `--update-baseline` và commit `baseline.json` **trong cùng change**.
4. Nếu đụng frontend: `npm run lint && npm run typecheck && npm run format:check && npm run build`.

## Đọc thêm khi cần
| Khi bạn định… | Đọc trước |
|---|---|
| Hiểu ranh giới service, luồng dữ liệu, vòng đời một request | `docs/architecture.md` |
| Thêm/sửa tool, subagent, gate, middleware, budget | `docs/agent-design.md` |
| Gặp thuật ngữ nghiệp vụ lạ (WBS, CSM, blueprint, preset, zone…) | `docs/domain-glossary.md` |
| Đụng schema JSON của artifact (wbs.json, blueprint.json, deck_plan.json…) | `docs/data-contracts.md` |
| Đụng renderer PPTX, preset màu, hoặc thêm block slide | `docs/deck-design-system.md` |
| Đụng Postgres / checkpointer / store | `docs/database.md` |
| Thêm/sửa endpoint, sự kiện SSE, giao thức gate resume | `docs/api-contracts.md` |
| Viết test hoặc eval | `docs/testing.md` |
| Deploy, env var, gỡ lỗi môi trường | `docs/runbook.md` |
| Đặt file mới, đặt tên, import, xử lý lỗi | `docs/conventions.md` |
| Gặp lỗi khó hiểu hoặc token blowout | `docs/gotchas.md` |
| Thấy code "kỳ lạ" và muốn refactor | `docs/decisions/` |
| Viết thêm tài liệu cho agent | `docs/instruction.md` (house style) |
| Sửa engineer loop hoặc cơ chế memory của diagram agent | `docs/plans/2026-07-26-memory-va-engineer-loop.md` |
| Triển khai hoặc sửa BRD Agent (sinh/chỉnh sửa .docx theo section) | `docs/plans/2026-07-29-brd-agent.md` |

> `README.MD` ở root là tài liệu cũ, auto-generated, **đã lệch thực tế** (mô tả `diagram_mcp/`, `agent.py`, `RECURSION_LIMIT=160`). Đừng coi là contract; ưu tiên `docs/`.
