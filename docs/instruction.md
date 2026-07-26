# Instruction — Thiết kế Memory, Sandbox & Tài liệu cho AI Agent

> Ghi chú thiết kế nội bộ. Nguồn tham chiếu: LangChain Deep Agents docs, `langchain-ai/open-swe`.
> Mục đích: chuẩn hoá cách xây agent và cách viết tài liệu để agent hiểu dự án.

---

## Phần 0 — Ba nguyên tắc xuyên suốt

1. **Context là tài nguyên khan hiếm.** Cái gì luôn cần → nạp sẵn. Cái gì thỉnh thoảng cần → nạp theo yêu cầu. Nhồi hết vào prompt là lỗi thiết kế, không phải lỗi model.
2. **Kiến thức bền phải do con người sở hữu và audit được.** File trong git > store vô hình. Agent tự ghi memory thì phải có trace.
3. **Cô lập trước, cấp quyền sau.** Chặn blast radius bằng hạ tầng, không bằng cách hỏi người dùng từng bước.

---

## Phần 1 — Memory pattern cho Deep Agents

### 1.1 Chọn gì

Không dùng vector DB làm memory mặc định. Deep Agents dùng **filesystem-backed memory**: memory là file, load memory = đọc file. Không embedding pipeline, không retrieval step lúc query.

Cấu hình nền:

```python
CompositeBackend(
    default=StateBackend(),          # scratch file, chết theo thread
    routes={
        "/memories/": StoreBackend(namespace=lambda rt: (rt.server_info.user.identity,)),
        "/policies/": StoreBackend(namespace=lambda rt: (rt.context.org_id,)),   # read-only
        "/skills/":   StoreBackend(namespace=...),
    },
)
# memory=["/memories/AGENTS.md"], skills=["/skills/"]
```

Lý do tách: `StateBackend` scope theo `thread_id` — sang thread mới là mất sạch. Đó là đúng cho file làm việc tạm, sai cho kiến thức bền.

### 1.2 Bốn tầng memory

| Tầng | Cơ chế | Nạp thế nào |
|---|---|---|
| Short-term | State + checkpointer | Tự động |
| Semantic (facts, preferences) | `AGENTS.md` trong Store | **Luôn** vào system prompt |
| Procedural (how-to) | Skills (`SKILL.md`) | Đọc description lúc start, đọc full khi match task |
| Episodic (past runs) | Checkpointed threads | Qua tool search, gọi khi cần |

**Luật phân loại:** luôn đúng → `AGENTS.md`. Thỉnh thoảng cần → skill. Chỉ để truy vết → episodic tool.
Nhồi tất cả vào `AGENTS.md` là sai lầm phổ biến nhất.

### 1.3 Chọn scope

- **Mặc định user-scoped** `(user_id,)`. Chỉ share khi có lý do cụ thể.
- **Org-level đặt read-only**: populate bằng application code / Store API, dùng permissions deny write hoặc policy hook. Nếu user A ghi được vào memory user B đọc → đó là kênh prompt injection.
- **Nhiều agent chung deployment**: namespace `(assistant_id, user_id)`.

### 1.4 Chiến lược ghi

Hot path (ghi trong hội thoại) là mặc định và đủ cho đa số. Background consolidation qua cron chỉ thêm khi cần giảm latency hoặc tổng hợp chất lượng.

> **Bẫy:** cron interval phải khớp lookback window của tool search. Lệch → hoặc xử lý lặp, hoặc mất memory.

### 1.5 Bốn cái bẫy

1. **Context bloat** — memory file inject vào system prompt mỗi lượt. Giữ `AGENTS.md` ở mức vài trăm từ.
2. **Agent tự quản memory** — prompt tệ thì over-save / under-save / lưu sai. Phải nói rõ cái **KHÔNG** lưu: credential, thông tin nhất thời.
3. **Concurrent write** — cùng file ghi song song → last-write-wins. Tách memory theo topic để giảm contention.
4. **Không hợp memory quy mô lớn** — tốt cho profile gọn vài trăm từ. Cần nhớ nhiều interaction quá khứ thì ghép semantic search **dưới dạng tool**, vẫn không nhét vào prompt.

---

## Phần 2 — Sandbox design (rút từ open-swe)

### 2.1 Nguyên tắc

Cô lập trước, rồi cấp full permission bên trong boundary. Không confirmation prompt từng bước, không production access.

### 2.2 Protocol tối giản

`SandboxBackendProtocol` yêu cầu:
- File ops: `ls()`, `read()`, `write()`, `edit()`, `glob()`, `grep()`
- Shell: `execute(command, timeout=None) -> ExecuteResponse`
- Identity: `id`

**Đòn bẩy thiết kế đáng copy nhất:** extend `BaseSandbox` thì mọi file operation được implement bằng cách delegate xuống `execute()`. Thêm provider mới ≈ 15 dòng — chỉ viết tầng shell.

Đánh đổi phải biết:
- Mỗi `read_file` là một shell round-trip.
- `grep`/`glob` đúng hay không phụ thuộc binary có sẵn trong snapshot.

### 2.3 Lifecycle

- Factory nhận `sandbox_id` optional: có → reconnect, không → tạo mới.
- Tự tái tạo nếu mất kết nối.
- `IDLE_TTL` mặc định 10 phút; `DELETE_AFTER_STOP` mặc định 24h.
- Snapshot từ Docker image để pre-warm: pre-install ngôn ngữ, framework, tool nội bộ → giảm setup time mỗi run.
- Cấu hình được vCPU / mem / FS capacity.

> **Hệ quả cần nhớ:** "persistent sandbox per thread" chỉ bền trong cửa sổ TTL. Follow-up sau 24h nhận sandbox trắng.

### 2.4 Credential isolation — phần quan trọng nhất

Agent chạy `GH_TOKEN=dummy gh <command>`; proxy inject auth thật ở **tầng network**. Token được mint runtime từ App installation credentials.

Quy tắc rút ra:
- **Không** lưu access token làm deployment env var.
- Credential nhạy cảm (observability, API nội bộ) giữ ở server process, mã hoá at-rest — sandbox không bao giờ cầm key.
- Chỉ load tool nhạy cảm cho run của user được authorize.

→ Sandbox bị compromise **≠** credential bị lộ.

### 2.5 Rủi ro tồn dư

- Dữ liệu attacker-influenced (log, trace, web page) + agent có network egress = prompt injection. Dùng key scoped, read-only.
- Chế độ sandbox `local` **không có isolation** — chỉ dev, bắt buộc bật human-in-the-loop.
- Validation prompt-driven (chỉ *dặn* agent chạy lint/test) là mắt xích yếu nhất. Nếu fork, vá đầu tiên bằng `@after_agent` middleware chạy CI xác định.

---

## Phần 3 — Bộ tài liệu để agent hiểu dự án

### 3.1 Nguyên tắc

**Một file luôn load + phần còn lại load theo yêu cầu.**

- `AGENTS.md` ở root = **router, không phải encyclopedia**. Dưới 150 dòng. Nói dự án là gì, chạy thế nào, luật cấm, và **chỉ đường** tới file chi tiết.
- `docs/*.md` = nội dung nặng, agent chỉ đọc khi cần.

### 3.2 Cây file

```
AGENTS.md                   # router, luôn load
docs/
  architecture.md
  database.md
  domain-glossary.md        # giá trị cao nhất cho domain agent
  conventions.md
  api-contracts.md
  testing.md
  runbook.md
  gotchas.md                # ROI cao nhất trên mỗi token
  decisions/
    0001-vi-sao-chon-x.md   # ADR
skills/
  <ten-quy-trinh>/SKILL.md
```

### 3.3 Nội dung từng file

| File | Viết gì | Ngăn được lỗi gì |
|---|---|---|
| `AGENTS.md` | Mô tả 3 dòng, stack, lệnh build/test/lint, luật cấm, bảng chỉ đường | Agent mò mẫm |
| `architecture.md` | Ranh giới service, luồng dữ liệu, cái gì gọi cái gì, **và tại sao** | Đặt code sai tầng |
| `database.md` | Bảng chính + quan hệ, quy ước đặt tên, **luật migration** | Phá schema |
| `domain-glossary.md` | Thuật ngữ nghiệp vụ, map Việt ↔ Anh | Hiểu sai ngữ nghĩa — loại bug khó phát hiện nhất |
| `conventions.md` | Cấu trúc thư mục, đặt tên, xử lý lỗi, **thư viện cấm** | Tự ý thêm dependency |
| `api-contracts.md` | Shape request/response, mã lỗi, auth, versioning | Mỗi endpoint một kiểu |
| `testing.md` | Chạy test kiểu gì, cái gì **phải xanh** trước commit | Vá điểm yếu validation prompt-driven |
| `runbook.md` | Env var, deploy, lỗi thường gặp + cách xử | Agent bí là dừng |
| `gotchas.md` | Bẫy cụ thể: file auto-gen, API trả 200 kèm lỗi trong body… | Lặp lại sai lầm cũ |
| `decisions/*.md` | Quyết định + bối cảnh + phương án đã loại | Agent "sửa" thứ cố tình làm vậy |

**Riêng dự án AI/agent, thêm:**
- `docs/agent-design.md` — danh sách tool và **khi nào dùng tool nào**, memory contract (ghi gì / cấm ghi gì), giới hạn step.
- `docs/data-contracts.md` — với IDP: loại document, schema field cần trích, quy tắc validate.

### 3.4 Cái KHÔNG cho vào

- Secret, token, connection string
- Trạng thái sprint, "đang làm task X" — hết hạn sau 2 tuần, agent đọc rồi hành động sai
- Chữ ký từng function, danh sách endpoint đầy đủ — code là nguồn sự thật
- Copy-paste code dài — agent đọc code nhanh hơn đọc mô tả code

> **Phép thử:** doc sai còn tệ hơn không có doc. Chỉ viết những gì thay đổi chậm.

### 3.5 Thứ tự triển khai

Đừng viết cả bộ trong một buổi — sẽ có 9 file nửa vời rồi mốc.

1. `AGENTS.md` + `conventions.md` + lệnh test → dùng được ngay
2. `domain-glossary.md` → nửa ngày, hiệu quả rõ nhất
3. `database.md` + `architecture.md` → khi agent bắt đầu đụng vào
4. `gotchas.md` + `decisions/` → **để tự mọc**, mỗi lần agent sai thì thêm một dòng

**Cách kiểm chứng:** viết xong `AGENTS.md`, mở session mới, bảo agent *"đọc AGENTS.md rồi mô tả lại dự án này"*. Chỗ nó mô tả sai chính là chỗ viết chưa rõ.

---

## Phụ lục A — Khung `AGENTS.md` (copy rồi điền)

```markdown
# <Tên dự án>

<Ba dòng: sản phẩm này làm gì, cho ai, giải quyết vấn đề gì.>

## Stack
- Backend: …
- Frontend: …
- DB: …
- Hạ tầng: …

## Lệnh
| Việc | Lệnh |
|---|---|
| Cài đặt | `…` |
| Chạy dev | `…` |
| Test | `…` |
| Lint / format | `…` |
| Migration | `…` |

## Luật cấm (không ngoại lệ)
- Không sửa file trong `…/generated/` — auto-gen.
- Không thêm dependency mới khi chưa hỏi.
- Không sửa migration đã merge; luôn tạo migration mới.
- Không commit khi test hoặc lint chưa xanh.
- …

## Trước khi commit
1. Chạy `<lệnh test>` — phải xanh.
2. Chạy `<lệnh lint>` — phải sạch.
3. Commit theo conventional commits: `feat:`, `fix:`, `chore:`.

## Đọc thêm khi cần
| Khi bạn định… | Đọc trước |
|---|---|
| Đụng schema / migration | `docs/database.md` |
| Thêm service hoặc đổi luồng dữ liệu | `docs/architecture.md` |
| Gặp thuật ngữ nghiệp vụ lạ | `docs/domain-glossary.md` |
| Thêm / sửa endpoint | `docs/api-contracts.md` |
| Viết test | `docs/testing.md` |
| Deploy hoặc gỡ lỗi môi trường | `docs/runbook.md` |
| Thấy code "kỳ lạ" và muốn refactor | `docs/decisions/` |
| Bị lỗi khó hiểu | `docs/gotchas.md` |
```

## Phụ lục B — Khung `gotchas.md`

```markdown
# Gotchas

Mỗi lần agent (hoặc người) mắc lỗi vì một đặc thù không hiển nhiên → thêm một mục.
Format: hiện tượng → nguyên nhân → cách xử lý đúng.

## <Hiện tượng ngắn gọn>
- **Nguyên nhân:** …
- **Đúng:** …
- **Sai:** …
```

## Phụ lục C — Khung ADR (`docs/decisions/0001-….md`)

```markdown
# 0001 — <Quyết định>

**Ngày:** YYYY-MM-DD
**Trạng thái:** accepted | superseded by 00xx

## Bối cảnh
<Ràng buộc gì buộc phải quyết định lúc đó.>

## Quyết định
<Chọn gì.>

## Phương án đã loại
- <A> — loại vì …
- <B> — loại vì …

## Hệ quả
<Cái gì trở nên khó hơn / dễ hơn vì quyết định này.>
```

---

## Checklist rà soát

**Memory**
- [ ] `AGENTS.md` dưới vài trăm từ
- [ ] Đã tách state (scratch) khỏi store (bền)
- [ ] Namespace mặc định là user-scoped
- [ ] Memory dùng chung được đặt read-only
- [ ] Prompt nói rõ cái KHÔNG lưu
- [ ] Bật trace để audit mọi lần ghi

**Sandbox**
- [ ] Không có access token trong deployment env var
- [ ] Credential nhạy cảm nằm ở server process, không ở sandbox
- [ ] Chế độ không-isolation chỉ tồn tại ở local dev
- [ ] Có snapshot pre-warm cho dependency nặng
- [ ] TTL phù hợp với nhịp follow-up thực tế

**Tài liệu**
- [ ] `AGENTS.md` là router, không phải encyclopedia
- [ ] Có `domain-glossary.md`
- [ ] Không có secret, không có trạng thái sprint
- [ ] Đã chạy phép thử "đọc AGENTS.md rồi mô tả lại dự án"
```
