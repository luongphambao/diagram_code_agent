# Agent Design

Hợp đồng thiết kế của Deep Agent: tool nào dùng khi nào, subagent làm gì, gate hoạt động ra sao, memory được ghi gì, và giới hạn ở đâu.
Đọc cùng `architecture.md` (§2, §5) và `gotchas.md` (mục "Agent / token").

---

## 1. Hình dạng agent

`agent/builder.py::build_agent()` gọi `create_deep_agent(...)` với: model theo role, `MAIN_TOOLS`, system prompt, `CompositeBackend`, `memory=[/global-memories/AGENTS.md, /memories/AGENTS.md]`, skills từ `backend/skills/`, 6 subagent đã compile, chuỗi middleware, checkpointer + store, `interrupt_on` (gate), `context_schema=SessionContext`.

`RECURSION_LIMIT = 450` (`agent/constants.py`) — dùng **chung** cho main và mọi subagent được `task` gọi xuống. Đó là lý do nó phải cao; cái chặn thật sự là `ModelCallLimitMiddleware` theo từng agent.

---

## 2. Subagent

| Tên | Việc | Tool | Trần call |
|---|---|---|---|
| `icon_resolver` | Đọc `render_spec.json`, resolve icon path + node class theo lô → ghi `icon_plan.json` | 7 | `ICON_CALL_LIMIT`=40 |
| `drawer` | Vòng render–refine (≤3) rồi export drawio; trả về **text**, không trả ảnh | 8 | `DRAWER_CALL_LIMIT`=40 |
| `critic` | Review chỉ-đọc `out.png` đối chiếu blueprint → `VERDICT: PASS/REVISE` | 2 | `CRITIC_CALL_LIMIT`=40 |
| `wbs_planner` | Phân rã WBS theo format BnK + ước lượng → `wbs.json` / `wbs_skeleton.json` (gate ở lại main) | 5 + `run_python` | `WBS_CALL_LIMIT`=60 |
| `ppt_generator` | Đọc artifact đã duyệt → `out.pptx` từ template BnK | 3 | `PPT_CALL_LIMIT`=60 |
| `brd_writer` | Soạn outline + nội dung từng section BRD → `out.brd.docx` (gate ở lại main) | 6 | `BRD_CALL_LIMIT`=60 |

Ba quy tắc bất di bất dịch khi thêm subagent:

1. **Subagent `general-purpose` ngầm của deepagents phải TẮT.** `_set_general_purpose_enabled(False, ...)` trong `agent/harness.py`, gọi từ `builder.py`. Nó đã đốt 1.66M token trong một trace thật. Test canh: `tests/test_general_purpose_disabled.py`. Xem ADR `0002`.
2. **Đừng cấm hành vi file bằng prompt.** Mọi subagent nhận đủ filesystem toolset bất kể `tools` khai báo. Muốn cấm ghi một file thì khai `FilesystemPermission(operations=["write"], paths=[...], mode="deny")` — như `icon_resolver` làm với `/workspace/icon_plan.json`.
3. **Gate ở lại main agent.** Subagent không có checkpointer riêng, nên `interrupt()` bên trong nó không resume được. `wbs_planner` sinh dữ liệu, `propose_wbs`/`export_wbs_excel` chạy ở main.

Mọi subagent được bọc `_StreamingSubAgentRunnable` (`agent/streaming.py`) để tool call bên trong nổi lên stream ngoài dưới dạng ACTIVITY event.

---

## 3. Tool — dùng cái nào khi nào

Tool định nghĩa rải theo domain nhưng **danh sách** tập trung ở `tools/__init__.py` (`MAIN_TOOLS` 47 mục, cộng các list cho từng subagent). Thêm tool = thêm hàm `@tool` trong `tools/**` **và** đăng ký vào đúng list.

Theo phase:

| Phase | Tool chính | Ghi chú |
|---|---|---|
| intake | `analyze_architecture_requirements`, `propose_diagram_brief`, `web_research`, `find_similar_solutions` | `find_similar_solutions` gọi **trước** `propose_tech_stack` |
| blueprint | `propose_tech_stack` ⛩, `propose_blueprint` ⛩, `find_diagram_template` | Blueprint là nguồn sự thật cho mọi thứ sau nó |
| draw | `task(icon_resolver)` → `task(drawer)` → `task(critic)` → `finalize_diagram` ⛩ | Architecture đi **native path**; `render_typed_diagram` cho sequence/erd/state_machine |
| wbs | `task(wbs_planner)`, `propose_wbs_skeleton` ⛩, `propose_wbs` ⛩, `export_wbs_excel` ⛩, `get_effort_norms`, `benchmark_solution` | BA/QC/PM luôn **derive**, không tự ước lượng |
| ppt / report | `propose_deck_plan` ⛩, `generate_ppt_proposal` ⛩, `generate_pdf_report` ⛩, `export_proposal_package` | Gọi `generate_pdf_report({})` **không tham số** trừ khi có lý do rõ |
| brd | `task(brd_writer)`, `propose_brd_outline` ⛩, `generate_brd_docx` ⛩, `edit_brd_section` ⛩ | Xem `docs/plans/2026-07-29-brd-agent.md` |
| delivery | `export_to_delivery` ⛩, `send_email` ⛩, `create_client_meeting` ⛩, `reality_sync` | |

⛩ = HITL gate.

Nhóm tool ngang: findings/evidence (`record_evidence`, `waive_finding`, `quality_summary`), comment, compliance pack, `run_python` (pandas trên file upload / re-estimate WBS).

---

## 4. HITL gate

- 16 gate liệt kê ở `GATE_TOOL_NAMES` (`tools/__init__.py`), nối vào `create_deep_agent` qua `interrupt_on` trong `builder.py`. deepagents interrupt **trước khi** tool chạy.
- `GATE_DECISIONS` định nghĩa menu hành động cấp sản phẩm (`approve`, `approve_with_assumptions`, `accept_risk`, `request_evidence`, `request_alternative`, `reject`); `session/gate_decisions.py::_decision_from_payload` gấp chúng về approve/reject của langchain, và `decision_record_from_payload` lưu `DecisionRecord` có cấu trúc.
- `ROLE_GATE_PERMISSIONS` (14/16 gate — 2 gate soạn-thảo/skeleton, `propose_deck_plan` và `propose_wbs_skeleton`, cố ý để mở cho mọi role vì chưa phải deliverable khách thấy) + `can_approve(role, gate)` giới hạn ai được duyệt gate còn lại. Role đến từ `Identity` server resolve, **không bao giờ** từ body request. Role rỗng/không có trong danh sách bị **từ chối** ở gate có giới hạn (không còn mặc định cho qua); `agui_endpoint` (`routers/chat.py`) chặn bằng HTTP 403 **trước khi** stream response bắt đầu, trước cả `Command(resume=...)`.
- Trước khi duyệt, `_persist_pending_gate` ghi `pending_gate.json` (+ bản nháp như `tech_stack_draft.json`) để gate sống sót qua reload.
- Ngoại lệ: `propose_meeting_slots` dùng `interrupt()` nội bộ và **cố ý** không nằm trong `GATE_TOOL_NAMES`.

**Thêm gate mới:** thêm tên vào `GATE_TOOL_NAMES`, khai menu trong `GATE_DECISIONS`, khai quyền trong `ROLE_GATE_PERMISSIONS`, thêm card ở `frontend/src/gates/cards/` và đăng ký ở `frontend/src/gates/registry.ts`. Tool gate **phải có tham số** — gate không tham số không hiển thị được nội dung để duyệt.

Ngoài `interrupt_on` còn một gate cưỡng chế bằng code: `DrawerReviseGateMiddleware` chặn dispatch `task(drawer)` lần hai nếu chưa chạm `finalize_diagram` sau lần `task(critic)` gần nhất, và ép `CRITIC_REVISION_HARD_CAP = 2`.

---

## 5. Middleware — thứ tự là contract

```
ContextEditing → UsageLogging → ModelCallLimit → ToolArgCoercion
  → VisionErrorFallback → ToolCallLimit(task) → DrawerReviseGate
  → DrawerContextInject → PhaseToolFilter + PhasePromptFilter
  → SafeLLMToolSelector → [ModelFallback]
```

Ràng buộc phải giữ:
- `ToolArgCoercion` **trước** `DrawerReviseGate` (gate đọc arg đã chuẩn hoá).
- `KeepLatestImagesEdit` **trước** `InjectVisionAsUserEdit`.
- `exit_behavior`: `ModelCallLimit="end"`, `ToolCallLimit(task)="continue"`. `"end"` sẽ raise `NotImplementedError` nếu còn parallel tool call đang chờ.
- `ClearToolUsesEdit(clear_at_least=1_000_000, keep=4)` — con số vô lý một cách cố ý: edit là ephemeral, tính lại từ checkpoint đầy đủ mỗi lần, nên giá trị nhỏ chỉ gọt được một lát ở đầu và sàn context sẽ leo mãi.

Test canh: `tests/test_middleware_order.py`.

---

## 6. Memory contract

**Ghi vào `/memories/AGENTS.md`** (theo thread) và `/global-memories/AGENTS.md` (xuyên thread): sự thật bền — quy ước của khách, preference cách trình bày, ràng buộc dự án đã chốt. Giữ vài trăm từ; file này vào system prompt **mỗi lượt**.

**KHÔNG ghi:** credential/token, thông tin nhất thời ("đang chạy render lần 2"), nội dung có thể suy ra từ artifact trong workspace, dữ liệu khách dán nguyên khối.

**Không dùng làm memory:** Qdrant / `solution_memory.json`. Chúng là corpus past-project truy cập **qua tool** (`find_similar_solutions`, `benchmark_solution`), không nhét vào prompt. Xem ADR `0001`.

Trạng thái phiên đi vào **file trong workspace** (`blueprint.json`, `wbs.json`, …), không vào memory — vì phase machine đọc chính các file đó.

---

## 7. Budget & giới hạn

Đặt ở `agent/constants.py` + `tools/constants.py`, chỉnh qua env:

- Model call: main 80, icon 40, drawer 40, critic 40, wbs 60, ppt 60 (`*_CALL_LIMIT`).
- Render: `RENDER_SOFT_CAP=3`, `RENDER_HARD_CAP=6` mỗi vòng. Hard cap **không** phủ `export_drawio`.
- Icon search: `ICON_SEARCH_PER_QUERY_CAP=3`, tổng 20; `NODE_SINGLE_SEARCH_HARD_CAP=2`.
- Web search: `WEB_SEARCH_SESSION_CAP = 10` phải **bằng tổng** `WEB_SEARCH_CATEGORY_CAPS` (`tech_stack:4, architecture:2, wbs:1, evidence:2, general:1`). Đổi một bên phải đổi bên kia.
- Chi phí theo stage: `STAGE_BUDGET_USDCENT_{INTAKE,BLUEPRINT,WBS,PPT,RESEARCH}`.

Bộ đếm nằm ở file JSON trong workspace (`render_count.json`, `web_search_budget.json`, …) qua `tools/stage_markers.py`, nên chúng sống sót qua resume.

---

## 8. Khi thêm/sửa prompt

Prompt sống ở `prompts/`, khối dùng chung ở `_blocks.py` với span `[[PHASE ...]]` để `PhasePromptFilterMiddleware` cắt theo phase. Hai điều cần nhớ:

- Dùng root ảo `/workspace`, không bao giờ `str(WORKSPACE)`.
- Phase filter làm prompt **biến thiên** → phá prompt caching. Nếu main chuyển sang provider có caching, tắt cả phase prompt filter lẫn tool filter và giữ prompt ổn định byte thay vì tiết kiệm 2.5K token/lượt.

Mọi thay đổi prompt/model phải kèm eval artifact — xem `testing.md`.
