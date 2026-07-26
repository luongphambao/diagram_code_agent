# API Contracts

Hình dạng request/response, auth, và giao thức đặc thù (SSE, gate resume, artifact ref).
Danh sách endpoint đầy đủ **không** ghi ở đây — code là nguồn sự thật, xem `backend/src/routers/`.

---

## 1. Bề mặt

| Prefix | Router | Vai trò |
|---|---|---|
| `POST /agui` | `routers/chat.py` | Kênh chat AG-UI (SSE). Endpoint quan trọng nhất |
| `POST /upload` | `routers/upload.py` | Upload tài liệu, stream thẳng ra đĩa |
| `/conversations` | `routers/conversations.py` | GET/POST danh sách; PATCH/DELETE `/{thread_id}`; GET `/{thread_id}/history` |
| `/comments` | `routers/comments.py` | GET/POST bình luận; POST `/resolve` |
| `/health`, `/health/live`, `/health/ready`, `/version` | `server.py` | Ops |
| `GET /api/artifacts/:key`, `GET /healthz` | `runtime/src/index.ts` | Do Node runtime phục vụ, không phải backend |

Browser không gọi `/agui` trực tiếp. Nó gọi `/api/copilotkit` (Node runtime) và runtime mới gọi `POST /agui`. Xem `architecture.md` §1.

---

## 2. Auth

Identity được **resolve ở phía server**, không bao giờ đọc từ body request.

- `AUTH_MODE=header` — đọc `AUTH_HEADER_EMAIL` / `AUTH_HEADER_ROLE` (mặc định `X-Auth-Request-Email` / `X-Auth-Request-Role`, kiểu oauth2-proxy). nginx và Node runtime đều forward hai header này.
- `AUTH_MODE=bearer` — đối chiếu `AUTH_BEARER_TOKENS`.
- `AUTH_MODE=none` — chỉ dev; **bị từ chối khi `APP_ENV=production`**.

Role điều khiển quyền duyệt gate (`ROLE_GATE_PERMISSIONS` / `can_approve`). Trước đây `/agui` từng đọc `userEmail`/`userRole` từ JSON body — nghĩa là ai cũng tự nhận role duyệt. **Đừng bao giờ quay lại kiểu đó.** Xem ADR `0007`.

**Quyền sở hữu thread:** caller đã xác thực đầu tiên chạm vào một `thread_id` sẽ claim nó (`security/ownership.py::ensure_owner`). Người khác nhận **404**, không phải 403 — cố ý, để không tiết lộ sự tồn tại của thread.

---

## 3. `POST /agui` — kênh chat

Request theo giao thức AG-UI: `threadId`, `runId`, `messages[]`, `state`, `forwardedProps` (mang `file_ids`, `userRole`, `diagramKind` do CopilotKit provider đặt). Response là **SSE**.

Backend làm, theo thứ tự:
1. Resolve `Identity` từ header → `ensure_owner(thread_id)`.
2. `set_current_workspace(resolve_workspace(thread_id))` — bind ContextVar workspace cho toàn bộ request.
3. Phân biệt **chat thường** vs **resume gate** (xem §4).
4. `AGENT.astream(...)` với stream mode có `custom`, để tool call bên trong subagent nổi lên thành ACTIVITY event.
5. Dịch event LangGraph → event AG-UI (`session/sse.py`).

Yêu cầu hạ tầng: SSE cần `proxy_buffering off` và timeout dài (nginx đặt 3600s). Thêm hop proxy nào cũng phải giữ hai điều này, nếu không stream sẽ bị đệm rồi chết.

---

## 4. Giao thức HITL gate

**Khi gate kích hoạt.** deepagents interrupt **trước khi** tool chạy. Backend ghi `pending_gate.json` (+ bản nháp như `tech_stack_draft.json`) vào workspace và phát ra một decision card (`session/gate_decisions.py::_card_for`). Frontend render card qua `frontend/src/gates/registry.ts` → `cards/<Gate>Card.tsx`.

**Khi người dùng quyết định.** Client gửi lại `POST /agui` với body **kết thúc bằng một tool message**. Backend nhận diện đó là resume:

```
_pending_interrupt(config) → _decision_from_payload(payload, pending_name)
  → AGENT.astream(Command(resume={"decisions": [decision]}), ...)
```

**Menu quyết định.** `GATE_DECISIONS` khai các hành động cấp sản phẩm cho từng gate: `approve`, `approve_with_assumptions`, `accept_risk`, `request_evidence`, `request_alternative`, `reject`. `_decision_from_payload` **gấp** chúng về `approve`/`reject` mà langchain hiểu, còn `decision_record_from_payload` lưu `DecisionRecord` đầy đủ ngữ nghĩa. Thêm hành động mới thì phải làm cả hai vế — nếu không, ngữ nghĩa mất.

**Khi approve, side effect chạy theo:** `archive_approved_revision(ws)` (snapshot CSM `REV-<n>`), `record_report_step(...)`, `conv_db.record_gate_outcome(...)`.

**Ràng buộc khi thiết kế gate:** tool gate **phải nhận tham số** — nội dung để người duyệt xem chính là arg của tool. Gate không tham số render ra card rỗng.

---

## 5. Artifact ref

Backend trả file nhị phân trong payload dưới dạng base64. Node runtime chặn giữa và thay **4 field** — `png_base64`, `pdf_base64`, `pptx_base64`, `wbs_xlsx_base64` — bằng:

```ts
{ __artifact: "<key>", mime: "...", filename: "..." }
```

phục vụ tại `GET /api/artifacts/:key`. Frontend resolve qua `src/lib/artifacts.ts`.

Field `drawio` **cố ý không bị thay**: XML phải có nguyên văn ở client để dựng URL fragment mở draw.io.

Thêm field nhị phân lớn mới thì phải thêm vào danh sách thay thế ở `runtime/src/artifact-substitution.ts`, nếu không payload SSE sẽ phình và UI đơ.

Store là LRU in-memory (512 MB, TTL 30 phút) trong một process runtime **1 replica** — link artifact chết sau restart hoặc sau TTL.

---

## 6. `POST /upload`

Stream thẳng ra đĩa (không nạp hết vào RAM), chặn theo `MAX_UPLOAD_BYTES` (mặc định 25 MB) và sniff content thật thay vì tin extension (`document_parsers/content_sniff.py`). nginx đặt `client_max_body_size 32m` — nới giới hạn ở một bên phải nới cả bên kia.

Trả `file_ids` để client đưa vào `forwardedProps.file_ids` của lượt chat kế tiếp.

---

## 7. Quy ước khi thêm endpoint

- Đặt vào router theo lĩnh vực trong `routers/`, đừng gắn thẳng lên `app` (trừ endpoint ops).
- Lấy identity qua helper của `security/auth.py`; endpoint nào đụng `thread_id` **phải** gọi `ensure_owner`.
- Endpoint nào chạm file của thread thì phải bind workspace ContextVar trước — không tự ghép đường dẫn.
- Trả lỗi có cấu trúc, giữ mã đúng ngữ nghĩa: 404 cho thread không sở hữu (không phải 403), 413 cho quá cỡ, 422 cho lỗi validate.
- Không thêm version prefix (`/v1/`): đây là hệ thống nội bộ, frontend và backend deploy cùng nhau. Đổi contract thì đổi cả hai phía trong một change.
