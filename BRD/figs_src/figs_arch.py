"""H1/H2/H3 — sinh bằng mingrammer `diagrams` + Graphviz (đúng việc: hạ tầng,
không phải flowchart/sequence). Sửa theo BRD gap analysis §A5, §A6:
- H2: thêm service copilot-runtime (:3001) đang thiếu.
- H3: 41 tool (không phải 35), 12 middleware (không phải 9), LLMToolSelector
  đánh dấu "inactive in shipped config", wbs_planner 6 tool (không phải 4),
  thêm hai gate điều khiển bằng code (DrawerReviseGate, PhaseToolFilter),
  RECURSION_LIMIT=450, icon riêng cho từng subagent.
"""
import os
from diagrams import Diagram, Cluster, Edge, Node
from diagrams.onprem.client import Users, User, Client
from diagrams.onprem.database import PostgreSQL
from diagrams.onprem.compute import Server
from diagrams.onprem.network import Nginx
from diagrams.programming.framework import React, Fastapi
from diagrams.programming.language import Python, Nodejs, Typescript
from diagrams.generic.storage import Storage
from diagrams.generic.compute import Rack
from diagrams.generic.blank import Blank
import diagrams.programming.flowchart as fc

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)

FONT = "DejaVu Sans"
ACCENT = "#1F4E79"
WARN = "#B45309"
GRAY = "#666666"

GRAPH = {
    "fontname": FONT, "bgcolor": "white", "fontsize": "20",
    "labelloc": "t", "pad": "0.4", "nodesep": "0.55", "ranksep": "0.85",
    "splines": "ortho",
}
NODE = {"fontname": FONT, "fontsize": "15"}
EDGE = {"fontname": FONT, "fontsize": "13", "color": GRAY}
CLU = {"fontname": FONT, "fontsize": "16", "bgcolor": "#F4F7FB",
       "pencolor": ACCENT, "style": "rounded", "penwidth": "1.2"}


def d(name, title, **kw):
    g = dict(GRAPH)
    g.update(kw.pop("graph_attr", {}))
    return Diagram(title, filename=os.path.join(OUT, name), outformat="png",
                   show=False, graph_attr=g, node_attr=NODE, edge_attr=EDGE, **kw)


# ── H1. Sơ đồ ngữ cảnh hệ thống (giữ nguyên cấu trúc, thêm legend) ───────────
with d("h1_context", "Hình 1 — Sơ đồ ngữ cảnh hệ thống (System Context)", direction="LR"):
    with Cluster("Người dùng nghiệp vụ (Business users)", graph_attr=CLU):
        ba = User("BA / Solution Architect")
        pm = User("Project Manager")
        cl = Users("Khách hàng (Client)")

    with Cluster("Diagram Code Agent Platform", graph_attr=CLU):
        ui = React("Web UI\n(React + AG-UI/SSE)")
        rt = Nodejs("CopilotKit runtime\n(Node ESM :3001)")
        api = Fastapi("Agent API\n(FastAPI :8001)")
        agent = Rack("Deep Agent\n(LangGraph orchestrator)")
        ui >> Edge(label="SSE stream") >> rt >> Edge(label="proxy /agui") >> api >> agent

    with Cluster("Dịch vụ ngoài (External services)", graph_attr=CLU):
        llm = Server("LLM Provider\n(mimo-v2.5-pro qua OpenAI-compatible API)")
        tav = Server("Tavily\n(Web research)")
        comp = Server("Composio\n(Gmail / Calendar / Meet)")
        jira = Server("Jira / Linear\n(Delivery sync)")

    with Cluster("Lưu trữ (Persistence)", graph_attr=CLU):
        pg = PostgreSQL("PostgreSQL\ncheckpoint + conversations")
        ws = Storage("Workspace\nagent_space/workspaces/<thread_id>")

    ba >> Edge(label="yêu cầu + tài liệu") >> ui
    pm >> ui
    ui >> Edge(label="tải deliverable", style="dashed") >> cl

    agent >> Edge(label="inference") >> llm
    agent >> Edge(label="≤10 truy vấn/phiên") >> tav
    agent >> Edge(label="gửi mail, đặt lịch") >> comp
    agent >> Edge(label="đồng bộ WBS") >> jira
    agent >> pg
    agent >> ws


# ── H2. Kiến trúc triển khai — THÊM copilot-runtime đang thiếu ──────────────
with d("h2_deployment", "Hình 2 — Kiến trúc triển khai (Deployment / Docker Compose)",
       graph_attr={"splines": "spline", "pad": "0.8", "nodesep": "0.7"}):
    dev = Client("Trình duyệt người dùng")
    with Cluster("Docker Compose — project: diagram-agent", graph_attr=CLU):
        with Cluster("service: frontend (nginx:alpine)", graph_attr=CLU):
            fe = Nginx("SPA build (Vite)\ncổng 5173 → 80")
        with Cluster("service: copilot-runtime (node:20)", graph_attr=CLU):
            rt = Nodejs("CopilotRuntime\ncổng 3001\n(AG-UI ↔ /agui bridge)")
        with Cluster("service: backend (python:3.11-slim)", graph_attr=CLU):
            be = Fastapi("diagram-agent-server\ncổng 8001")
            gv = Python("Graphviz + Playwright\n(render PNG / PDF)")
            be - Edge(style="dotted") - gv
        with Cluster("service: postgres (16-alpine)", graph_attr=CLU):
            db = PostgreSQL("checkpoints, store,\nconversations")
        with Cluster("Volumes", graph_attr=CLU):
            v1 = Storage("./artifacts\n(workspace theo thread)")
            v2 = Storage("agent_space\n(uploads, skills, outputs)")

    dev >> Edge(label="HTTP :5173") >> fe
    fe >> Edge(label="proxy /api/copilotkit") >> rt
    rt >> Edge(label="rewrite → POST /agui\n(VITE_BACKEND_URL)") >> be
    be >> Edge(label="asyncpg pool (max 20)") >> db
    be >> v1
    be >> v2


# ── H3. Kiến trúc Deep Agent & subagent — SỬA số liệu đúng code thật ────────
with d("h3_agent", "Hình 3 — Kiến trúc Deep Agent, middleware và các subagent",
       graph_attr={"ranksep": "1.3", "nodesep": "0.9"}):
    req = Blank("Yêu cầu\nngười dùng")

    with Cluster("Middleware — 12 lớp cố định\n(agent/middleware/__init__.py)", graph_attr=CLU):
        m1 = Blank("1-3\nContext ·\nUsage ·\nCallLimit")
        m2 = Blank("4-6\nCoercion ·\nVision ·\nTaskLimit")
        m3 = Blank("7-9\nDrawerGate ·\nCtxInject ·\nPhaseFilter")
        m4 = Blank("10-12\nPromptFilter ·\nSelector(tắt) ·\nFallback")
        m1 >> Edge(style="dashed") >> m2 >> Edge(style="dashed") >> m3 >> Edge(style="dashed") >> m4

    main = Rack("MAIN AGENT\n41 tool")

    with Cluster("Budget", graph_attr=CLU):
        budget = Blank("RUN_CALL_LIMIT=80\nRECURSION_LIMIT=450\ntask() ≤12/phiên")

    with Cluster("Subagents (5) — general-purpose bị tắt", graph_attr=CLU):
        s1 = Python("icon_resolver\n7 tool · limit 40")
        s2 = Typescript("drawer\n8 tool · limit 40\nvision relay bật")
        s3 = Rack("critic\n2 tool · limit 40\nvision relay bật")
        s4 = Server("wbs_planner\n6 tool · limit 60\n5 WBS + run_python")
        s5 = Nginx("ppt_generator\n3 tool · limit 60")

    with Cluster("Skills", graph_attr=CLU):
        sk = Storage("diagrams-as-code\npro-style\nwbs-planning\nppt-generator")

    with Cluster("Trạng thái bền vững", graph_attr=CLU):
        st = Storage("workspace/*.json\n(state machine thực tế:\nphase suy từ file trên đĩa)")
        cp = PostgreSQL("LangGraph checkpoint\n+ pending interrupt")

    req >> m1
    m4 >> main
    main - Edge(style="dotted") - budget
    main >> Edge(label="task(subagent_type)") >> s1
    main >> s2
    main >> s3
    main >> s4
    main >> s5
    s2 >> Edge(style="dotted", label="load") >> sk
    main >> Edge(label="đọc/ghi") >> st
    main >> cp


# ── H5. Vòng đời artifact trong workspace — BỔ SUNG file thật đang thiếu ────
# Danh mục ĐẦY ĐỦ (15 file thêm so với v1.0: tech_stack_draft.json,
# blueprint_draft.json, pending_gate.json, design_tokens.json, layout_plan.json,
# label_fits.json, _logos/, out.native_stats.json, diagram_manifest.json,
# quality_snapshot.json, render_count.json, revision_count.json,
# interpreter_count.json, out_patched.pptx, deck_visual_audit.json) nằm ở
# Bảng M-Artifacts trong nội dung BRD — hình này chỉ giữ 1-2 file đại diện
# mỗi ô để không lặp lại lỗi tràn chữ của bản v1.0.
with d("h5_artifacts", "Hình 5 — Vòng đời artifact trong workspace (state machine theo phase)",
       direction="TB", graph_attr={"nodesep": "0.6", "ranksep": "0.55"}):
    with Cluster("Cột 1 — từ yêu cầu tới bản thiết kế", graph_attr=CLU):
        p0 = fc.Document("PHASE intake\nrequirements.md")
        p1 = fc.Document("PHASE blueprint\ntech_stack_draft.json →\ntech_stack.json")
        p2 = fc.Document("blueprint_draft.json →\nblueprint.json, render_spec.json")
        p0 >> p1 >> p2
    with Cluster("Cột 2 — từ bản vẽ tới deliverable", graph_attr=CLU):
        p3 = fc.Document("PHASE draw\nicon_plan.json → out.png,\nout.drawio, layout_plan.json")
        p4 = fc.Document("engineer_report.json,\nquality_history.json → critique.json")
        p5 = fc.MultipleDocuments("PHASE wbs / report / ppt\nwbs_filled.xlsx, out.pdf,\nout.pptx, out_patched.pptx")
        p6 = fc.Document("PHASE brd (đề xuất mới)\nbrd_outline.json →\nout.brd.docx")
        p3 >> p4 >> p5 >> p6
    with Cluster("Sổ cái quản trị (append-only)", graph_attr=CLU):
        gov = fc.StoredData("solution_model.json (CSM),\nevidence/decision/findings/\ncomment_log.json, usage.json")

    p2 >> Edge(color=ACCENT) >> p3
    p2 >> Edge(style="dotted", label="project", constraint="false") >> gov
    p5 >> Edge(style="dotted", constraint="false") >> gov
    p6 >> Edge(style="dotted", constraint="false") >> gov
