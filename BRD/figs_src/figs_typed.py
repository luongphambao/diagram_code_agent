"""S1-S4 (sequence), ST1-ST3 (state machine), E1-E2 (ERD) — MỚI, dogfood
backend/src/prettygraph/native/* qua render_typed.py. Mọi lifeline, state,
transition, cột bảng đều trỏ về một dòng code hoặc một file trace thật
(xem BRD gap analysis §B3-B5 và các trích dẫn trong docstring mỗi spec).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_typed import render_typed_spec  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════
# S1 — Vòng đời một request chat
# Nguồn: routers/chat.py (agui_endpoint, ensure_owner, astream), runtime/src/
# diagram-agent.ts (DiagramHttpAgent.requestInit), session/sse.py (_sse).
# ═══════════════════════════════════════════════════════════════════════
S1 = {
    "title": "S1 — Vòng đời một request chat (POST /agui → SSE)",
    "participants": [
        {"id": "user", "label": "Người dùng", "kind": "actor"},
        {"id": "fe", "label": "Web UI (React)", "kind": "frontend"},
        {"id": "rt", "label": "CopilotKit runtime", "kind": "service"},
        {"id": "api", "label": "FastAPI /agui", "kind": "service"},
        {"id": "graph", "label": "LangGraph + middleware", "kind": "service"},
        {"id": "llm", "label": "LLM Provider", "kind": "external"},
        {"id": "tool", "label": "Tool / Gate", "kind": "service"},
    ],
    "messages": [
        {"order": 1, "from": "user", "to": "fe", "label": "Nhập yêu cầu + đính kèm", "kind": "sync"},
        {"order": 2, "from": "fe", "to": "rt", "label": "AG-UI RunAgentInput (SSE)", "kind": "sync"},
        {"order": 3, "from": "rt", "to": "api", "label": "rewrite → POST /agui", "kind": "sync"},
        {"order": 4, "from": "api", "to": "graph", "label": "astream(messages, config, recursion_limit=450)", "kind": "sync"},
        {"order": 5, "from": "graph", "to": "llm", "label": "inference (qua 12 middleware)", "kind": "sync"},
        {"order": 6, "from": "llm", "to": "graph", "label": "tool_call: propose_tech_stack", "kind": "return"},
        {"order": 7, "from": "graph", "to": "tool", "label": "invoke gate tool", "kind": "sync"},
        {"order": 8, "from": "tool", "to": "graph", "label": "interrupt_on fires trước khi chạy thân tool", "kind": "return"},
        {"order": 9, "from": "graph", "to": "api", "label": "aget_state → task.interrupts[0]", "kind": "return"},
        {"order": 10, "from": "api", "to": "rt", "label": "TOOL_CALL_START/ARGS/END (card JSON)", "kind": "async"},
        {"order": 11, "from": "rt", "to": "fe", "label": "SSE relay + artifact substitution", "kind": "async"},
        {"order": 12, "from": "fe", "to": "user", "label": "Hiển thị gate card (GateHost)", "kind": "async"},
    ],
    "fragments": [],
    "activations": [{"participant": "graph", "start_order": 4, "end_order": 9}],
}

# ═══════════════════════════════════════════════════════════════════════
# S2 — Cổng HITL: interrupt → card → resume
# Nguồn: session/gate_decisions.py (_card_for, _persist_pending_gate,
# _decision_from_payload), routers/chat.py:88-125 (_persist_decision_record).
# ═══════════════════════════════════════════════════════════════════════
S2 = {
    "title": "S2 — Cổng HITL: interrupt → card → resume",
    "participants": [
        {"id": "main", "label": "Main agent", "kind": "service"},
        {"id": "mw", "label": "HumanInTheLoop MW", "kind": "service"},
        {"id": "cp", "label": "Checkpointer", "kind": "database"},
        {"id": "pg", "label": "pending_gate.json", "kind": "external"},
        {"id": "sse", "label": "SSE (chat.py)", "kind": "service"},
        {"id": "ui", "label": "GateHost (FE)", "kind": "frontend"},
        {"id": "approver", "label": "Người duyệt", "kind": "actor"},
    ],
    "messages": [
        {"order": 1, "from": "main", "to": "mw", "label": "gọi gate tool (vd propose_blueprint)", "kind": "sync"},
        {"order": 2, "from": "mw", "to": "cp", "label": "ghi interrupt vào graph state", "kind": "sync"},
        {"order": 3, "from": "cp", "to": "mw", "label": "state bền vững (sống sót qua restart)", "kind": "return"},
        {"order": 4, "from": "mw", "to": "pg", "label": "_persist_pending_gate()", "kind": "sync"},
        {"order": 5, "from": "mw", "to": "sse", "label": "STATE_DELTA + TOOL_CALL_START/ARGS/END", "kind": "sync"},
        {"order": 6, "from": "sse", "to": "ui", "label": "toolCallName = card[\"type\"]", "kind": "async"},
        {"order": 7, "from": "ui", "to": "approver", "label": "hiển thị card đúng theo role", "kind": "async"},
        {"order": 8, "from": "approver", "to": "ui", "label": "chọn quyết định", "kind": "sync"},
        {"order": 9, "from": "ui", "to": "sse", "label": "message role:\"tool\" (payload quyết định)", "kind": "sync"},
        {"order": 10, "from": "sse", "to": "main", "label": "Command(resume={decisions:[...]})", "kind": "sync"},
        {"order": 11, "from": "main", "to": "cp", "label": "decision_log.json + archive_approved_revision", "kind": "sync"},
    ],
    "fragments": [
        {"kind": "alt", "condition": "proceed (approve*) ⟷ revise (reject*)", "start_order": 8, "end_order": 10}
    ],
    "activations": [],
}

# ═══════════════════════════════════════════════════════════════════════
# S3 — Uỷ nhiệm subagent + engineer loop (vẽ diagram)
# Nguồn: agent/middleware/drawer_gate.py, prettygraph/native/repair.py,
# tools/rendering_tools.py (edit_drawio/inspect_render_quality), thực đo tại
# artifacts/thread-ms33ubw0-6frps (9 vòng quality_history.json, 7 revert).
# ═══════════════════════════════════════════════════════════════════════
S3 = {
    "title": "S3 — Uỷ nhiệm subagent + engineer loop",
    "participants": [
        {"id": "main", "label": "Main agent", "kind": "service"},
        {"id": "icon", "label": "icon_resolver", "kind": "service"},
        {"id": "drawer", "label": "drawer", "kind": "service"},
        {"id": "repair", "label": "repair.py (Tier 0)", "kind": "service"},
        {"id": "critic", "label": "critic", "kind": "service"},
        {"id": "approver", "label": "Người duyệt", "kind": "actor"},
    ],
    "messages": [
        {"order": 1, "from": "main", "to": "icon", "label": "task(subagent_type=icon_resolver)", "kind": "sync"},
        {"order": 2, "from": "icon", "to": "main", "label": "icon_plan.json", "kind": "return"},
        {"order": 3, "from": "main", "to": "drawer", "label": "task(drawer) — render_spec.json injected", "kind": "sync"},
        {"order": 4, "from": "drawer", "to": "repair", "label": "auto_repair(): 6 phương án, 0 token", "kind": "sync"},
        {"order": 5, "from": "repair", "to": "drawer", "label": "chọn layout thắng (engineer_report.json)", "kind": "return"},
        {"order": 6, "from": "drawer", "to": "drawer", "label": "edit_drawio → inspect_render_quality (≤2 vòng)", "kind": "sync"},
        {"order": 7, "from": "drawer", "to": "drawer", "label": "tụt >1 điểm ⇒ auto-revert (quality_history.json)", "kind": "return"},
        {"order": 8, "from": "drawer", "to": "main", "label": "out.drawio, out.png", "kind": "return"},
        {"order": 9, "from": "main", "to": "critic", "label": "task(subagent_type=critic)", "kind": "sync"},
        {"order": 10, "from": "critic", "to": "main", "label": "PASS / REVISE (critique.json)", "kind": "return"},
        {"order": 11, "from": "main", "to": "drawer", "label": "task(drawer) + critique.json (DrawerContextInject)", "kind": "sync"},
        {"order": 12, "from": "drawer", "to": "main", "label": "bản vẽ đã sửa", "kind": "return"},
        {"order": 13, "from": "main", "to": "approver", "label": "finalize_diagram (GATE 3)", "kind": "sync"},
    ],
    "fragments": [
        {"kind": "loop", "condition": "Tier 1-2, ≤2 vòng (DRAWIO_EDIT_CAP)", "start_order": 6, "end_order": 7},
        {"kind": "opt", "condition": "REVISE, ≤2 lần", "start_order": 11, "end_order": 12},
    ],
    "activations": [],
}

# ═══════════════════════════════════════════════════════════════════════
# S4 — Chỉnh sửa BRD theo section (FR09, đề xuất mới)
# Nguồn: KE_HOACH_BRD_AGENT.md §7 (ba lớp: anchor map, patch ops, optimistic
# lock qua checksum).
# ═══════════════════════════════════════════════════════════════════════
S4 = {
    "title": "S4 — Chỉnh sửa BRD theo section (FR09)",
    "participants": [
        {"id": "user", "label": "Người dùng", "kind": "actor"},
        {"id": "main", "label": "brd_writer / main", "kind": "service"},
        {"id": "reader", "label": "read_brd_outline", "kind": "service"},
        {"id": "map", "label": "anchor_map.json", "kind": "database"},
        {"id": "patcher", "label": "edit_brd_section", "kind": "service"},
        {"id": "writer", "label": "OOXML writer", "kind": "service"},
        {"id": "rev", "label": "brd_revisions/", "kind": "database"},
    ],
    "messages": [
        {"order": 1, "from": "user", "to": "main", "label": "\"sửa mục 4.3 Security\"", "kind": "sync"},
        {"order": 2, "from": "main", "to": "reader", "label": "read_brd_outline()", "kind": "sync"},
        {"order": 3, "from": "reader", "to": "map", "label": "đọc [start,end], checksum hiện hành", "kind": "sync"},
        {"order": 4, "from": "map", "to": "reader", "label": "checksum SHA-256 rút gọn", "kind": "return"},
        {"order": 5, "from": "reader", "to": "main", "label": "section_id + expect_checksum", "kind": "return"},
        {"order": 6, "from": "main", "to": "patcher", "label": "edit_brd_section(section_id, expect_checksum, content)", "kind": "sync"},
        {"order": 7, "from": "patcher", "to": "writer", "label": "replace_body — mượn style template", "kind": "sync"},
        {"order": 8, "from": "writer", "to": "rev", "label": "ghi REV-n.docx + patch_log.json", "kind": "sync"},
        {"order": 9, "from": "writer", "to": "main", "label": "out.brd.docx (revision+1)", "kind": "return"},
        {"order": 10, "from": "patcher", "to": "main", "label": "checksum lệch ⇒ từ chối, yêu cầu lập chỉ mục lại", "kind": "return"},
        {"order": 11, "from": "main", "to": "user", "label": "diff trước/sau + nút hoàn tác", "kind": "async"},
    ],
    "fragments": [
        {"kind": "alt", "condition": "checksum khớp ⟷ checksum lệch (từ chối)", "start_order": 7, "end_order": 10},
    ],
    "activations": [],
}


# ═══════════════════════════════════════════════════════════════════════
# ST1 — Vòng đời cổng HITL
# Nguồn: HumanInTheLoopMiddleware interrupt_on, GATE_DECISIONS (tools/
# __init__.py), _decision_from_payload (gate_decisions.py:413-444).
# ═══════════════════════════════════════════════════════════════════════
ST1 = {
    "title": "ST1 — Vòng đời cổng HITL",
    "states": [
        {"id": "idle", "label": "idle", "kind": "initial"},
        {"id": "pending", "label": "pending", "kind": "normal"},
        {"id": "approved", "label": "approved", "kind": "normal"},
        {"id": "rejected", "label": "rejected", "kind": "normal"},
        {"id": "edited", "label": "edited", "kind": "normal"},
        {"id": "resumed", "label": "resumed", "kind": "final"},
        {"id": "restarted", "label": "service restart", "kind": "choice"},
    ],
    "transitions": [
        {"from": "idle", "to": "pending", "event": "interrupt_on fires (gọi gate tool)"},
        {"from": "pending", "to": "approved", "event": "approve | approve_with_assumptions | accept_risk"},
        {"from": "pending", "to": "rejected", "event": "reject | request_evidence | request_alternative"},
        {"from": "pending", "to": "edited", "event": "decision=edit (HITL v2 payload sửa tay)"},
        {"from": "approved", "to": "resumed", "event": "Command(resume={decisions})"},
        {"from": "rejected", "to": "resumed", "event": "Command(resume) — agent quay lại sửa"},
        {"from": "edited", "to": "resumed", "event": "Command(resume) với payload đã sửa"},
        {"from": "pending", "to": "restarted", "event": "process restart"},
        {"from": "restarted", "to": "pending", "event": "checkpoint + pending_gate.json khôi phục"},
    ],
}

# ═══════════════════════════════════════════════════════════════════════
# ST2 — State machine phase (thực chất là "state machine" duy nhất của agent)
# Nguồn: agent/middleware/phase_filter.py:145-157 (_detect_phase),
# tools/stage_markers.py (clear_stage_markers).
# ═══════════════════════════════════════════════════════════════════════
ST2 = {
    "title": "ST2 — State machine phase (suy từ file trên đĩa, tính lại mỗi lần gọi model)",
    "states": [
        {"id": "intake", "label": "intake", "kind": "initial"},
        {"id": "blueprint", "label": "blueprint", "kind": "normal"},
        {"id": "draw", "label": "draw", "kind": "normal"},
        {"id": "wbs", "label": "wbs", "kind": "normal"},
        {"id": "ppt", "label": "ppt", "kind": "normal"},
        {"id": "report", "label": "report", "kind": "normal"},
        {"id": "missing_artifact", "label": "backfill nếu thiếu file", "kind": "choice"},
        {"id": "pending_gate", "label": "gate đang chờ duyệt", "kind": "choice"},
    ],
    "transitions": [
        {"from": "intake", "to": "blueprint", "event": "tech_stack.json ∨ architecture_analysis.json tồn tại"},
        {"from": "blueprint", "to": "draw", "event": "out.png ∨ blueprint.json tồn tại"},
        {"from": "draw", "to": "wbs", "event": "wbs.json tồn tại"},
        {"from": "wbs", "to": "ppt", "event": "deck_plan.json tồn tại"},
        {"from": "ppt", "to": "report", "event": "out.pdf tồn tại"},
        {"from": "report", "to": "intake", "event": "reset (clear_stage_markers)"},
        {"from": "blueprint", "to": "missing_artifact", "event": "tech_stack.json bị thiếu"},
        {"from": "missing_artifact", "to": "blueprint", "event": "giữ propose_tech_stack trong allowed set (backfill)"},
        {"from": "draw", "to": "pending_gate", "event": "pending_gate.json tồn tại"},
        {"from": "pending_gate", "to": "draw", "event": "giữ tool đang chờ duyệt trong allowed set"},
    ],
}

# ═══════════════════════════════════════════════════════════════════════
# ST3 — Vòng chất lượng diagram (engineer loop, 3 tầng)
# Nguồn: tools/constants.py (_DRAWIO_EDIT_CAP, _EDIT_REGRESSION_TOLERANCE),
# agent/middleware/drawer_gate.py:114-127 (_decide — cấp lại budget).
# ═══════════════════════════════════════════════════════════════════════
ST3 = {
    "title": "ST3 — Vòng chất lượng diagram (engineer loop)",
    "states": [
        {"id": "rendered", "label": "rendered", "kind": "initial"},
        {"id": "scored", "label": "scored", "kind": "normal"},
        {"id": "kept", "label": "kept (cải thiện)", "kind": "normal"},
        {"id": "reverted", "label": "reverted (tụt >1 điểm)", "kind": "normal"},
        {"id": "budget_exhausted", "label": "hết budget (2 edit + 2 inspect)", "kind": "choice"},
        {"id": "finalized", "label": "finalized (GATE 3)", "kind": "final"},
    ],
    "transitions": [
        {"from": "rendered", "to": "scored", "event": "inspect_render_quality"},
        {"from": "scored", "to": "finalized", "event": "PASS ⇒ finalize_diagram"},
        {"from": "scored", "to": "kept", "event": "điểm cải thiện ⇒ giữ bản vá"},
        {"from": "scored", "to": "reverted", "event": "tụt > _EDIT_REGRESSION_TOLERANCE=1.0 ⇒ tự động hoàn tác"},
        {"from": "kept", "to": "rendered", "event": "edit_drawio lần kế (≤2)"},
        {"from": "reverted", "to": "rendered", "event": "edit_drawio lần kế (≤2)"},
        {"from": "rendered", "to": "budget_exhausted", "event": "đã dùng hết 2 lượt edit + 2 lượt inspect"},
        {"from": "budget_exhausted", "to": "finalized", "event": "finalize_diagram với điểm hiện tại (có thể dưới ngưỡng)"},
    ],
}


# ═══════════════════════════════════════════════════════════════════════
# E1 — Lược đồ lưu trữ (PostgreSQL 16)
# Nguồn: conversations.py:22-32 (DDL thật của app); langgraph/checkpoint/
# postgres/base.py và langgraph/store/postgres/base.py (DDL thật của thư viện
# langgraph-checkpoint-postgres — không thuộc schema riêng của dự án).
# ═══════════════════════════════════════════════════════════════════════
E1 = {
    "title": "E1 — Lược đồ lưu trữ PostgreSQL 16",
    "entities": [
        {
            "id": "conversations",
            "name": "conversations (ứng dụng)",
            "columns": [
                {"name": "thread_id", "data_type": "text", "primary_key": True},
                {"name": "name", "data_type": "text", "default": "'Untitled'"},
                {"name": "created_at", "data_type": "timestamptz", "default": "NOW()"},
                {"name": "updated_at", "data_type": "timestamptz", "default": "NOW()"},
                {"name": "last_message", "data_type": "text"},
                {"name": "messages_json", "data_type": "text", "default": "'[]'"},
                {"name": "state_json", "data_type": "text", "default": "'{}'"},
                {"name": "outcomes_json", "data_type": "text", "default": "'[]'"},
                {"name": "owner_email", "data_type": "text"},
            ],
        },
        {
            "id": "checkpoints",
            "name": "checkpoints (langgraph-checkpoint-postgres)",
            "columns": [
                {"name": "thread_id", "data_type": "text", "primary_key": True, "foreign_key": True, "references": "conversations.thread_id"},
                {"name": "checkpoint_ns", "data_type": "text", "primary_key": True, "default": "''"},
                {"name": "checkpoint_id", "data_type": "text", "primary_key": True},
                {"name": "parent_checkpoint_id", "data_type": "text"},
                {"name": "type", "data_type": "text"},
                {"name": "checkpoint", "data_type": "jsonb"},
                {"name": "metadata", "data_type": "jsonb", "default": "'{}'"},
            ],
        },
        {
            "id": "checkpoint_blobs",
            "name": "checkpoint_blobs (thư viện)",
            "columns": [
                {"name": "thread_id", "data_type": "text", "primary_key": True},
                {"name": "checkpoint_ns", "data_type": "text", "primary_key": True, "default": "''"},
                {"name": "channel", "data_type": "text", "primary_key": True},
                {"name": "version", "data_type": "text", "primary_key": True},
                {"name": "type", "data_type": "text"},
                {"name": "blob", "data_type": "bytea"},
            ],
        },
        {
            "id": "checkpoint_writes",
            "name": "checkpoint_writes (thư viện)",
            "columns": [
                {"name": "thread_id", "data_type": "text", "primary_key": True},
                {"name": "checkpoint_ns", "data_type": "text", "primary_key": True, "default": "''"},
                {"name": "checkpoint_id", "data_type": "text", "primary_key": True},
                {"name": "task_id", "data_type": "text", "primary_key": True},
                {"name": "idx", "data_type": "integer", "primary_key": True},
                {"name": "channel", "data_type": "text"},
                {"name": "type", "data_type": "text"},
                {"name": "blob", "data_type": "bytea"},
            ],
        },
        {
            "id": "store",
            "name": "store (langgraph Store — memory)",
            "columns": [
                {"name": "prefix", "data_type": "text", "primary_key": True},
                {"name": "key", "data_type": "text", "primary_key": True},
                {"name": "value", "data_type": "jsonb"},
                {"name": "created_at", "data_type": "timestamptz"},
                {"name": "updated_at", "data_type": "timestamptz"},
            ],
        },
    ],
    "relationships": [
        {"from_entity": "checkpoints", "from_columns": ["thread_id"], "to_entity": "conversations", "to_columns": ["thread_id"], "cardinality": "one_to_many"},
        {"from_entity": "checkpoint_blobs", "from_columns": ["thread_id"], "to_entity": "checkpoints", "to_columns": ["thread_id"], "cardinality": "one_to_many"},
        {"from_entity": "checkpoint_writes", "from_columns": ["thread_id", "checkpoint_id"], "to_entity": "checkpoints", "to_columns": ["thread_id", "checkpoint_id"], "cardinality": "one_to_many"},
    ],
}

# ═══════════════════════════════════════════════════════════════════════
# E2 — Mô hình CSM (thay Hình 6) — 9 quan hệ có kiểu thật từ code
# Nguồn: memory/stores/csm.py (SolutionModel), csm_adapter.py.
# ═══════════════════════════════════════════════════════════════════════
E2 = {
    "title": "E2 — Mô hình dữ liệu CSM (Canonical Solution Model)",
    "entities": [
        {"id": "req", "name": "Requirement (REQ)", "columns": [
            {"name": "id", "data_type": "text", "primary_key": True},
            {"name": "text", "data_type": "text"},
            {"name": "kind", "data_type": "text"},
        ]},
        {"id": "con", "name": "Constraint (CON)", "columns": [
            {"name": "id", "data_type": "text", "primary_key": True},
            {"name": "text", "data_type": "text"},
        ]},
        {"id": "asm", "name": "Assumption (ASM)", "columns": [
            {"name": "id", "data_type": "text", "primary_key": True},
            {"name": "text", "data_type": "text"},
            {"name": "confirmed", "data_type": "boolean"},
        ]},
        {"id": "dec", "name": "Decision (DEC)", "columns": [
            {"name": "id", "data_type": "text", "primary_key": True},
            {"name": "chosen_option", "data_type": "text"},
            {"name": "rationale", "data_type": "text"},
        ]},
        {"id": "comp", "name": "Component (COMP)", "columns": [
            {"name": "id", "data_type": "text", "primary_key": True},
            {"name": "name", "data_type": "text"},
            {"name": "cluster", "data_type": "text"},
        ]},
        {"id": "risk", "name": "Risk (RISK)", "columns": [
            {"name": "id", "data_type": "text", "primary_key": True},
            {"name": "severity", "data_type": "text"},
        ]},
        {"id": "ctrl", "name": "Control (CTRL)", "columns": [
            {"name": "id", "data_type": "text", "primary_key": True},
            {"name": "description", "data_type": "text"},
        ]},
        {"id": "wi", "name": "WorkItem (WBS)", "columns": [
            {"name": "id", "data_type": "text", "primary_key": True},
            {"name": "task", "data_type": "text"},
            {"name": "dev_effort_md", "data_type": "decimal"},
        ]},
        {"id": "evd", "name": "Evidence (EVD)", "columns": [
            {"name": "id", "data_type": "text", "primary_key": True},
            {"name": "source", "data_type": "text"},
        ]},
        {"id": "art", "name": "Deliverable (ART)", "columns": [
            {"name": "id", "data_type": "text", "primary_key": True},
            {"name": "kind", "data_type": "text"},
        ]},
    ],
    "relationships": [
        {"from_entity": "comp", "from_columns": ["id"], "to_entity": "req", "to_columns": ["id"], "cardinality": "many_to_many"},  # satisfies
        {"from_entity": "con", "from_columns": ["id"], "to_entity": "dec", "to_columns": ["id"], "cardinality": "many_to_many"},  # constrains
        {"from_entity": "asm", "from_columns": ["id"], "to_entity": "dec", "to_columns": ["id"], "cardinality": "many_to_many"},  # assumes
        {"from_entity": "dec", "from_columns": ["id"], "to_entity": "comp", "to_columns": ["id"], "cardinality": "many_to_many"},  # implements
        {"from_entity": "ctrl", "from_columns": ["id"], "to_entity": "risk", "to_columns": ["id"], "cardinality": "many_to_many"},  # mitigates
        {"from_entity": "wi", "from_columns": ["id"], "to_entity": "comp", "to_columns": ["id"], "cardinality": "many_to_many"},  # implements
        {"from_entity": "evd", "from_columns": ["id"], "to_entity": "dec", "to_columns": ["id"], "cardinality": "many_to_many"},  # supports
        {"from_entity": "art", "from_columns": ["id"], "to_entity": "comp", "to_columns": ["id"], "cardinality": "many_to_many"},  # visualizes
        {"from_entity": "art", "from_columns": ["id"], "to_entity": "req", "to_columns": ["id"], "cardinality": "many_to_many"},  # claims
    ],
}


if __name__ == "__main__":
    render_typed_spec("sequence", S1, "s1_request_lifecycle")
    render_typed_spec("sequence", S2, "s2_gate_lifecycle")
    render_typed_spec("sequence", S3, "s3_subagent_engineer_loop")
    render_typed_spec("sequence", S4, "s4_brd_section_edit")
    render_typed_spec("state_machine", ST1, "st1_gate_lifecycle")
    render_typed_spec("state_machine", ST2, "st2_phase_state_machine")
    render_typed_spec("state_machine", ST3, "st3_diagram_quality_loop")
    render_typed_spec("erd", E1, "e1_storage_schema")
    render_typed_spec("erd", E2, "e2_csm_model")
    print("ALL TYPED FIGURES RENDERED")
