# Testing

Chạy test kiểu gì, cái gì **phải xanh** trước commit, và cái gì tuyệt đối không được chạy tự động.

---

## 1. Phải xanh trước khi commit

```bash
cd backend
uv sync --frozen
uv run ruff format --check .
uv run ruff check .                 # chỉ E9, F821, F822, F823 — cố ý hẹp
uv run pytest tests/ -q
```

Nếu đụng frontend:
```bash
cd frontend && npm run lint && npm run typecheck && npm run format:check && npm run build
```

Nếu đụng prompt hoặc model:
```bash
cd backend && uv run python -m evals.run_all --gate
```

---

## 2. Test backend

- Vị trí: `backend/tests/` — phẳng, ~65 file `test_*.py`. **Không có `conftest.py`** ở bất kỳ đâu trong repo.
- Cấu hình ở `backend/pyproject.toml`: `testpaths = ["tests"]`, và `pythonpath` gồm `src` cùng `src/domain/{diagram,deck,reporting,wbs,validation}` — vì repo import module domain bằng tên phẳng. Thêm subpackage domain mới thì phải thêm vào cả `pythonpath` lẫn `[tool.pyright].extraPaths`.
- Không có custom marker.
- CI chạy kèm coverage: `pytest tests/ -q --cov=src --cov-fail-under=60`. **Không hạ ngưỡng 60** để làm build xanh.

**Chạy cục bộ trên Windows** (venv có sẵn ở `backend/.venv`):
```powershell
cd backend
./.venv/Scripts/python.exe -m pytest tests/ -q
```

**Đặt `SANDBOX_PROVIDER=local`** khi chạy test cục bộ, nếu không một số test sẽ gọi Modal thật và chết với `AuthError: Token missing`.

---

## 3. Các test là chốt canh — đừng xoá, đừng "đơn giản hoá"

| Test | Canh điều gì |
|---|---|
| `test_general_purpose_disabled.py` | Subagent `general-purpose` ngầm bị tắt trên mọi `create_deep_agent`; `task` chỉ có ở main |
| `test_middleware_order.py` | Thứ tự middleware + thứ tự context edit |
| `test_no_legacy_agent_module.py` | Không có `backend/src/agent.py` phẳng che package `agent/` |
| `test_workspace_isolation.py`, `test_safe_path.py` | ContextVar workspace theo thread + chống path traversal |
| `test_phase_prompt_filter.py`, `test_phase_filter_pending_gate.py` | Phase machine và van an toàn backfill / pending gate |
| `test_drawer_revise_gate.py` | Chặn vòng drawer thứ hai không được phép |
| `test_mimo_coercion.py`, `test_tool_arg_coercion.py` | Ép kiểu arg cho model stringify dict/list |
| `test_agent_run_limits.py` | Trần call theo agent + budget render |
| `test_sandbox.py`, `test_sandbox_runners.py` | Chọn runner, fail-closed |
| `test_production_upgrade.py`, `test_semantic_lint.py`, `test_waf_audit.py` | Chất lượng sơ đồ |

---

## 4. Test đang hỏng (đã biết)

`tests/test_agent_run_limits.py::test_failed_render_counts_toward_hard_cap` — nó `monkeypatch.setattr(rendering_tools.subprocess, "run", ...)`, nhưng `render_diagram` đã chuyển sang `get_sandbox_runner().render(...)` → `local_dev_runner` → `runtime/sandbox/render_exec.py` (chỗ có `subprocess.run` thật). Patch trỏ sai chỗ nên runner Modal thật được gọi và test chết với `AuthError`.
**Cách sửa đúng:** patch `runtime.sandbox.render_exec.subprocess.run`, hoặc set `SANDBOX_PROVIDER=local` bằng fixture. Test này cũng sẽ đỏ trên CI (CI không set `MODAL_TOKEN_*`).

Trạng thái đo được gần nhất: **764 collected · 760 passed · 3 skipped · 1 failed** (~63s).

---

## 5. Eval

Eval là lớp kiểm định chất lượng agent, tách khỏi unit test. Suite ở `backend/evals/` — xem `backend/evals/README.md` cho bảng đầy đủ.

```bash
cd backend
uv run python -m evals.run_all --gate            # chạy trong CI, không cần API key
uv run python -m evals.run_all --update-baseline # sau khi đổi chất lượng có chủ đích
```

**Luật:** *không có thay đổi prompt/model nào ship mà không kèm eval artifact.* Một metric bị coi là hồi quy khi trung bình rơi xuống dưới `baseline - 0.02`. Nếu chất lượng đổi là có chủ đích, chạy `--update-baseline` và commit `baseline.json` **trong cùng change** với sửa đổi prompt/model.

Trong gate (không cần API key): `intake`, `architecture`, `wbs`, `deck`, `diagram_quality`, `reality_sync`, `compliance`.

**Cố ý KHÔNG ở trong gate:**
- `evals/diagram` — cần LLM + vision.
- Vision judge của `evals/deck`.
- **`evals/e2e/run_full_flow.py` — gửi email THẬT và đặt lịch Google Calendar/Meet THẬT** (mặc định gửi tới `bao.luong@bnksolution.com`), cộng gọi LLM thật. Chạy có chủ đích, **không bao giờ** gắn vào commit hay CI.

---

## 6. Frontend & runtime

```bash
cd frontend && npm run test          # vitest; hiện chỉ có gates/__tests__/registry.test.tsx
cd runtime  && npm run test          # 6 file test: agent-shape, artifact-store,
                                     # artifact-substitution, diagram-agent,
                                     # message-integrity, passthrough-runner
```

CI **không** chạy test frontend — có comment giải thích: bộ test luồng HITL chưa có, chạy vitest rỗng chỉ là "CI theater". Khi bổ sung test thật cho gate flow thì thêm bước vào `frontend-quality`.

`runtime/src/__tests__/agent-shape.test.ts` đặc biệt quan trọng: nó canh cast `as unknown as AbstractAgent` trong `runtime/src/index.ts` (lệch type-identity giữa `@ag-ui/client` bundled và direct). Nâng version AG-UI mà test này đỏ nghĩa là cast không còn an toàn.

---

## 7. Smoke test thủ công

```bash
# Full flow qua HTTP, cần backend đang chạy
python scripts/full_flow_smoke_test.py <đường-dẫn-file-md-hoặc-txt>

# Render qua sandbox đang cấu hình
docker compose exec backend python /app/backend/scripts/render_smoke_test.py
# hoặc: cd backend && uv run python scripts/render_smoke_test.py
```

Kiểm tra boot nhanh:
```bash
cd backend
uv run python -c "import server"
uv run python -c "from agent import build_agent, make_persistence"
```

---

## 8. CI làm gì (`.github/workflows/`)

**`ci.yml`** — push lên `main`/`sandbox` và **mọi** PR:
1. `backend-quality` — sync frozen → ruff format → ruff check (hẹp) → ruff `--select ALL` (**không chặn**, ~500 hit tồn đọng) → pyright (**không chặn**, 228 lỗi tồn đọng) → pytest + coverage ≥60%.
2. `frontend-quality` — lint, typecheck, format:check, build (Node 20).
3. `security` — Gitleaks (chặn), pip-audit / npm audit / Trivy (tham khảo), CodeQL.
4. `container-build` — build image backend, **assert `/app/backend/.env` KHÔNG có trong image** (chặn), boot + curl `/health/live`, Trivy, SBOM. Image `runtime/` **không** được build trong CI.
5. `modal-smoke` — chỉ khi push `main`.

**`evals.yml`** — mọi thay đổi chạm `backend/**`: `pytest tests/ -q` **và** `evals.run_all --gate`.
