# Học gì từ open-swe — Phân tích pattern & Gap cho `diagram_code_agent`

## Context

Bạn muốn rút các best-practice pattern từ **open-swe** (một coding-agent production trên LangGraph + deepagents) để áp dụng vào dự án **`diagram_code_agent`** (`backend/src/diagram_mcp/`).

Phát hiện then chốt khi khảo sát: dự án của bạn **đã chủ động port rất nhiều pattern open-swe rồi** — `findings.py` ghi rõ *"Design mirrors open-swe's reviewer_findings.py"*, bạn đã có deep agent + subagents, skills, memory route, `refine_memory.py` (continual learning), evals (judge/run_eval/target), HITL gates, middleware stack, Postgres persistence. Vì vậy tài liệu này **không liệt kê lại pattern cơ bản**, mà tập trung vào:

> **open-swe có gì → bạn đã có gì → còn thiếu gì → áp dụng vào file nào.**

Đây là **báo cáo phân tích + lộ trình học tập** (không sửa code trong phase này), phủ cả 4 mảng bạn chọn: Memory & Continual Learning, Harness & Middleware, Tools & Prompts, Evals & Multi-graph.

> Tham chiếu nhanh kiến trúc 2 bên:
> - open-swe: `open-swe/CLAUDE.md`, `agent/server.py`, `agent/reviewer.py`, `agent/analyzer.py`, `agent/middleware/*`, `agent/tools/*`
> - của bạn: `backend/src/diagram_mcp/agent.py`, `tools.py`, `prompts.py`, `findings.py`, `backends.py`, `conversations.py`, `scripts/refine_memory.py`, `evals/diagram/*`, `skills/*`

---

## Bảng tổng quan: bạn đang ở đâu

| Mảng | open-swe | diagram_code_agent | Trạng thái |
|---|---|---|---|
| Deep agent + subagents | main + reviewer + analyzer | main + icon_resolver + drawer + critic | ✅ Có, làm tốt |
| Skills (virtual files) | `/skills/` route, SKILL.md | `MAIN_SKILL_PATHS`, `skills/*/SKILL.md` | ✅ Có |
| Structured findings | `reviewer_findings.py` | `findings.py` (mirror) | ✅ Có |
| Memory persistent | thread metadata + Store | `/memories/AGENTS.md` + Postgres Store | ✅ Có |
| Continual learning | analyzer 2 mode + cron đêm | `refine_memory.py` (script thủ công) | 🟡 Có, còn thiếu |
| Context management | ClearToolUsesEdit, Summarization | ClearToolUses + KeepLatestImages + VisionRelay | ✅ Có, thậm chí vượt (xử lý ảnh) |
| Middleware stack | 12 lớp có thứ tự | ~4 lớp (context/usage/limit/fallback) | 🟡 Thiếu nhiều lớp resilience |
| Tool error handling | `ToolErrorMiddleware` → ToolMessage | (chưa thấy lớp tương đương) | 🔴 Gap |
| Per-thread isolation | sandbox riêng mỗi thread_id | **WORKSPACE dùng chung toàn cục** | 🔴 Gap nghiêm trọng |
| Eval harness | golden comments + LLM judge | judge/run_eval/target | ✅ Có |
| Model resolution | per-thread > profile > team | config.yaml per-role | 🟡 Đơn giản hơn |

Diễn giải: **bạn đã vững phần "agent shape"**. Khoảng trống thực sự nằm ở **độ bền vận hành production** (isolation, error recovery, middleware resilience) và **vòng học khép kín tự động** (continual learning).

---

## Mảng 1 — Memory & Continual Learning

### 1.0 Chẩn đoán: memory ĐANG mount đúng, nhưng KHÔNG tự cập nhật & KHÔNG archive run

**Cơ chế (đã xác minh — phần đọc không hỏng):**
```
agent.py:637  memory=[MEMORY_PATH="/memories/AGENTS.md"]
  → deepagents MemoryMiddleware(sources=["/memories/AGENTS.md"])
  → backends.py:64 CompositeBackend route "/memories/" → FilesystemBackend(root=agent_space, virtual_mode=True)
  → trên đĩa: backend/agent_space/memories/AGENTS.md  (file thật, 25 dòng, có nội dung học)
```
`MemoryMiddleware.before_agent` đọc file vào state đầu mỗi run; `modify_request` chèn vào system prompt (`<agent_memory>…`) trước MỖI model call; HTML comment bị strip (marker `<!-- last_analyzed -->` không lọt vào model). → Memory được nạp & đưa vào prompt bình thường.

**3 vấn đề thật (vì sao "không thấy kết quả mount ra"):**

1. **Không có bước tự động GHI memory sau run.** Hai đường ghi, không đường nào tự chạy đều đặn:
   - *Online*: `prompts.py:185-191` dặn agent `edit_file("/memories/AGENTS.md")` khi gate reject/approve — nhưng phụ thuộc LLM tuân thủ; với gpt-5.4-mini/mimo thường bị bỏ qua → AGENTS.md hiếm khi đổi sau run.
   - *Offline*: `scripts/refine_memory.py` (đường tạo ra nội dung hiện tại — format khớp `_SYNTHESIS_PROMPT`) chỉ chạy **thủ công** và chỉ học từ `reject` có note. Gate outcomes lưu ở Postgres `conversations.outcomes_json` nhưng "nằm chờ" tới khi chạy tay.
   - → **Áp dụng**: gọi `refine_memory` (hoặc một bước học rút gọn) tự động ở cuối mỗi run trong `server.py` (sau `RUN_FINISHED`), hoặc cron đêm (xem 1.2). Đừng chỉ dựa vào LLM tự `edit_file`.

2. **Output mỗi run KHÔNG được archive.** `backends.py:28` định nghĩa `OUTPUTS_DIR = agent_space/outputs/` ("timestamped run archives") và `_ensure_dirs()` tạo thư mục, **nhưng không có code nào ghi vào đó** — thư mục rỗng. Mọi run đè lên `agent_space/workspace/out.png`, `diagram.py`, `blueprint.json`… run sau xóa run trước.
   - → **Áp dụng**: trong `server.py` sau khi run xong, copy artifact (`out.png`/`diagram.py`/`out.drawio`/`*.json`) sang `OUTPUTS_DIR/<thread_id>-<timestamp>/`. Tận dụng `OUTPUTS_DIR` đã có sẵn.

3. **Memory nằm trên filesystem local, không phải Postgres Store** (đã có sẵn Store qua `make_persistence`). Khi deploy container/nhiều replica: `agent_space/` là ổ tạm → memory **mất khi redeploy**, mỗi replica memory riêng.
   - → **Áp dụng**: route `/memories/` vào `deepagents.backends.store.StoreBackend` (cross-thread, bền) thay vì FilesystemBackend — đúng pattern open-swe (learned content trong Store, không phải sandbox). Lưu ý: `refine_memory.py` hiện đọc/ghi file đĩa, nếu chuyển sang Store thì script cũng phải đọc/ghi qua Store.

### 1.1 Học từ CẢ tín hiệu đúng lẫn sai (gap quan trọng)

- **open-swe**: analyzer mode `continual` đọc `read_finding_outcomes()` trả về **2 nhóm**: `confirmed` (finding được resolve bằng commit → đúng) và `dismissed` (bị bỏ qua → sai). Nó **promote** pattern mà team thật sự sửa, **demote** pattern bị bỏ. Nguồn: `agent/tools/read_finding_outcomes.py`, `agent/reviewer_findings.py:upsert_finding_outcome`.
- **bạn**: `scripts/refine_memory.py:_fetch_outcomes` chỉ lấy `decision == "reject"` **có note**. Tín hiệu `approve` bị bỏ hoàn toàn.
- **Gap**: bạn chỉ học từ thất bại, không học từ thành công → AGENTS.md chỉ phình mục "Do Not Do", không bao giờ biết "cái gì user duyệt ngay" để củng cố.
- **Áp dụng**: trong `conversations.py:record_gate_outcome` bạn đã lưu cả `approve`/`reject` vào `outcomes_json` — dữ liệu đã có sẵn. Sửa `refine_memory.py:_route` để route `approve` (đặc biệt approve-không-sửa-gì) thành tín hiệu củng cố cho mục "Style Preferences". Cân nhắc thêm trọng số: pattern xuất hiện trong nhiều `approve` → giữ; trong nhiều `reject` → cảnh báo.

### 1.2 Tự động hoá vòng học (cron) thay vì chạy tay

- **open-swe**: sau bootstrap, `ensure_continual_cron` tự đăng ký cron đêm **lệch giờ theo hash repo** (`analyzer_cron.py:_daily_schedule` → `minute = hash % 60`) để tránh thundering herd; thread deterministic + threadless (mỗi đêm tạo run mới, không tích luỹ lịch sử).
- **bạn**: `refine_memory.py` chạy thủ công (`uv run python scripts/refine_memory.py`). Đã có cờ `--bootstrap`/`--continual` và timestamp `<!-- last_analyzed -->` (rất tốt) nhưng không có scheduler.
- **Áp dụng**: bạn đã có `scheduler.py`? (open-swe có graph scheduler). Cách nhẹ nhất: đăng ký một cron OS / LangGraph cron gọi `refine_memory.py --continual` mỗi đêm. Pattern timestamp incremental của bạn đã sẵn sàng cho việc này.

### 1.3 Skill-as-procedure cho chính bước học

- **open-swe**: quy trình học **không hardcode trong Python** — nó nằm trong `agent/skills/continual-learning/SKILL.md` và `bootstrap-repo-analysis/SKILL.md`, nạp qua `StateBackend` route `/skills/`. Python chỉ seed file + set `analyzer_mode`. Sửa cách học = sửa file .md, không deploy lại.
- **bạn**: logic synthesis nằm cứng trong `_SYNTHESIS_PROMPT` (Python string trong `refine_memory.py`). Bạn ĐÃ có `skills/requirement-analysis/SKILL.md`, `solution-design/SKILL.md` cho runtime — nhưng chưa có skill cho bước *học*.
- **Áp dụng**: nếu sau này nâng `refine_memory` thành một analyzer-graph thật (xem Mảng 4), hãy đưa quy trình synthesis vào `skills/continual-learning/SKILL.md` thay vì prompt cứng.

### 1.4 Memory marker ẩn — bạn đang làm rất đúng

`refine_memory.py` dùng `<!-- last_analyzed: ... -->` (deepagents strip HTML comment trước khi inject) — đây chính xác là pattern "machine marker survives on disk, invisible to model" của open-swe. Giữ nguyên. Có thể mở rộng marker để lưu thêm `processed_thread_ids` nhằm idempotent tuyệt đối.

---

## Mảng 2 — Harness & Middleware (khoảng trống lớn nhất về resilience)

open-swe có **12 middleware xếp thứ tự** quanh mỗi model call (`agent/server.py`). Bạn có ~4 (`agent.py:_middleware`): ContextEditing → UsageLogging → ModelCallLimit → (ModelFallback optional). Dưới đây là các lớp open-swe có mà bạn **nên cân nhắc bổ sung**, theo độ ưu tiên cho một diagram agent.

### 2.1 ToolErrorMiddleware — bắt exception tool → ToolMessage (nên thêm sớm)

- **open-swe** `agent/middleware/tool_error_handler.py`: tool ném exception → trả về `ToolMessage(status="error")` có cấu trúc (`error_type`, `error`, gợi ý recovery) để LLM tự sửa thay vì crash cả run. Trường hợp đặc biệt `SandboxClientError` → tái tạo sandbox.
- **bạn**: `render_diagram` chạy code `diagrams` trong subprocess (`tools.py`) — đây là nơi exception xảy ra thường xuyên (code sai, import sai, icon path sai). Nếu một tool ném exception không bắt, run có thể hỏng.
- **Áp dụng**: thêm một `ToolErrorMiddleware` bọc mọi tool, chuẩn hoá lỗi thành ToolMessage. Đặc biệt giá trị với `render_diagram`/`export_drawio` — agent thấy lỗi cấu trúc và tự fix vòng sau. *(Lưu ý kiểm tra: deepagents có thể đã bọc một phần — xác minh trước khi thêm.)*

### 2.2 SanitizeToolInputsMiddleware — ép kiểu input méo

- **open-swe** `sanitize_tool_inputs.py`: LLM hay sinh `offset='1, 80'`; middleware regex lấy số đầu trước khi Pydantic validate → tiết kiệm 1 vòng retry.
- **bạn**: tool nhận `blueprint` (dict lồng nhau phức tạp), `icons` (list). Bạn đã có `test_mimo_coercion.py` → đã từng gặp vấn đề coercion. Hãy gom logic coercion vào một middleware sanitize đầu stack thay vì rải trong từng tool.

### 2.3 "no empty message" guard

- **open-swe** `ensure_no_empty_msg.py`: model trả message rỗng (không text, không tool call) phá vỡ vòng agent → inject `no_op` để ép tiến. Một số provider (bạn đang dùng mimo-v2.5!) dễ sinh output lạ.
- **Áp dụng**: bạn đã có `InjectVisionAsUserEdit` để né lỗi mimo về image. Bổ sung guard empty-message cùng tinh thần.

### 2.4 Circuit breaker cho render loop

- **open-swe** `sandbox_circuit_breaker.py`: ≥2 lỗi sandbox liên tiếp → ngắt mạch, báo user, không loop vô hạn.
- **bạn**: bạn đã có `RENDER_HARD_CAP` + icon-search budget (rất tốt, comment trong `agent.py:379`). Đây là circuit breaker dạng đếm. Có thể nâng: khi chạm cap, trả message rõ ràng cho user (như `notify_step_limit_reached`) thay vì dừng im lặng.

### 2.5 Thứ tự middleware là HỢP ĐỒNG, không phải ngẫu nhiên

open-swe `CLAUDE.md` nhấn mạnh: sanitize **trước** validate; error-handling **trước** limit-check; fallback **cuối cùng** để bọc mọi lỗi tầng dưới. Khi bạn thêm các lớp trên vào `_middleware()`, hãy giữ trật tự: `Sanitize → ContextEditing → ToolError → ModelCallLimit → Usage → EmptyMsgGuard → CircuitBreaker → ModelFallback (cuối)`.

### 2.6 Stateless factory — bạn đã làm đúng

`build_agent(model, style, checkpointer, store)` của bạn dựng agent mới mỗi lần, state ngoài (checkpointer/store) — đúng pattern open-swe `get_agent(config)`. Giữ nguyên.

---

## Mảng 3 — Tools & Prompts

### 3.1 Defensive return shape — chuẩn hoá toàn bộ

- **open-swe**: **mọi tool** trả `dict` có `success: bool` + (`error: str` | data). Không bao giờ raise. LLM thấy lỗi có cấu trúc và tự quyết retry/đổi hướng (`web_search.py`, `fetch_url.py`).
- **bạn**: `tools.py` (2155 dòng) — cần soát xem mọi tool có return shape nhất quán không. Đây là nền tảng để 2.1/2.2 hoạt động.
- **Áp dụng**: định một convention return (vd `{"ok": bool, "error": str|None, ...}`) và áp cho toàn bộ tool trong `tools.py`. Đặc biệt `render_diagram` nên trả lỗi compile/traceback dạng cấu trúc để drawer fix.

### 3.2 Docstring-as-contract

- **open-swe**: docstring tool = đặc tả đầy đủ: **When to use**, Args, Returns (liệt kê key), và mệnh lệnh hậu-xử-lý ("never dump raw markdown"). Đây là cách rẻ nhất để LLM dùng tool đúng.
- **Áp dụng**: rà `tools.py`, đảm bảo mỗi tool có block "When to use" + liệt kê đúng key trả về. Nhất là các tool dễ nhầm: `render_diagram` vs `inspect_diagram`, `search_icons` vs `resolve_icons`.

### 3.3 Suggestion capping & deterministic verdict — bạn ĐÃ làm rất chuẩn

`findings.py` của bạn: `MAX_FINDINGS=5`, `MAX_SUGGESTION_LINES=4`, `verdict_for()` machine-greppable `VERDICT: PASS|REVISE`, `prune()` rank theo severity/confidence. Đây là bản port **xuất sắc** của `reviewer_findings.py`. Không cần đổi. Điểm hay riêng của bạn: `in_blueprint` để tách finding ngoài-scope không block finalize — tốt hơn cả việc chỉ copy.

### 3.4 System prompt modular + AGENTS.md override

- **open-swe** `prompt.py`: prompt ghép từ 10+ section, inject động (repo, user, flag); **AGENTS.md là authority** — đọc ngay sau clone, override hành vi mặc định.
- **bạn**: `prompts.py` (969 dòng) đã có `build_system_prompt`/`build_pretty_system_prompt`/`build_*_prompt` cho từng subagent — đã modular tốt. Memory `/memories/AGENTS.md` của bạn nạp lúc startup = đúng vai trò "override authority".
- **Áp dụng (nhỏ)**: open-swe inject prompt section **có điều kiện** (vd `ALWAYS_CREATE_PR_SECTION` chỉ khi flag bật). Bạn có thể inject section theo `style`/độ phức tạp diagram để prompt gọn hơn cho ca đơn giản.

### 3.5 SSRF guard cho fetch (nếu agent fetch URL ngoài)

- **open-swe** `http_request.py`: validate IP, pin DNS chống rebinding, validate mọi redirect hop.
- **bạn**: `logo_fetch.py` fetch logo từ web. Nếu URL có thể do user/LLM cung cấp → cân nhắc validate host (chặn private/loopback IP). Mức ưu tiên thấp nếu chỉ fetch từ allowlist domain.

---

## Mảng 4 — Evals & Multi-graph + Isolation

### 4.1 Per-thread isolation — GAP NGHIÊM TRỌNG NHẤT

- **open-swe**: mỗi `thread_id` có **sandbox riêng** (`ensure_sandbox_for_thread`, cache theo thread, id lưu trong metadata). Hai run song song không đụng nhau.
- **bạn**: **một WORKSPACE toàn cục dùng chung** (`backends.py:WORKSPACE = AGENT_SPACE/workspace`). `server.py` ghi cứng `WORKSPACE/out.png`, `WORKSPACE/diagram.py`, `WORKSPACE/blueprint.json`... cho **mọi** thread. Hai user generate diagram đồng thời → **đè file của nhau**, ảnh trả về sai phiên.
- **Tác động**: hiện chỉ an toàn khi single-user / chạy tuần tự. Lên production multi-user là lỗi tức thì.
- **Áp dụng**: workspace theo thread — `WORKSPACE / thread_id /` thay vì `WORKSPACE /`. `make_local_backend()` nhận `thread_id` và root FilesystemBackend vào thư mục con. `server.py` đọc artifact (`out.png`...) từ `WORKSPACE/thread_id/`. `/memories/` vẫn dùng chung (đó là tri thức toàn cục, đúng). Đây là thay đổi có ảnh hưởng rộng (`backends.py`, `agent.py:build_agent`, các chỗ đọc `WORKSPACE/...` trong `server.py`) nên cần làm cẩn thận — nhưng là việc đáng ưu tiên số 1 nếu hướng tới multi-user.

### 4.2 Tách analyzer thành graph (nâng cấp refine_memory)

- **open-swe**: học là một **graph riêng** (`analyzer`) đăng ký trong `langgraph.json`, chạy độc lập, có tool `save_review_style_prompt`/`read_finding_outcomes`, dùng skill làm playbook.
- **bạn**: học là một **script** (`refine_memory.py`) — đơn giản và đang chạy được. Nâng cấp lên graph chỉ đáng làm nếu bạn muốn: (a) chạy qua LangGraph cron/scheduler thống nhất, (b) cho LLM tự đọc nhiều nguồn outcome (không chỉ reject note), (c) audit/trace qua LangSmith. Nếu chưa cần, giữ script.

### 4.3 Eval — bạn đã có nền tốt, mở rộng coverage

- **open-swe** `evals/reviewer/`: golden comments + LLM judge (`claude-opus`) chấm pairwise precision/recall/f1, judge **cùng model với baseline** để số liệu so sánh được.
- **bạn** `evals/diagram/`: đã có `judge.py` + `run_eval.py` + `target.py`. Đây là tài sản quý.
- **Áp dụng**: với diagram, cân nhắc judge **đa tiêu chí** (completeness vs blueprint, layout/readability, icon đúng) thay vì một điểm — khớp với `Category` trong `findings.py` của bạn. Có thể tái dùng chính `critic` subagent làm judge offline.

### 4.4 Model resolution & observability gating

- **open-swe**: precedence per-thread > profile > team (`server.py`), và **gate tool observability theo authorization** (chỉ user được phép mới nạp Datadog/LangSmith tool — chống prompt-injection exfil).
- **bạn**: `config.py:get_model("role", default)` per-role từ config.yaml — đủ cho single-tenant. Chỉ cần nâng nếu đa người dùng / đa team. Observability gating chỉ liên quan nếu bạn thêm tool đọc dữ liệu nội bộ.

---

## Mảng 5 — Persistence: lưu Conversation/Run chi tiết hơn vào Postgres

**Đang lưu** (`conversations.py`): bảng `conversations` (1 dòng / `thread_id`, **ghi đè mỗi run** qua `upsert_run`) gồm `messages_json`, `state_json` (kèm png), `outcomes_json = [{gate, decision, note, timestamp}]`; cộng bảng `langgraph_*` (checkpoint để resume).

**Thiếu — nên bổ sung để học + observability:**

1. **Lịch sử per-run (append-only).** `conversations` ghi đè → mỗi thread chỉ giữ run mới nhất; chi tiết run cũ mất (trừ checkpoint thô). → thêm bảng `runs` (1 dòng / `run_id`).
2. **Token/cost vào DB.** `UsageLoggingMiddleware` (agent.py:183) ghi `usage.json` vào **WORKSPACE dùng chung** → không query được + bị mọi thread append đè (cùng lỗi global-workspace). → ghi usage vào bảng `runs` theo `run_id`.
3. **Outcome quá mỏng cho learning.** `outcomes_json` chỉ có `note` text, không gắn với *cái gì bị reject* (blueprint/tech_stack/diagram). → lưu snapshot `blueprint.json`/`tech_stack.json` + đường dẫn diagram cùng outcome, để `refine_memory` học có ngữ cảnh (đúng tinh thần open-swe: outcome gắn finding cụ thể).
4. **Findings critic không lưu cấu trúc.** `DiagramFinding` (severity/category) chỉ thành text verdict rồi mất. → lưu `findings_json` để đo "lỗi layout hay tái diễn" và feed continual learning.
5. **Metadata run:** model, effort, style, duration, status (ok/failed/limit_reached), render_count, error.

**Schema đề xuất** (bảng `runs` append-only, bổ sung cho `conversations`):
```sql
CREATE TABLE runs (
  run_id   TEXT PRIMARY KEY,  thread_id TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  model TEXT, effort TEXT, style TEXT,
  status TEXT,                 -- ok | failed | limit_reached
  duration_ms INTEGER,
  input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER,
  render_count INTEGER,
  findings_json JSONB,         -- DiagramFinding[] từ critic
  artifacts_json JSONB,        -- đường dẫn out.png/diagram.py đã archive (xem 1.0 #2)
  error TEXT
);
-- gate outcome gắn artifact thay vì note rời (bảng gate_outcomes hoặc cột mở rộng):
-- {run_id, gate, decision, note, blueprint_snapshot, diagram_path, findings_ref, timestamp}
```
**Áp dụng**: viết bảng `runs` trong `conversations.py` (cùng pattern `_DDL` + `setup()` đã có); ghi 1 dòng sau `RUN_FINISHED` trong `server.py` (nơi đã có `run_id`, `thread_id`, đọc `tool_budget_summary.json`/`usage.json`). Liên kết `OUTPUTS_DIR` archive (1.0 #2) qua `artifacts_json`. Đây cũng là nền cho continual-learning giàu ngữ cảnh (1.1) và eval (4.3).

## Ưu tiên đề xuất (nếu sau này muốn implement)

| # | Hạng mục | Mảng | Ảnh hưởng | Công sức |
|---|---|---|---|---|
| 1 | Per-thread workspace isolation | 4.1 | Cao (chặn multi-user bug; cũng sửa va chạm usage.json/output) | Trung bình |
| 2 | Archive output mỗi run vào OUTPUTS_DIR + bảng `runs` append-only | 1.0/5 | Cao (giữ lịch sử run, cost, findings — nền cho học & observability) | TB |
| 3 | Tự động học sau run / cron đêm, học cả approve | 1.0/1.1/1.2 | Cao (memory mới thực sự "tự cập nhật") | Thấp–TB |
| 4 | ToolErrorMiddleware + defensive return shape | 2.1/3.1 | Cao (độ bền render loop) | Thấp–TB |
| 5 | Outcome gắn ngữ cảnh (blueprint/diagram/findings) | 1.1/5 | TB (continual learning có ngữ cảnh, không chỉ note rời) | TB |
| 6 | Memory → Postgres StoreBackend (thay FilesystemBackend) | 1.0 | TB (bền khi deploy/nhiều replica) | TB |
| 7 | Sanitize inputs + empty-msg guard middleware | 2.2/2.3 | TB (ổn định với mimo) | Thấp |
| 8 | Docstring-as-contract rà soát tools.py | 3.2 | TB (LLM dùng tool đúng) | Thấp |
| 9 | Eval đa tiêu chí (tái dùng critic làm judge) | 4.3 | TB (đo tiến bộ) | TB |
| 10 | Analyzer-graph hoá refine_memory | 4.2 | Thấp (chỉ khi cần trace/cron thống nhất) | Cao |

**Tinh thần chung**: bạn đã giỏi phần "hình dạng agent". Việc học từ open-swe bây giờ chủ yếu là **độ bền production** (#1, #2, #4) và **khép kín vòng học** (#3) — không phải làm lại từ đầu.

---

## Verification (cho từng hạng mục nếu triển khai)

- **Isolation (#1)**: chạy 2 request `/agui` song song với 2 `threadId` khác nhau, xác nhận mỗi phiên trả đúng `out.png` của mình; kiểm `agent_space/workspace/<thread_id>/` tách biệt.
- **ToolError (#2)**: cố tình truyền code `diagrams` lỗi import → xác nhận agent nhận ToolMessage lỗi cấu trúc và tự sửa ở vòng sau (không crash run). Chạy `backend/tests/` (đã có `test_agent_run_limits.py`, `test_mimo_coercion.py`).
- **Continual (#3)**: tạo vài outcome `approve`/`reject` trong Postgres → `uv run python scripts/refine_memory.py --dry-run` → xác nhận mục "Style Preferences" được củng cố từ approve, không chỉ "Do Not Do".
- **Middleware (#4)**: unit test theo kiểu `open-swe/tests/middleware/` (mock handler, assert input đã sanitize / empty-msg được inject).
- **Eval (#6)**: `uv run python -m evals.diagram.run_eval` trên tập mẫu, so điểm đa tiêu chí trước/sau thay đổi.

> Lưu ý: đây là tài liệu phân tích/học tập (theo lựa chọn "Báo cáo phân tích + gap"). Không có thay đổi code nào được đề xuất thực thi ngay. Nếu bạn muốn, tôi có thể biến bất kỳ hạng mục nào ở bảng ưu tiên thành một plan triển khai chi tiết và thực hiện.
