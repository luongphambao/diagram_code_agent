# Implementation plan — các finding còn lại từ review 2026-07-30

Ngày viết: 2026-07-31
Nguồn: `docs/codex/multi-agent-architecture-review-2026-07-30.md` (§4 Findings, §8 Target
architecture, §9 Roadmap).

## Trạng thái triển khai 2026-07-31

Đã hoàn tất các mục bounded không cần dependency mới trong tài liệu này:

- **HIGH-1:** backend advisory run lease + HTTP `THREAD_BUSY`, runtime collision defense, gate identity/revision chống stale resume.
- **HIGH-2 runtime:** `/api/artifacts/:key` gọi backend artifact-authz và forward identity header trước khi đọc store.
- **P1.3:** snapshot blueprint được duyệt và validator blocking cho chain approved blueprint → render spec → Draw.io; PDF/PPT release gate dùng validator này trước khi tạo file.

P1.1 vẫn giữ quyết định không làm. P1.6 và P2 vẫn để lại vì cần chốt phạm vi/refactor/dependency riêng.

## Bối cảnh

Sau review, đã fix xong: CRITICAL-1 (RBAC), CRITICAL-2 (global memory write), HIGH-2 (artifact
authz — backend endpoint; **runtime `/api/artifacts/:key` vẫn chưa gọi nó**, xem mục cần làm thêm
bên dưới), HIGH-3 (revision drift, `session/artifact_manifest.py`), HIGH-4 (release gate blocks
export), HIGH-5 (WBS schedule fail-closed), MEDIUM-1 (pending gate resolve), MEDIUM-2 (phase machine
tường minh, `session/workflow_state.py` — xong 2026-07-31), MEDIUM-3 (Docker lockfile), MEDIUM-4
(docs registry sync — dạng hẹp, xem P1.6 bên dưới), MEDIUM-5 (validator unavailable state).

Tài liệu này chỉ liệt kê phần **chưa làm**, để tránh lặp lại phân tích đã xong ở review gốc.

## 1. HIGH-1 — Same-thread run lease (đã làm 2026-07-31)

**Hiện trạng đã xác minh (2026-07-31):**

- `runtime/src/passthrough-runner.ts`: `PassthroughRunner` giữ `Map<threadId, AbstractAgent>`
  (`inflight`, dòng 27). `run()` luôn `this.inflight.set(request.threadId, request.agent)` (dòng 30)
  — **ghi đè vô điều kiện**, không kiểm tra entry cũ có còn sống hay không.
- `isRunning()` (dòng 133-135) chỉ đọc `this.inflight.has(threadId)` — không dùng để chặn `run()` mới,
  chỉ để CopilotKit hiển thị trạng thái UI.
- `backend/src/routers/chat.py`: grep `lease|advisory_lock|pg_advisory|THREAD_BUSY|409` trong toàn bộ
  file — **không có kết quả**. Không có per-thread lock nào ở `/agui`.
- Cùng `thread_id` bind cùng workspace (`backends.resolve_workspace`) và cùng LangGraph checkpointer
  key → hai run song song ghi đè `pending_gate.json`, stage JSON, `out.*`, decision record, checkpoint.

**Đề xuất (theo §9 P0.2 của review gốc, chưa triển khai):**

1. Distributed lease `(tenant_id, thread_id)` với owner `run_id`, TTL, heartbeat. Vì DB hiện có là
   Postgres (đã dùng cho checkpointer + `conversations` table), dùng **Postgres advisory lock**
   (`pg_try_advisory_lock`) là lựa chọn không cần thêm dependency — ưu tiên hơn Redis (Redis chưa có
   trong stack, thêm sẽ vi phạm luật "không thêm dependency khi chưa hỏi").
2. `/agui` (`backend/src/routers/chat.py::agui_endpoint`) thử acquire lease đầu request; acquire thất
   bại → trả `409` với body có mã lỗi ổn định (không phải raw exception) trước khi
   `StreamingResponse` bắt đầu — giống pattern RBAC 403 hiện tại (precompute trước khi commit vào
   response 200).
3. `PassthroughRunner.run()` (runtime) nên tôn trọng `isRunning()` thật sự: nếu `inflight.has(threadId)`
   với agent khác, reject thay vì ghi đè Map — đây là lớp phòng thủ thứ hai, không thay thế lease ở
   backend (browser có thể mất kết nối mà runtime không biết run cũ đã chết).
4. Khi resume gate: kiểm `gate_id`/revision chứ không chỉ dựa vào checkpoint hiện tại của thread — để
   một resume cũ (từ tab đã đóng) không thể áp lên state đã tiến xa hơn.

**Việc cần làm trước khi code:** xác nhận owner (backend hay runtime) giữ lease — khuyến nghị backend
vì đó là nơi duy nhất có Postgres pool và đã có precompute-before-stream pattern để tái dùng
(CRITICAL-1 fix là tiền lệ trực tiếp). Cần một research pass riêng (đọc `chat.py` toàn bộ luồng resume
+ `conv_db` pool lifecycle) trước khi viết plan chi tiết như đã làm cho MEDIUM-2 — **chưa làm pass đó**.

## 1b. HIGH-2 phần runtime (đã làm 2026-07-31)

Backend đã có `GET /conversations/{thread_id}/artifact-authz` (commit `cb13ac4`). Nhưng
`runtime/src/index.ts` (`ARTIFACTS_PREFIX` handler, dòng ~73) vẫn serve `artifactStore.get(key)` trực
tiếp, không gọi endpoint đó trước. Việc còn lại: sửa route đó gọi authz endpoint (forward header auth
của request) trước khi trả file — bounded fix, không cần dependency mới, có thể làm độc lập với HIGH-1.

## 2. P1.1 — Top-level LangGraph state machine (quyết định KHÔNG làm ở dạng review đề xuất)

Review §8.1 đề xuất viết lại top-level thành `StateGraph` tường minh
(`Intake -> Analyze -> TechStackGate -> ... -> DeliveryGate`), Deep Agent chỉ chạy trong node.

**Quyết định đã chốt với user (2026-07-31):** không làm ở mức này. Thay vào đó đã triển khai
MEDIUM-2 ở dạng nhẹ hơn — `session/workflow_state.json` (state file trong workspace, không đụng
`AGENT.astream`/checkpointer). Xem chi tiết trong code (`backend/src/session/workflow_state.py`,
`backend/src/agent/middleware/phase_filter.py`).

Nếu sau này cần làm đúng đề xuất gốc của review (StateGraph thật), đây là việc **viết lại kiến trúc
điều phối**, rủi ro cao (đụng resume protocol, checkpointer schema, cách subagent được gọi) — cần một
plan mode riêng, không nối vào việc nhỏ lẻ.

## 3. P1.3 — End-to-end semantic check xuyên toàn bộ chain (đã làm 2026-07-31)

**Đã có:** `session/artifact_manifest.py::is_stale` phát hiện artifact lệch so với upstream đã ghi
nhận (`derived_from` hash chain), dùng bởi `solution_validator._staleness_findings` — nhưng đây là
**medium-severity advisory finding**, không block export.

**Chưa có:** kiểm tra semantic preservation thật (node/edge recall, coverage) tính **từ approved
blueprint revision** → render spec → Draw.io → PDF/PPT, như review đề xuất ở §4 HIGH-3 "Semantic
preservation phải kiểm từ approved blueprint revision tới render spec và từ render spec tới Draw.io."
Hiện `out.native_stats.json` so output với render spec **hiện hành**, không phải với blueprint revision
đã duyệt.

## 4. P1.6 — Registry duy nhất cho tool/gate/role/UI/docs/prompt (partial)

**Đã có:** `backend/tests/test_docs_registry_sync.py` — test hẹp, chỉ so số cụ thể (tool count, gate
count, subagent count) giữa docs và registry, bắt drift kiểu "docs nói 41 tool, code có 47". Đọc
docstring của chính test: "Deliberately narrow ... broadening this to catch every possible drift would
be a fragile, high-maintenance parser".

**Chưa có:** một registry typed duy nhất sinh ra docs/prompt/UI card mapping/role policy tự động
(đúng đề xuất gốc của review). Việc hiện tại chỉ là lưới an toàn chống số liệu lệch, không phải nguồn
sự thật duy nhất.

## 5. P2 — Scale và quality (chưa bắt đầu mục nào)

Tất cả 5 mục ở §9 P2 của review đều **cần dependency mới** (Redis hoặc object storage/S3-compatible)
hoặc là refactor hạ tầng lớn — đã thống nhất với user là "cần bàn riêng, không làm ngay":

1. Durable object storage, signed URLs, lifecycle policy cho artifact.
2. Redis/Postgres-backed runtime state thay `PassthroughRunner`'s in-memory `Map` (runtime hiện
   dùng in-memory cho cả `inflight` run map và `artifactStore`).
3. Queue/worker cho render/deck/report jobs, lease/heartbeat/retry có idempotency.
4. Tenant-aware global memory và promotion workflow (mở rộng của CRITICAL-2 fix hiện tại — hiện chỉ
   deny write, chưa phân tenant).
5. Visual eval ở kích thước slide/PDF thật (font, clipping, whitespace, content-fill) — review §6.3
   ghi nhận diagram/deck hiện pass structural metric nhưng vẫn có vấn đề trình bày khi nhìn ở kích
   thước thật.

## Thứ tự ưu tiên đề xuất cho lần làm tiếp theo

1. **HIGH-1** (run lease) — rủi ro concurrency cao nhất còn tồn tại, bounded, không cần dependency mới
   nếu dùng Postgres advisory lock.
2. **HIGH-2 phần runtime** — nhỏ, độc lập, đã có sẵn nửa backend.
3. P1.3 (end-to-end semantic check từ approved revision) — tự nhiên nối tiếp MEDIUM-2/HIGH-3 vừa làm,
   vì giờ đã có `workflow_state.json` biết gate nào approved ở revision nào.
4. P1.6 (registry thật) và P2 — cần bàn phạm vi/dependency riêng với user trước khi lên plan.
