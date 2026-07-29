"""H4a/H4b/H4c — thay cho Hình 4 gốc (13 gate nhồi vào một flowchart 4 cột,
dùng constraint="false" khiến cạnh uốn khắp canvas và nhãn chồng nhau — xem
BRD gap analysis §A11). Tách theo giai đoạn, mỗi hình một chuỗi dọc đơn để
Graphviz không phải giải bài toán bố cục nhiều cột như bản gốc.

Quy ước hình: hình thoi = cổng phê duyệt HITL; hình chữ nhật = hành động agent;
hình chữ nhật kép = tiến trình con (subagent); nét đứt = luồng quay lui.
"""
import os
import diagrams.programming.flowchart as fc
from diagrams import Diagram, Cluster, Edge

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)

FONT = "DejaVu Sans"
ACCENT = "#1F4E79"

GRAPH = {
    "fontname": FONT, "bgcolor": "white", "fontsize": "18",
    "labelloc": "t", "pad": "1.0", "nodesep": "0.5", "ranksep": "0.5",
}
NODE = {"fontname": FONT, "fontsize": "13"}
EDGE = {"fontname": FONT, "fontsize": "11", "color": "#666666"}
CLU = {"fontname": FONT, "fontsize": "15", "bgcolor": "#F4F7FB",
       "pencolor": ACCENT, "style": "rounded", "penwidth": "1.2"}


def d(name, title, **kw):
    g = dict(GRAPH)
    g.update(kw.pop("graph_attr", {}))
    return Diagram(title, filename=os.path.join(OUT, name), outformat="png",
                   show=False, direction="TB", graph_attr=g, node_attr=NODE, edge_attr=EDGE, **kw)


# ── H4a. Intake → Tech stack → Blueprint (GATE 1-2) ─────────────────────────
with d("h4a_intake_blueprint", "Hình 4a — Intake → Tech stack → Blueprint (GATE 1-2)"):
    start = fc.StartEnd("Bắt đầu phiên")
    up = fc.Document("Tải tài liệu yêu cầu\n(PDF / DOCX / MD / TXT)")
    an = fc.Action("analyze_architecture_requirements")
    brief = fc.Action("propose_diagram_brief")
    res = fc.Action("web_research (Tavily)\n≤10 truy vấn/phiên, chia theo chủ đề")
    g1 = fc.Decision("GATE 1\npropose_tech_stack")
    bp = fc.Action("propose_blueprint\n+ render_spec.json")
    g2 = fc.Decision("GATE 2\npropose_blueprint")
    nxt = fc.StartEnd("→ Hình 4b (vẽ diagram)")

    start >> up >> an >> brief >> res >> g1
    g1 >> Edge(label="approve", color=ACCENT) >> bp >> g2
    g1 >> Edge(label="reject / request_alternative", style="dashed") >> brief
    g2 >> Edge(label="reject / request_evidence", style="dashed") >> bp
    g2 >> Edge(label="approve", color=ACCENT) >> nxt


# ── H4b. Vòng vẽ diagram: icon_resolver → drawer → engineer loop → critic → GATE 3
with d("h4b_draw_loop", "Hình 4b — Vòng vẽ diagram và engineer loop (GATE 3)"):
    prev = fc.StartEnd("← từ Hình 4a\n(blueprint đã duyệt)")
    icon = fc.PredefinedProcess("subagent: icon_resolver\n→ icon_plan.json")
    draw = fc.PredefinedProcess("subagent: drawer\n→ out.drawio, out.png")
    tier0 = fc.Action("Tier 0 — repair.py\n6 phương án, 0 token")
    tier12 = fc.Action("Tier 1-2 — edit_drawio ⇄\ninspect_render_quality (≤2 vòng,\nauto-revert nếu tụt >1 điểm)")
    crit = fc.PredefinedProcess("subagent: critic\n→ critique.json")
    verdict = fc.Decision("PASS / REVISE")
    g3 = fc.Decision("GATE 3\nfinalize_diagram")
    nxt = fc.StartEnd("→ Hình 4c (deliverable)")

    prev >> icon >> draw >> tier0 >> tier12 >> crit >> verdict
    verdict >> Edge(label="REVISE (≤2 lần — DrawerReviseGate)", style="dashed") >> draw
    verdict >> Edge(label="PASS", color=ACCENT) >> g3
    g3 >> Edge(label="reject", style="dashed") >> draw
    g3 >> Edge(label="approve", color=ACCENT) >> nxt


# ── H4c. Chuỗi deliverable & bàn giao (GATE 4-13 + slot_picker) ─────────────
with d("h4c_deliverable_handover", "Hình 4c — Chuỗi deliverable và bàn giao (GATE 4-13)",
       graph_attr={"ranksep": "0.4"}):
    prev = fc.StartEnd("← từ Hình 4b\n(diagram đã chốt)")

    with Cluster("Báo cáo & đề xuất", graph_attr=CLU):
        g4 = fc.Decision("GATE 4\ngenerate_pdf_report")
        g5 = fc.Decision("GATE 8\npropose_deck_plan*")
        g6 = fc.Decision("GATE 9\ngenerate_ppt_proposal")
        g4 >> g5 >> g6
    with Cluster("WBS", graph_attr=CLU):
        g7 = fc.Decision("GATE 5\npropose_wbs_skeleton")
        g8 = fc.Decision("GATE 6\npropose_wbs")
        g9 = fc.Decision("GATE 7\nexport_wbs_excel")
        g7 >> g8 >> g9
    with Cluster("Business case (mới)", graph_attr=CLU):
        g10 = fc.Decision("GATE 13\npropose_business_case")
    with Cluster("Bàn giao", graph_attr=CLU):
        g11 = fc.Decision("GATE 10\nsend_email")
        slot = fc.ManualInput("propose_meeting_slots\n(interrupt riêng — card slot_picker)")
        g12 = fc.Decision("GATE 11\ncreate_client_meeting")
        g13 = fc.Decision("GATE 12\nexport_to_delivery\n(dry_run mặc định)")
        g11 >> slot >> g12 >> g13
    endd = fc.StartEnd("Kết thúc phiên")

    prev >> g4
    g6 >> g7
    g9 >> g10
    g10 >> g11
    g13 >> endd