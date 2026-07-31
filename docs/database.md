# Database

PostgreSQL 16. Có **hai nhóm bảng hoàn toàn tách biệt** trong cùng một database, sở hữu bởi hai bên khác nhau.

---

## 1. Nhóm bảng của LangGraph — `langgraph_*`

Sở hữu bởi thư viện. `AsyncPostgresSaver` (checkpointer) + `AsyncPostgresStore` (store) tự `setup()` idempotent lúc lifespan khởi động (`agent/persistence.py::make_persistence()`), dùng chung một `psycopg_pool.AsyncConnectionPool(max_size=20)`.

**Luật:**
- **Không** viết migration, không `ALTER`, không query trực tiếp các bảng này. Schema thuộc về LangGraph và đổi theo version thư viện.
- Muốn đọc lịch sử hội thoại thì đi qua API của graph (`aget_state`, `astream`), không qua SQL.
- Nâng version LangGraph có thể kéo theo migration nội bộ của nó — chạy một lần trên staging trước.

Không có `DATABASE_URL` thì cả hai rơi về `MemorySaver()` + `InMemoryStore()` kèm log cảnh báo. Chỉ dùng cho dev; restart là mất sạch.

---

## 2. Bảng do dự án quản — `conversations`

Sở hữu bởi `backend/src/conversations.py`. Đây là **metadata hội thoại cho UI**, không phải trạng thái agent.

```sql
CREATE TABLE IF NOT EXISTS conversations (
    thread_id     TEXT PRIMARY KEY,
    name          TEXT        NOT NULL DEFAULT 'Untitled',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_message  TEXT        NOT NULL DEFAULT '',
    messages_json TEXT        NOT NULL DEFAULT '[]',
    state_json    TEXT        NOT NULL DEFAULT '{}',
    outcomes_json TEXT        NOT NULL DEFAULT '[]',
    owner_email   TEXT        NOT NULL DEFAULT ''
);
```

`thread_id` là khoá nối duy nhất sang thế giới LangGraph và sang workspace trên đĩa (`ARTIFACTS_DIR/<thread_id>`).

`outcomes_json` lưu kết quả gate (`record_gate_outcome`). `owner_email` là quyền sở hữu thread: caller đã xác thực đầu tiên chạm vào thread sẽ **claim** nó (`security/ownership.py`); người khác nhận 404. Chuỗi rỗng nghĩa là **chưa ai sở hữu** — hàng dữ liệu cũ trước khi tính năng này ra đời, hoặc thread chưa ai claim; hàng chưa sở hữu vẫn hiện với mọi người để không khoá người dùng cũ ra ngoài.

### Advisory run lease (không có bảng)

`POST /agui` dùng `pg_try_advisory_lock(bigint)` trên một connection riêng để serialize run theo `(tenant_id, thread_id)`. Đây là session-level lock, không phải row/table: connection được giữ đến khi SSE kết thúc hoặc disconnect, rồi gọi `pg_advisory_unlock`; nếu process/connection chết PostgreSQL tự nhả lock. Vì vậy không có TTL table hay migration, và tuyệt đối không trả connection giữ lock về pool trước khi response kết thúc.

Không có `DATABASE_URL` (dev), cùng contract được mô phỏng bằng map process-local; nó không phải distributed lock và không thay thế Postgres trong multi-process deployment.

---

## 3. Luật migration

Dự án **không dùng Alembic hay bất kỳ framework migration nào**. Cách tiến hoá schema là *idempotent DDL chạy lúc startup*, trong `conversations.py`:

- `_DDL` — `CREATE TABLE IF NOT EXISTS`, luôn phản ánh schema đầy đủ hiện tại.
- `_ALTER_STATEMENTS` — danh sách `ALTER TABLE … ADD COLUMN IF NOT EXISTS …`, append-only.

Thêm cột mới thì làm **cả hai**: thêm vào `_DDL` (cho DB mới) **và** thêm một `ALTER … IF NOT EXISTS` (cho DB đang chạy). Bỏ sót vế thứ hai là hỏng deploy trên môi trường sẵn có.

Ràng buộc kỹ thuật quan trọng, đã có comment trong file: **mỗi entry trong `_ALTER_STATEMENTS` phải là MỘT câu lệnh**, chạy bằng các lần `conn.execute()` riêng — không nối bằng dấu chấm phẩy. psycopg3 gửi `execute()` không tham số qua extended query protocol, vốn không chấp nhận nhiều câu lệnh.

Không xoá cột, không đổi tên cột. Cột hết dùng thì để lại và ngừng ghi vào.

`setup()` **nuốt lỗi và chỉ log warning** — có chủ ý: DB tạm lỗi không được làm app không boot được. Hệ quả: một migration hỏng sẽ hiện ra dưới dạng lỗi query muộn hơn, không phải crash lúc start. Đọc log dòng `conversations table ready` khi deploy.

---

## 4. Dữ liệu KHÔNG nằm trong Postgres

| Dữ liệu | Nằm ở đâu |
|---|---|
| Artifact của một thread (`blueprint.json`, `wbs.json`, `out.png`, `out.pptx`…) | Đĩa: `ARTIFACTS_DIR/<thread_id>/` — xem `architecture.md` §4 |
| Memory bền của agent | File `AGENTS.md` trong `/memories/` và `/global-memories/` |
| Corpus past-project | `backend/data/*.json` + Qdrant collection `bnk_solutions` |
| Artifact nhị phân đang phục vụ cho UI | LRU **in-memory** trong `runtime/` (512 MB, TTL 30 phút) — mất khi restart, đây là hạn chế đã biết |

Nghĩa là backup Postgres **không** đủ để khôi phục một thread: phải backup cả `ARTIFACTS_DIR`.
