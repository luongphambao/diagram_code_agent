# Review kiến trúc multi-agent và chất lượng code do Opus 4.8 tạo ra

Ngày review: 2026-07-30  
Phạm vi: `backend/`, `runtime/`, `frontend/` ở mức ranh giới service, persistence, HITL, memory, subagent, tool/middleware, security và artifact runtime.  
Artifact được kiểm: `artifacts/` và `backend/agent_space/` (diagram, Draw.io, quality report, WBS/XLSX, PDF, PPTX và gate state).  
Không chạy `backend/evals/e2e/` vì có side effect gửi email và tạo lịch thật.

## 1. Kết luận ngắn

Đây là một codebase có mức đầu tư engineering cao, vượt xa một prototype agent thông thường. Opus 4.8 đã tạo được nhiều cấu trúc tốt: phân tách domain, per-thread workspace, declarative subagent spec, middleware theo phase, call budget, deterministic validators, sandbox cho code sinh ra, HITL và bộ artifact rất rộng.

Điểm yếu chính không nằm ở việc thiếu tính năng, mà ở **system-wide invariants**: một số boundary quan trọng vẫn là advisory, state workflow suy ra từ file, revision artifact không có dependency invalidation, và validator đôi khi chỉ kiểm consistency ở một đoạn cục bộ thay vì từ artifact đã duyệt tới deliverable cuối. Kết quả runtime xác nhận vấn đề này: có diagram fail quality nhưng vẫn sinh PDF/PPT/WBS; một WBS có tổng effort đúng nhưng lịch và critical path không có ý nghĩa; một revision blueprint mới hơn render spec nhưng downstream không bị invalidated.

Đánh giá tổng thể chất lượng code do Opus 4.8 tạo ra: **6.8/10 - nền tảng tốt, nhiều chi tiết mạnh, nhưng chưa đủ chắc cho production multi-user nếu chưa xử lý các finding P0/P1**.

> Lưu ý attribution: Opus 4.8 là coding model đã tạo codebase. Runtime hiện cấu hình `moonshotai/kimi-k3-free` cho main và các role (`backend/config.yaml:10`). Vì vậy chất lượng nội dung/visual của từng artifact chịu ảnh hưởng của Kimi và prompt; còn các lỗi permission, state, invalidation, gating, concurrency và validator boundary là chất lượng của implementation/architecture do coding model tạo ra.

## 2. Scorecard

| Hạng mục | Điểm | Nhận xét |
|---|---:|---|
| Ý đồ kiến trúc | 8.5/10 | Có staged workflow, specialist agents, deterministic tail và HITL rõ ràng. |
| Modularity và maintainability | 8.0/10 | Domain/module khá sạch; `SubagentSpec` và middleware composition tốt. |
| Testability | 7.5/10 | Baseline cuối đã chạy: 93 architecture-focused backend tests và 34 runtime tests pass; vẫn thiếu invariant/integration tests quan trọng. |
| Security boundary | 5.0/10 | Có auth/ownership và sandbox, nhưng RBAC approval, artifact delivery và global memory chưa hard-enforced. |
| State consistency | 5.0/10 | Checkpoint/store tốt, nhưng phase/revision/gate state còn dựa vào file và dễ stale/race. |
| Reliability/reproducibility | 6.0/10 | Có budgets, fallback, health checks; Docker install không khóa bằng `uv.lock`, nhiều critical check bị best-effort. |
| Artifact correctness | 6.0/10 | Sinh được bộ deliverable rộng và có validator; audit thực tế cho thấy semantic/visual/WBS inconsistencies còn lọt qua. |
| Documentation accuracy | 5.5/10 | Docs hữu ích nhưng đã lệch số tool, gate và subagent; prompt cũng lệch workflow thật. |

## 3. Kiến trúc as-built

### 3.1 Ranh giới service

1. React/CopilotKit frontend gửi AG-UI request qua Node runtime.
2. Node runtime dùng `PassthroughRunner`, proxy stream sang FastAPI backend và tách binary artifact ra khỏi agent state.
3. FastAPI xác thực identity, kiểm ownership của `thread_id`, bind per-thread workspace, rồi stream `AGENT.astream(...)`.
4. Main Deep Agent dùng LangGraph/deepagents, PostgreSQL checkpointer/store, 47 authored tools cộng built-in filesystem/task tools.
5. Main agent điều phối 6 subagent: `icon_resolver`, `drawer`, `critic`, `wbs_planner`, `ppt_generator`, `brd_writer` (`backend/src/agent/subagents/__init__.py:36`).
6. Generated code chạy trong Modal Sandbox; artifact nghiệp vụ nằm trong per-thread workspace; memory dài hạn nằm ở `/global-memories/AGENTS.md`.
7. Qdrant và Composio là integration tùy chọn cho past-project RAG, Gmail, Calendar và Meet.

### 3.2 Pipeline artifact

`requirements.md` -> `architecture_analysis.json` -> `diagram_brief.json` -> tech-stack gate -> `tech_stack.json` -> blueprint gate -> `blueprint.json` + `render_spec.json` -> icon/style/layout -> `out.drawio` + `out.png` -> engineer/critic -> final review -> WBS/PDF/PPTX/BRD gates.

Thiết kế có chủ đích tách semantic artifact khỏi presentation artifact. Tuy nhiên repo chưa có manifest revision/dependency DAG để đảm bảo khi upstream đổi thì mọi downstream liên quan bị đánh dấu stale và buộc regenerate.

### 3.3 Tool và HITL thực tế

- `MAIN_TOOLS` hiện có 47 tool (`backend/src/tools/__init__.py:272`), không phải 41 như `docs/agent-design.md:38`.
- `GATE_TOOL_NAMES` hiện có 16 gate (`backend/src/tools/__init__.py:364`), không phải 13 như `docs/agent-design.md:59`.
- Có 6 subagent, không phải 5 như `docs/architecture.md:41` và `docs/agent-design.md:10`.
- `propose_meeting_slots` dùng internal interrupt và không nằm trong `GATE_TOOL_NAMES` (`backend/src/tools/__init__.py:303`).
- Phase middleware giảm tool schema theo artifact hiện có, nhưng phase không phải một workflow state được persist tường minh (`backend/src/agent/middleware/phase_filter.py:175`).

## 4. Findings ưu tiên

### CRITICAL-1 - RBAC của HITL chỉ ghi log, không chặn approval

**Bằng chứng**

- `can_approve()` định nghĩa policy theo role (`backend/src/tools/__init__.py:440`).
- Khi role không hợp lệ, backend chỉ `logger.warning(...)` rồi vẫn tạo record và resume (`backend/src/routers/chat.py:90`, `backend/src/routers/chat.py:107`).
- Empty/unknown role được cho phép mặc định (`backend/src/tools/__init__.py:461`).
- `Command(resume=...)` vẫn chạy ở `backend/src/routers/chat.py:314`.

**Tác động**

Người dùng có ownership của thread nhưng sai role vẫn có thể duyệt technical design, client delivery, email hoặc calendar gate. Audit log có vẻ đầy đủ nhưng không phải enforcement, dễ tạo cảm giác an toàn giả.

**Đề xuất**

- Chặn trước `_persist_decision_record` và trước `Command(resume)`; trả `403` hoặc một AG-UI error có mã ổn định.
- Không cho empty role qua đối với gate restricted; map identity -> role ở server side.
- Persist cả denied attempt, nhưng denied attempt không được trở thành approval record.
- Test matrix cho mọi gate x role, gồm missing role, unknown role và role downgrade.

### CRITICAL-2 - Global memory có thể bị mọi subagent ghi, dù prompt nói read-only

**Bằng chứng**

- Mọi subagent dùng cùng `backend` và đều được mount `memory=[GLOBAL_MEMORY_PATH, MEMORY_PATH]` (`backend/src/agent/builder.py:133`).
- `/global-memories/` dùng `FilesystemBackend` không có write permission restriction (`backend/src/backends.py:292`).
- Drawer/critic chỉ bị cấm bằng prompt (`backend/src/prompts/drawer_agent.py:199`, `backend/src/prompts/critic_agent.py:26`).
- Repo đã tự chứng minh prompt-only guard không đủ qua fix riêng cho `icon_plan.json` (`backend/src/agent/subagents/icon_resolver.py:13`), nhưng cùng nguyên tắc chưa được áp dụng cho global memory.

**Tác động**

Một worker bị prompt injection, hallucination hoặc tool defection có thể poison memory dùng chung cho mọi thread. Trong môi trường nhiều user, đây là đường cross-thread/cross-tenant contamination.

**Đề xuất**

- Deny `write` cho `/global-memories/*` ở tất cả subagent.
- Main agent cũng không nên edit file trực tiếp; cung cấp tool `append_global_memory_lesson(...)` có schema, validation, author/thread/source, dedup và audit.
- Tách memory theo tenant/team; chỉ promote lesson lên global sau review hoặc confidence threshold.

### HIGH-1 - Không có same-thread run lease; hai run có thể ghi đè cùng checkpoint/workspace

**Bằng chứng**

- Runtime lưu một `Map<threadId, agent>`, nhưng `run()` luôn `set(...)` và ghi đè entry cũ (`runtime/src/passthrough-runner.ts:28`, `runtime/src/passthrough-runner.ts:32`).
- `isRunning()` chỉ quan sát Map; nó không serialize hoặc reject run mới (`runtime/src/passthrough-runner.ts:140`).
- Backend bind cùng `thread_id` vào cùng workspace/checkpointer và không có per-thread lock tại `/agui` (`backend/src/routers/chat.py:203`).

**Tác động**

Double submit, reconnect hoặc hai browser tab có thể race trên `pending_gate.json`, stage JSON, `out.*`, decision record và LangGraph checkpoint. Run cũ kết thúc còn có thể phát event xen vào run mới.

**Đề xuất**

- Distributed lease `(tenant_id, thread_id)` với owner `run_id`, TTL và heartbeat; dùng PostgreSQL advisory lock hoặc Redis SET NX.
- Mặc định trả `409 THREAD_BUSY`; nếu cho queue thì queue phải idempotent theo `run_id`.
- Khi resume gate, kiểm gate id/revision, không chỉ thread checkpoint hiện tại.

### HIGH-2 - Artifact download endpoint không kiểm auth hoặc ownership

**Bằng chứng**

- Runtime phục vụ `GET /api/artifacts/:key` trực tiếp từ in-memory store (`runtime/src/index.ts:62`, `runtime/src/index.ts:73`).
- Không có identity, thread ownership hoặc signed expiry validation trước `artifactStore.get(key)`.

**Tác động**

Content hash khó đoán, nhưng URL bị lộ qua browser history, proxy log, screenshot, referrer hoặc support ticket thì artifact có thể tải trong TTL. `Cache-Control: private` không thay thế authorization.

**Đề xuất**

- Artifact key phải gắn với `thread_id`, owner/tenant và expiry.
- Endpoint dùng cùng auth middleware, gọi ownership check; hoặc phát signed URL ngắn hạn bằng HMAC/object storage.
- Không dùng raw content hash như bearer capability duy nhất.

### HIGH-3 - Revision drift: upstream artifact đổi nhưng downstream không bị invalidated

**Bằng chứng artifact**

Trong `artifacts/thread-ms33ubw0-6frps`:

- `blueprint.json`: 29 nodes / 23 edges, mtime 18:05:56.
- `render_spec.json`: 27 nodes / 20 edges, mtime 18:04:19.
- Blueprint mới hơn render spec nhưng không trigger regenerate.
- Chênh lệch: 2 nodes và 3 edges không có trong render spec.
- `out.native_stats.json` vẫn báo node/edge recall 1.0 vì semantic validator so output với render spec hiện hành, không so với revision blueprint mới nhất.
- Critic sau đó mới phát hiện missing nodes/edges; PDF và PPTX vẫn được tạo.

**Tác động**

Từng stage có thể locally consistent nhưng deliverable cuối không còn trace tới artifact đã duyệt/mới nhất. Đây là lỗi contract xuyên stage, nguy hiểm hơn một lỗi render đơn lẻ.

**Đề xuất**

- Mỗi artifact có `artifact_id`, `revision`, `content_hash`, `created_from[]`, `approved_revision`.
- Khi upstream hash đổi, đánh dấu tất cả downstream phụ thuộc là `stale`; tool export phải reject stale input.
- Semantic preservation phải kiểm từ approved blueprint revision tới render spec và từ render spec tới Draw.io.
- Critic/engineer report phải ghi rõ source revision đã kiểm.

### HIGH-4 - Hard quality finding vẫn có thể đi tiếp sang client deliverable

**Bằng chứng code**

- `finalize_diagram()` chỉ bắt buộc `out.png` tồn tại (`backend/src/tools/rendering_tools.py:2508`).
- Scorecard và residual critique chỉ được đính kèm advisory; exception bị nuốt (`backend/src/tools/rendering_tools.py:2511`, `backend/src/tools/rendering_tools.py:2518`).

**Bằng chứng artifact**

- 27 run có `out.png`; 26 có native stats; 14 có engineer report.
- Trong 14 engineer report: 8 pass, 6 fail.
- 3 run có semantic hard findings; 7 run có critic high/critical finding.
- 3 run vẫn tạo downstream PDF/PPTX/XLSX dù engineer fail hoặc semantic hard finding.
- Một sample engineer score 87.3 nhưng `final_pass=false`, critic còn high completeness finding, deck audit còn high tiny-font issue; vẫn có PDF và PPTX.

**Tác động**

HITL đang được dùng như cách bypass validator ngầm định. Con người có thể chủ động chấp nhận risk, nhưng hiện system không buộc decision đó phải explicit, có reason và gắn với exact revision.

**Đề xuất**

- Hard blocker: semantic completeness, invalid/stale source, missing required artifact, corrupted file, client-visible tiny text.
- Cho phép bypass chỉ qua action `accept_risk` với reason bắt buộc, role phù hợp và exact artifact revision.
- `approve` thông thường không được bypass hard finding.

### HIGH-5 - WBS có tổng effort đúng nhưng scheduling sai nghĩa

**Bằng chứng code**

- `add_wbs_items` cho phép `predecessors`, nhưng workflow/skill không bắt buộc planner điền dependency (`backend/src/domain/wbs/wbs_tools.py:382`, `backend/skills/wbs-planning/SKILL.md:34`).
- `compute_wbs_rollup` chạy CPM nếu có dependency **hoặc chỉ cần có PERT estimate** (`backend/src/domain/wbs/wbs_tools.py:751`).
- Với toàn bộ task isolated, CPM trả duration bằng task dài nhất và critical path rỗng (`backend/src/domain/wbs/wbs_effort.py:310`).
- `plan_timeline_and_sprints` thấy `early_start=0` và gán tất cả vào sprint 1 (`backend/src/domain/wbs/wbs_tools.py:829`, `backend/src/domain/wbs/wbs_effort.py:402`).

**Bằng chứng artifact**

`backend/agent_space/workspaces/e2e-fullflow/wbs.json` có 43 items, 487 MD, timeline 7 tháng/14 sprint nhưng:

- 0 item có predecessor/dependency.
- 43/43 item có `float_md=null`.
- `critical_path.ref_codes` rỗng, `project_duration_md=14`.
- Tất cả item có `assigned_sprint=1`.

Hai WBS runtime khác được kiểm cũng có cùng pattern: max assigned sprint = 1 và không có dependency.

**Tác động**

Effort/cost summary có thể dùng được, nhưng Delivery Plan, sprint allocation, resource leveling và critical path tạo cảm giác chính xác giả. Đây là lỗi correctness của artifact khách hàng.

**Đề xuất**

- Không chạy CPM nếu DAG không có ít nhất một edge; khi không có DAG, để schedule state là `not_planned` thay vì tạo số giả.
- Bắt buộc planner cung cấp predecessor cho task delivery, hoặc có deterministic default phase/module dependency graph.
- Validate: timeline > 1 sprint nhưng 90% task ở sprint 1 là blocking anomaly.
- Integration test từ `add_wbs_items` -> `finalize_wbs` -> XLSX cho case PERT-without-dependencies.

### MEDIUM-1 - `pending_gate.json` bị stale sau resume

**Bằng chứng**

- Gate payload được ghi vào `pending_gate.json` khi card được tạo (`backend/src/session/gate_decisions.py:37`).
- Resume path không clear file trước/sau `Command(resume)` (`backend/src/routers/chat.py:265`).
- `_stage_artifacts()` luôn trả file này cho UI nếu tồn tại (`backend/src/session/artifacts.py:56`, `backend/src/session/artifacts.py:74`).
- File chỉ nằm trong danh sách cleanup của fresh-run reset (`backend/src/tools/stage_markers.py:241`).
- 9/26 artifact thread có `pending_gate.json`; sample đã hoàn thành PDF/PPT vẫn còn gate `propose_blueprint`.

**Đề xuất**

Gate state phải có `gate_id`, `status`, `created_at`, `resolved_at`, `revision`; clear hoặc chuyển trạng thái atomically khi resume được chấp nhận. UI chỉ render `status=pending` khớp checkpoint interrupt hiện tại.

### MEDIUM-2 - Phase machine dựa vào file existence, không phải state machine tường minh

**Bằng chứng**

- `_detect_phase()` chọn phase cao nhất dựa trên file (`backend/src/agent/middleware/phase_filter.py:175`).
- Code đã phải thêm backfill tool vì file thiếu ở phase cao làm workflow mắc kẹt (`backend/src/agent/middleware/phase_filter.py:199`).

**Tác động**

File stale/corrupt/partial có thể đẩy phase tiến sai; file bị mất có thể kéo phase lùi; không biểu diễn được revision, retry, rejected, waived hoặc parallel deliverable branch.

**Đề xuất**

LangGraph top-level StateGraph với typed state: `stage`, `status`, `active_gate`, `approved_revisions`, `artifact_manifest`, `quality_state`. File là materialized artifact, không phải workflow authority.

### MEDIUM-3 - Build container không reproducible theo lockfile

**Bằng chứng**

- Local/CI contract dùng `uv sync --frozen`, nhưng Docker dùng `pip install -e ./backend` (`backend/Dockerfile:55`).
- Runtime dependencies dùng lower bounds `>=` (`backend/pyproject.toml:6`).
- Anthropic adapter là optional extra (`backend/pyproject.toml:40`), nên đổi runtime config sang Claude trong fresh image sẽ thiếu dependency nếu image không cài extra.

**Tác động**

Hai build cùng commit ở hai thời điểm có thể resolve dependency khác nhau. Test với lockfile không bảo đảm image production dùng cùng graph/runtime versions.

**Đề xuất**

- Docker cài từ `uv.lock` bằng `uv sync --frozen --no-dev` hoặc export lock thành requirements có hash.
- Chọn rõ image variant/provider extras; smoke test import provider theo `config.yaml` trong build/health check.

### MEDIUM-4 - Prompt, docs và implementation drift

**Bằng chứng**

- Prompt bắt mọi response có ít nhất một tool call (`backend/src/prompts/_blocks.py:260`) nhưng staged intake cho phép hỏi clarification rồi stop (`backend/src/prompts/_blocks.py:344`).
- Prompt liệt kê chỉ 6 approval pause hợp lệ (`backend/src/prompts/_blocks.py:275`) trong khi implementation có 16 gate.
- Docs ghi 5 subagent, 41 tools và 13 gates; implementation là 6/47/16.

**Tác động**

Model nhận instruction mâu thuẫn; maintainer review nhầm topology; gate mới có thể không được prompt/middleware/UI xử lý nhất quán.

**Đề xuất**

- Generate docs/prompt gate table từ một registry typed duy nhất.
- Contract test assert docs snapshot, UI card mapping, role policy, `interrupt_on`, decision menu và prompt registry cùng tập gate.
- Clarification nên là node/workflow outcome rõ ràng, không phải ngoại lệ prose.

### MEDIUM-5 - Nhiều critical check dùng `except Exception: pass`

**Bằng chứng**

- Semantic stats render là best-effort (`backend/src/tools/rendering_tools.py:1056`).
- Final scorecard/snapshot/critique đều có đường nuốt exception (`backend/src/tools/rendering_tools.py:2511`, `backend/src/tools/rendering_tools.py:2533`).

**Tác động**

Failure của chính validator có thể bị trình bày như không có finding. Với client deliverable, `validator unavailable` phải khác `validator passed`.

**Đề xuất**

- Quality state ba giá trị: `pass | fail | unavailable`.
- `unavailable` block client export hoặc yêu cầu explicit risk acceptance.
- Log structured error + metric + trace id; không dùng empty dict để biểu diễn thành công.

## 5. Điểm mạnh đáng giữ

### 5.1 Per-thread isolation và ownership đã được xử lý có chiều sâu

- `thread_id` được sanitize và map sang workspace riêng (`backend/src/backends.py:72`).
- Filesystem backend resolve `cwd` theo request-scoped contextvar (`backend/src/backends.py:141`).
- Absolute-looking path được re-root bằng `virtual_mode=True`, giảm path traversal/cross-thread leak (`backend/src/backends.py:240`).
- Backend kiểm thread owner trước khi chạy agent (`backend/src/routers/chat.py:212`).

Đây là một trong những phần tốt nhất của codebase: comment giải thích rõ failure mode lịch sử và testability được tính đến.

### 5.2 Subagent registry và compile loop tốt

- `SubagentSpec` gom role, tools, model, skill, run limit và permission (`backend/src/agent/subagents/spec.py:16`).
- `build_agent()` compile đồng nhất mọi role (`backend/src/agent/builder.py:122`).
- General-purpose nested subagent bị vô hiệu hóa sau khi trace thực tế cho thấy token blowout (`backend/src/agent/builder.py:105`).

Đây là pattern maintainable hơn việc copy/paste `create_deep_agent()` cho từng role.

### 5.3 Có deterministic layers thay vì giao mọi thứ cho LLM

- Effort ratio, PERT/CPM, diagram semantic check, Draw.io validator, deck audit và cross-artifact validator đều có code deterministic.
- WBS tổng effort trong sample khớp giữa item sum, role sum và declared total.
- Excel sample có 5 sheet, giữ formula VLOOKUP/SUM và rate-card formula; không chỉ xuất bảng phẳng.

Ý đồ này đúng: LLM nên tạo plan/semantics, còn rollup/export/validation nên deterministic. Vấn đề hiện tại là invariant giữa các deterministic layer chưa được nối kín.

### 5.4 Permission layer đã được dùng đúng ở một số chỗ

- `icon_resolver` bị deny ghi trực tiếp `icon_plan.json` (`backend/src/agent/subagents/icon_resolver.py:22`).
- `brd_writer` bị deny ghi `out.brd.docx` và revision trực tiếp (`backend/src/agent/subagents/brd_writer.py:18`).

Đây là bằng chứng team hiểu đúng nguyên tắc “không dùng prompt làm security boundary”; cần mở rộng nó nhất quán cho memory và artifact ownership.

### 5.5 Budget, context trimming và observability được quan tâm

- Phase filter giảm tool schema/prompt theo stage.
- Có model-call limit theo role, tool budget, image relay/sanitization và subagent streaming.
- Runtime tách base64 artifact ra khỏi agent state để tránh browser/runtime giữ nhiều MB dữ liệu (`runtime/src/passthrough-runner.ts:34`).

Những chi tiết này cho thấy Opus làm tốt local optimization và xử lý nhiều failure mode thực tế, không chỉ dựng skeleton.

### 5.6 Artifact breadth tốt

- Full-flow sample tạo được Draw.io, PNG, PDF 20 trang, PPTX, WBS JSON và Excel 5 sheet.
- WBS full-flow có 43 items, tổng 487 MD và 7 tháng; công thức effort/cost nội bộ khớp.
- Artifact có sidecar audit (`engineer_report`, native stats, critique, deck audit), tạo nền tốt cho release gate sau này.

## 6. Audit artifact thực tế

### 6.1 Thống kê tập mẫu

| Chỉ số | Kết quả |
|---|---:|
| Run có `out.png` | 27 |
| Run có native stats | 26 |
| Run có engineer report | 14 |
| Engineer pass/fail | 8 / 6 |
| Run có semantic hard finding | 3 |
| Run có critic high/critical | 7 |
| Run vẫn sinh downstream khi fail/hard | 3 |

### 6.2 Diagram

- Sample score 79, fail: 29 nodes nhưng 11 orphan, edge/component ratio 0.69; canvas rất dài, nhiều whitespace, zone rời và connector quá dài.
- Sample score 87.3, fail: blueprint/render spec revision drift, 7 orphan, ratio 0.74, nhiều crossing; critic phát hiện thiếu 2 nodes và 3 edges.
- Sample score 94.1, pass: semantic đủ hơn nhưng vẫn còn 4 medium visual findings; diagram sparse, label/edge có chỗ chồng và content fill thấp.
- Full-flow sample score 87.9 pass, nhưng kiểm tra trực quan vẫn thấy text nhỏ, whitespace và crossing làm giảm khả năng trình bày với khách.

Kết luận: score hiện thiên về structural metrics và chưa phản ánh đủ presentation quality ở kích thước slide/PDF thật.

### 6.3 PPTX/PDF

- Sample 22 slides có `deck_visual_audit.passed=false`; một high tiny-font 6.5pt.
- Quan sát trực quan: slide technical stack gần trống, architecture bị scale quá nhỏ, một số slide effort/pricing mang tính generic hơn là trace trực tiếp từ approved solution.
- PDF được tạo ổn định và có cấu trúc nhiều trang, nhưng diagram nhỏ/whitespace từ source được mang nguyên sang report.

Đề xuất thêm audit ở **final consumption size**: render mỗi slide/PDF page thành ảnh ở 100%, OCR/font threshold, content-fill ratio, minimum architecture image height và evidence coverage per slide.

### 6.4 WBS/XLSX

Điểm tốt:

- Tổng item, tổng role và declared total khớp.
- Excel giữ template 5 sheet và formula, phù hợp deliverable BnK hơn CSV đơn giản.

Điểm yếu:

- Dependency graph gần như trống trong các WBS lớn đã kiểm.
- Timeline/critical path/sprint assignment mâu thuẫn; mọi task vào sprint 1.
- Team composition có role null khi không được model hóa, nhưng UI/report chưa phân biệt `not_required` với `unknown/not_planned`.

## 7. Đánh giá riêng về chất lượng coding của Opus 4.8

### Opus làm tốt

- Viết code có nhiều context về failure mode thực tế; comment thường giải thích “vì sao”, không chỉ “làm gì”.
- Tạo abstraction hợp lý cho subagent, backend routing, middleware và deterministic tool chain.
- Có xu hướng thêm test guard cho regression lịch sử và xử lý compatibility khá kỹ.
- Nhận ra token/context blowout và tối ưu schema, prompt, image state, nested delegation.
- Tạo được hệ thống end-to-end nhiều artifact, không dừng ở demo chat/tool calling.

### Opus còn yếu

- Tối ưu cục bộ nhiều nhưng thiếu một bộ invariant toàn cục: ownership, role, revision, gate, quality và concurrency chưa cùng chung một transaction model.
- Dễ tạo “advisory safety”: warning, scorecard, validator và prompt rule tồn tại nhưng không phải enforcement.
- Docs/comment rất nhiều nhưng registry không single-source-of-truth, nên drift nhanh.
- Có xu hướng best-effort/exception swallowing để giữ flow chạy; phù hợp UX prototype nhưng nguy hiểm cho client deliverable.
- Test tập trung vào function behavior và historical regressions, thiếu invariant test xuyên service/artifact revision.
- Thêm feature nhanh hơn việc làm sạch state model; file existence trở thành implicit workflow database.

Nhận định cân bằng: Opus 4.8 thể hiện năng lực coding tốt ở mức module và debugging thực tế, nhưng cần human architect đặt ra invariants/acceptance criteria chặt hơn. Nếu prompt chỉ yêu cầu “build feature end-to-end”, model có xu hướng ưu tiên flow không bị block; nếu yêu cầu “security/revision/quality must be fail-closed with property tests”, chất lượng production sẽ tăng đáng kể.

## 8. Target architecture đề xuất

### 8.1 Hybrid LangGraph + Deep Agents

Dùng LangGraph StateGraph cho top-level workflow deterministic:

`Intake -> Analyze -> TechStackGate -> BlueprintGate -> Render -> QualityGate -> DiagramGate -> {WBS, PDF, PPT, BRD} -> DeliveryGate`

Deep Agents chỉ dùng bên trong các node có task mở:

- Architect/main: synthesize analysis và options.
- Drawer: layout/render repair trong budget.
- Critic: visual/semantic review read-only.
- WBS planner: tạo work breakdown/dependency proposal.
- Deck/BRD writer: content planning trong contract rõ ràng.

Top-level graph sở hữu transition, retry, interrupt, revision, policy và release eligibility; subagent không tự quyết stage tiếp theo.

### 8.2 Artifact manifest

Mỗi artifact ghi:

```json
{
  "artifact_id": "blueprint",
  "revision": 4,
  "content_hash": "...",
  "status": "approved",
  "created_by_run": "run-...",
  "created_from": ["tech_stack@2", "analysis@1"],
  "quality": {"status": "pass", "report": "..."},
  "approved_by": {"user": "...", "role": "architect", "decision_id": "..."}
}
```

Artifact export chỉ đọc exact revisions từ manifest. Upstream thay đổi sẽ invalidate transitive downstream bằng dependency DAG.

### 8.3 Policy enforcement

- `AuthorizationPolicy`: user/tenant/thread/role/gate/action.
- `ArtifactPolicy`: owner, sensitivity, expiry, signed download.
- `FilesystemPolicy`: allowlist theo subagent; global memory read-only mặc định.
- `ReleasePolicy`: pass/fail/unavailable; risk acceptance là action riêng, không đồng nghĩa approve.
- `ConcurrencyPolicy`: one active lease per thread, idempotent run/gate resume.

### 8.4 Tool surface

Thay vì main agent thấy 47 authored tools theo registry rộng, cung cấp stage facades:

- `analyze_solution`
- `propose_tech_stack`
- `propose_blueprint`
- `build_diagram`
- `review_diagram`
- `build_wbs`
- `build_report`
- `build_deck`
- `build_brd`
- `deliver_artifacts`

Facade gọi deterministic service/tool nội bộ. Main model chọn business action, không phải nhớ nhiều implementation-level tool.

## 9. Roadmap cải thiện

### P0 - Security và data integrity

1. Hard RBAC trước gate resume.
2. Same-thread distributed lease + idempotency.
3. Auth/ownership hoặc signed URL cho artifact GET.
4. Deny global-memory write cho subagent; memory-write tool có audit.
5. Clear/resolve pending gate atomically.
6. Docker install từ lockfile.

### P1 - Workflow và artifact correctness

1. Top-level LangGraph state machine typed.
2. Artifact manifest + revision hash + dependency invalidation.
3. End-to-end semantic check từ approved blueprint tới final Draw.io/PDF/PPT.
4. Release gate fail-closed; `accept_risk` explicit.
5. Sửa WBS scheduling contract và anomaly validator.
6. Registry duy nhất cho tool/gate/role/UI/docs/prompt.

### P2 - Scale và quality

1. Durable object storage, signed URLs và lifecycle policy.
2. Redis/Postgres-backed runtime state thay in-memory artifact/run map.
3. Queue/worker cho render/deck/report jobs; lease/heartbeat/retry có idempotency.
4. Tenant-aware global memory và promotion workflow.
5. Visual eval ở slide/PDF consumption size; benchmark artifact theo domain.

## 10. Test/eval nên bổ sung

- Property test: subagent bất kỳ không thể write `/global-memories/*`.
- Contract test: disallowed role không thể resume checkpoint.
- Concurrency test: hai `run_id` cùng `thread_id`, chỉ một run được mutate state.
- Revision test: sửa blueprint làm render spec/drawio/pdf/ppt stale; export bị block.
- Gate test: stale `gate_id` hoặc double resume bị reject idempotently.
- Validator test: validator exception -> `unavailable`, không thành pass.
- WBS integration test: PERT không dependency không được tạo fake CPM/sprint plan.
- Artifact security test: owner A không tải được artifact của owner B dù biết key.
- Golden eval: semantic recall tính against approved blueprint revision.
- Visual eval: font, clipping, whitespace, content fill, diagram legibility trong PPT/PDF.

## 11. Baseline verification

- Architecture-focused backend tests: **93 passed**.
- Runtime tests: **34 passed**.
- Không chạy `backend/evals/e2e/` theo rule an toàn của repo.
- Các finding trên chủ yếu là missing invariant/integration coverage; việc unit tests xanh không phủ định chúng.

## 12. Tài liệu sơ đồ

File Draw.io đi kèm có 7 page:

1. System Context
2. Multi-Agent Topology
3. Request & HITL Sequence
4. State & Memory
5. Security & Failure Modes
6. Model & Token Strategy
7. Target Architecture
