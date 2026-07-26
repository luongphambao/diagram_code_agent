# Conventions

Đặt file ở đâu, đặt tên thế nào, import ra sao, xử lý lỗi kiểu gì.
Vi phạm những điều dưới đây thường không làm đỏ CI — nó chỉ làm code sai tầng và khó test.

---

## 1. Bố cục thư mục

**Backend** — quy tắc đặt code mới:

| Bạn đang viết | Đặt vào |
|---|---|
| Logic nghiệp vụ thuần (tính toán, parse, render, validate) | `backend/src/domain/<lĩnh vực>/` hoặc `prettygraph/` |
| Vỏ `@tool` cho agent gọi | `backend/src/tools/**` + đăng ký vào list trong `tools/__init__.py` |
| Prompt / khối prompt | `backend/src/prompts/` (khối dùng chung ở `_blocks.py`) |
| Lắp ráp agent, subagent, middleware | `backend/src/agent/**` |
| HTTP endpoint | `backend/src/routers/` |
| Đọc env / cấu hình | `backend/src/config/` |
| Gọi dịch vụ ngoài (Composio, Qdrant, Modal) | `integrations/`, `rag/`, `runtime/sandbox/` |

**Luật một chiều:** `domain/*` và `prettygraph/*` **không được** import từ `tools/`, `agent/`, hay `routers/`. Chúng phải test được mà không cần LLM, không cần HTTP. Nếu bạn thấy mình cần import ngược, nghĩa là logic đó đang nằm sai chỗ.

**Frontend** — `src/app/` (khung layout), `src/components/` (thành phần lớn), `src/ui/` (primitive), `src/gates/` (khung HITL: `registry.ts` + `cards/`), `src/hooks/` (state + fetch), `src/lib/` (helper thuần), `src/styles/` (token là nguồn sự thật ở `tokens.ts`).

---

## 2. Import

Import root là `backend/src`, và các thư mục domain nằm **thẳng** trên `sys.path`. Nên:

```python
import backends                     # đúng
from tools import MAIN_TOOLS        # đúng
import wbs_tools                    # đúng — dù file ở domain/wbs/wbs_tools.py
from backend.src.domain.wbs import wbs_tools   # sai
```

Thêm subpackage `domain/` mới → thêm đường dẫn vào **cả hai**: `[tool.pytest.ini_options].pythonpath` và `[tool.pyright].extraPaths` trong `backend/pyproject.toml`.

**Không tạo shim re-export** cho module mà test có monkeypatch module-global (`backends.py` là ví dụ điển hình). Shim tách đôi globals và làm patch mất tác dụng trong im lặng. Nếu buộc phải di chuyển module như vậy, sửa luôn các test đang patch nó trong cùng change.

---

## 3. Đặt tên

- Python: `snake_case` module/hàm, `PascalCase` cho Pydantic model và dataclass, `UPPER_SNAKE` cho hằng và tên env.
- Tên tool (hàm `@tool`) là **động từ + tân ngữ**, đúng thứ mà người dùng thấy trong UI: `propose_blueprint`, `export_wbs_excel`, `find_similar_solutions`. Tool gate bắt đầu bằng `propose_`, `generate_`, `export_`, `finalize_`, hoặc `create_`.
- File artifact trong workspace: `snake_case.json`, tên bằng danh từ nghiệp vụ (`blueprint.json`, `deck_plan.json`), bộ đếm kết thúc bằng `_count.json` / `_budget.json`.
- ID trong CSM: prefix viết hoa + gạch (`REQ-`, `COMP-`, `DEC-`…). Đừng chế prefix mới nếu chưa thêm vào `csm.py`.
- TypeScript: component `PascalCase.tsx`, hook `useThing.ts`, helper `camelCase.ts`.
- Test: `backend/tests/test_<vùng>.py` phẳng (không có thư mục con, không có `conftest.py` trong repo).

---

## 4. Xử lý lỗi

- **Fail closed ở prod.** CORS (`config/cors.py`), auth (`security/auth.py`), sandbox provider (`runtime/sandbox/provider.py`) đều từ chối khởi động/chạy khi `APP_ENV=production` với cấu hình không an toàn. Giữ nguyên tính chất này khi thêm dịch vụ ngoài mới.
- **Suy giảm mềm ở dịch vụ tuỳ chọn** — Qdrant, Tavily, Composio được phép vắng mặt: bắt lỗi, trả kết quả có `status` rõ ràng, ghi log, để agent đi tiếp. Nhưng **phải nói ra**: đừng trả về mảng rỗng như thể không tìm thấy gì.
- **Không nuốt lỗi âm thầm trong normalize.** Tên section/field không nhận diện được thì WARNING; vượt ngưỡng rác thì fallback về default (bài học từ vụ PDF 13→3 trang).
- **Đường dẫn** luôn qua `runtime/safe_path.py` khi có thành phần do model hoặc người dùng cung cấp. Không nối chuỗi path bằng tay.
- **Output sandbox là dữ liệu không tin cậy** kể cả khi exit code 0 — validate trước khi phục vụ/nhúng/import.

---

## 5. Thư viện & dependency

- Không thêm dependency mới khi chưa hỏi. Backend quản bằng `uv` (`uv.lock` phải commit; CI dùng `--frozen`).
- `@ag-ui/client` và `@ag-ui/core` pin **chính xác** `0.0.57`, có `overrides` ở **cả** `frontend/package.json` và `runtime/package.json`. Nâng phải nâng cùng lúc; `runtime/src/__tests__/agent-shape.test.ts` là chốt canh cho cast `as unknown as AbstractAgent`.
- Node: `frontend/Dockerfile` cần **Node 24** (script `build-tokens.mjs` dựa vào TS stripping native); CI đang chạy Node 20. Biết sự lệch này trước khi đổi bất kỳ bên nào.
- Không dùng axios/react-query ở frontend — code hiện tại dùng `fetch` trần, giữ nhất quán.

---

## 6. Thêm thứ mới — checklist ngắn

**Thêm tool:** hàm `@tool` trong `tools/**` → thêm vào đúng list `*_TOOLS` → nếu là gate thì xem `agent-design.md` §4 → thêm test.

**Thêm gate:** `GATE_TOOL_NAMES` + `GATE_DECISIONS` + `ROLE_GATE_PERMISSIONS` + card ở `frontend/src/gates/cards/` + đăng ký `registry.ts`. Tool gate **phải có tham số**.

**Thêm subagent:** `SubagentSpec` trong `agent/subagents/` → khai `*_TOOLS` riêng → đặt call limit qua env → chặn hành vi file bằng `FilesystemPermission`, không bằng prompt → gate ở lại main agent.

**Thêm kiểu sơ đồ:** thêm nhánh vào union `DiagramSpec`, **không** thêm field vào `Blueprint` → đăng ký `RendererEntry` trong `prettygraph/native/registry.py` → thêm profile scorecard nếu tiêu chí chấm khác.

**Thêm block deck:** khai `SectionContract` trong `deck_sections.py` **và** cập nhật `backend/docs/bnk_deck_sections.md` → hiện thực renderer → thêm vào `IMPLEMENTED_BLOCKS`.

**Thêm env var:** đọc trong `config/` hoặc tại chỗ dùng, ghi vào `backend/.env.example` kèm chú thích, thêm vào bảng ở `docs/runbook.md`.

---

## 7. Commit

- Conventional commits: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`.
- Thay đổi prompt hoặc model **phải** đi kèm eval artifact trong cùng commit (xem `testing.md`).
- Lưu ý hook auto-commit trong `.claude/settings.json` sẽ tự tạo commit `auto: update <file>` cho mỗi file code được sửa — squash lại trước khi mở PR nếu muốn lịch sử sạch.
