# -*- coding: utf-8 -*-
"""Toàn bộ nội dung BRD cho dự án Diagram Code Agent.

Mỗi khoá là một `section_id` trong bản đồ anchor của template; giá trị là danh
sách block. Cấu trúc này chính là payload mà tool `edit_brd_section` của agent
sẽ nhận — nên nội dung và cơ chế ghi hoàn toàn tách rời nhau.
"""
FIG = "figs/"

P = lambda t, **kw: {"type": "p", "text": t, **kw}
B = lambda t: {"type": "bullet", "text": t}
CAP = lambda t: {"type": "caption", "text": t}
IMG = lambda f, w=6.1: {"type": "image", "path": FIG + f, "width": w}
T = lambda rows, **kw: {"type": "table", "rows": rows, **kw}
H = lambda t, lv: {"type": "heading", "text": t, "level": lv}

PROJECT = "Diagram Code Agent — Nền tảng AI Agent sinh tài liệu thiết kế & bàn giao dự án"
VERSION = "Version 1.1.0"
AUTHOR = "Huy Mai — Business Analyst / AI Engineer"
DATE = "29/07/2026"

# ══════════════════════════ 1. INTRODUCTION ══════════════════════════════
SECTIONS = {}

SECTIONS["purpose"] = [
    P("Tài liệu này đặc tả yêu cầu nghiệp vụ (Business Requirements Document — BRD) cho "
      "hệ thống Diagram Code Agent: một nền tảng AI Agent tự động hoá công đoạn tiền dự án "
      "(pre-sales và khởi tạo dự án) của một công ty phần mềm — vốn đang được thực hiện "
      "hoàn toàn thủ công bởi đội Business Analyst (BA), Solution Architect (SA) và "
      "Project Manager (PM)."),
    P("Mục tiêu nghiệp vụ của hệ thống:"),
    B("Rút ngắn thời gian từ « yêu cầu thô của khách hàng » tới « bộ hồ sơ giải pháp hoàn "
      "chỉnh » từ 5–10 ngày công xuống dưới 1 ngày công."),
    B("Chuẩn hoá đầu ra: mọi hồ sơ (diagram kiến trúc, báo cáo PDF, đề xuất PowerPoint, "
      "WBS Excel, tài liệu BRD Word) đều sinh từ một mô hình dữ liệu chung, bảo đảm nhất "
      "quán số liệu và thuật ngữ giữa các tài liệu."),
    B("Giữ con người ở vị trí quyết định (Human-in-the-loop — HITL): mọi quyết định có ảnh "
      "hưởng tới chi phí, kiến trúc hoặc cam kết với khách hàng đều phải được người có thẩm "
      "quyền phê duyệt trước khi agent đi tiếp."),
    B("Bảo đảm khả năng truy vết (traceability): mỗi phát biểu trong tài liệu bàn giao đều "
      "quy chiếu ngược được về yêu cầu gốc, bằng chứng và quyết định thiết kế đã ghi nhận."),
    P("Phạm vi của bản BRD này bao gồm (a) toàn bộ năng lực hiện có của hệ thống và "
      "(b) module BRD Agent — luồng sinh và chỉnh sửa tài liệu BRD dạng .docx — là hạng mục "
      "phát triển mới được đề xuất trong giai đoạn tiếp theo."),
]

SECTIONS["intended-audience"] = [
    P("Tài liệu hướng tới các nhóm đối tượng sau:"),
    T([
        ["Audience", "Representative", "Mối quan tâm chính"],
        ["Ban lãnh đạo / Sponsor", "Giám đốc khối Giải pháp",
         "Giá trị nghiệp vụ, chi phí, mức độ rủi ro khi đưa AI vào quy trình bán hàng"],
        ["Business Analyst", "Trưởng nhóm BA",
         "Chất lượng tài liệu đầu ra, khả năng chỉnh sửa và kiểm soát nội dung"],
        ["Solution Architect", "Kiến trúc sư trưởng",
         "Độ chính xác của blueprint, tech stack, diagram và các ràng buộc phi chức năng"],
        ["Project Manager", "PM phụ trách delivery",
         "Độ tin cậy của WBS, ước lượng effort, kế hoạch tiến độ và đồng bộ Jira"],
        ["Đội phát triển", "Tech Lead, Fullstack, AI Engineer",
         "Đặc tả chức năng, hợp đồng API, mô hình dữ liệu, tiêu chí nghiệm thu"],
        ["Đội QA", "QC Lead",
         "Tiêu chí chấp nhận, bộ eval hồi quy, kịch bản kiểm thử luồng HITL"],
    ], widths=[1.6, 1.9, 2.9]),
]

SECTIONS["intended-use"] = [
    P("BRD — Business Requirements Document — được sử dụng để mô tả yêu cầu nghiệp vụ, "
      "phạm vi, các chức năng và yêu cầu phi chức năng của hệ thống ở mức đủ chi tiết để "
      "(1) ban lãnh đạo phê duyệt đầu tư, (2) đội phát triển bóc tách thành backlog kỹ thuật "
      "và (3) đội QA xây dựng bộ tiêu chí nghiệm thu."),
    P("Tài liệu này KHÔNG thay thế cho: đặc tả kỹ thuật chi tiết từng API (SDD), tài liệu "
      "vận hành (Runbook), hay hợp đồng thương mại. Các tài liệu đó được tham chiếu ở "
      "Appendix A."),
]

SECTIONS["scope"] = [
    P("Trong phạm vi (In scope)", bold=True),
    B("Tiếp nhận yêu cầu dạng văn bản tự do hoặc tài liệu đính kèm (PDF, DOCX, MD, TXT) và "
      "chuyển hoá thành mô hình yêu cầu có cấu trúc."),
    B("Đề xuất technology stack và blueprint kiến trúc, có đối chiếu thông tin thị trường "
      "qua công cụ tìm kiếm web trực tuyến."),
    B("Sinh diagram kiến trúc dưới dạng mã nguồn (diagrams-as-code), kết xuất PNG và tệp "
      ".drawio chỉnh sửa được."),
    B("Sinh bộ tài liệu bàn giao: báo cáo PDF, đề xuất PowerPoint, WBS Excel có công thức "
      "sống, gói ADR và — theo đề xuất mới — tài liệu BRD dạng .docx."),
    B("Cho phép chỉnh sửa gia tăng (incremental edit) trên từng phần của tài liệu đầu ra mà "
      "không sinh lại toàn bộ."),
    B("Bàn giao: gửi email kèm tệp, đặt lịch họp khách hàng, đồng bộ WBS sang Jira/Linear."),
    B("Quản trị: nhật ký bằng chứng, nhật ký quyết định, danh sách phát hiện (findings), "
      "bình luận theo thực thể và ảnh chụp phiên bản đã phê duyệt."),
    P(""),
    P("Ngoài phạm vi (Out of scope)", bold=True),
    B("Sinh mã nguồn ứng dụng cho khách hàng; hệ thống chỉ sinh tài liệu và bản vẽ."),
    B("Quản lý hợp đồng, báo giá pháp lý và quy trình ký số."),
    B("Thay thế vai trò phê duyệt của con người — hệ thống luôn dừng tại các cổng HITL."),
    B("Huấn luyện hoặc tinh chỉnh (fine-tune) mô hình ngôn ngữ riêng; hệ thống sử dụng "
      "mô hình của nhà cung cấp qua API."),
    P(""),
    IMG("h1_context.png", 6.0),
    CAP("Hình 1 — Sơ đồ ngữ cảnh hệ thống (System Context Diagram)"),
]

SECTIONS["abbreviations-and-acronyms"] = [
    T([
        ["Abbreviations", "Describe"],
        ["BRD", "Business Requirements Document — tài liệu đặc tả yêu cầu nghiệp vụ"],
        ["WBS", "Work Breakdown Structure — cấu trúc phân rã công việc"],
        ["HITL", "Human-in-the-loop — cơ chế dừng chờ con người phê duyệt"],
        ["CSM", "Canonical Solution Model — mô hình giải pháp chuẩn hoá dùng chung"],
        ["LLM", "Large Language Model — mô hình ngôn ngữ lớn"],
        ["RAG", "Retrieval-Augmented Generation — sinh nội dung có truy hồi tri thức"],
        ["SSE", "Server-Sent Events — kênh truyền sự kiện một chiều từ server"],
        ["AG-UI", "Agent-User Interaction protocol — giao thức sự kiện giữa agent và giao diện"],
        ["ADR", "Architecture Decision Record — biên bản quyết định kiến trúc"],
        ["NFR", "Non-Functional Requirement — yêu cầu phi chức năng"],
        ["WAF", "Well-Architected Framework — khung đánh giá kiến trúc tốt"],
        ["OOXML", "Office Open XML — chuẩn định dạng của tệp .docx/.xlsx/.pptx"],
        ["SA / BA / PM", "Solution Architect / Business Analyst / Project Manager"],
        ["N/A", "Not applicable — không áp dụng"],
    ], widths=[1.3, 5.1]),
    P("Quy ước ký hiệu trong các flowchart của tài liệu: hình thoi = cổng phê duyệt HITL; "
      "hình chữ nhật = hành động do agent thực hiện; hình chữ nhật kép = tiến trình con "
      "(subagent); hình bình hành = dữ liệu vào/ra; đường nét đứt = luồng quay lui khi bị "
      "từ chối.", italic=True),
]

SECTIONS["document-conventions"] = [
    T([
        ["Categories", "Conventions"],
        ["Casual text", "Tahoma 11px"],
        ["Section titles", "Tahoma 14px"],
        ["Subsection titles", "Tahoma 11px bold"],
        ["Text in table", "Tahoma 9px"],
        ["Section/subsection number", "X.X.X (đánh số tự động theo style Heading)"],
        ["Mã yêu cầu chức năng", "FRxx — ví dụ FR01, FR02"],
        ["Mã yêu cầu phi chức năng", "NFR-<nhóm>-xx — ví dụ NFR-PERF-01"],
        ["Tên tool của agent", "chữ thường, nối bằng gạch dưới — ví dụ propose_blueprint"],
    ], widths=[2.2, 4.2]),
]

# ══════════════════════════ 2. GENERAL DESCRIPTION ═══════════════════════
SECTIONS["user-needs"] = [
    P("Hệ thống phục vụ bốn nhóm người dùng chính, tương ứng bốn nhu cầu nghiệp vụ khác nhau:"),
    T([
        ["No.", "NAME", "Type of user", "Description"],
        ["1", "Business Analyst", "Primary",
         "Tự động hoá việc soạn BRD/SRS từ yêu cầu thô; chỉnh sửa từng mục tài liệu theo "
         "phản hồi khách hàng mà không phải viết lại toàn bộ"],
        ["2", "Solution Architect", "Primary",
         "Tự động sinh blueprint kiến trúc và diagram đạt chuẩn trình bày; kiểm tra tính "
         "nhất quán giữa yêu cầu — thiết kế — bản vẽ"],
        ["3", "Project Manager", "Primary",
         "Tự động phân rã WBS, ước lượng effort theo định mức công ty và kết xuất Excel "
         "kế hoạch có công thức sống"],
        ["4", "Pre-sales / Account", "Secondary",
         "Tự động sinh bộ đề xuất (PDF + PPTX), gửi email và đặt lịch họp với khách hàng"],
        ["5", "Tech Lead / Dev", "Secondary",
         "Nhận đặc tả có truy vết và WBS đã được đồng bộ sang Jira để bắt đầu triển khai"],
        ["6", "QC Lead", "Secondary",
         "Nhận tiêu chí nghiệm thu và bộ eval hồi quy để kiểm soát chất lượng đầu ra của agent"],
    ], widths=[0.5, 1.5, 1.1, 3.3]),
]

SECTIONS["assumptions-and-dependencies"] = [
    T([
        ["No.", "Assumptions", "Dependencies"],
        ["1", "Yêu cầu đầu vào của khách hàng được cung cấp bằng văn bản (chat hoặc tệp) và "
              "đủ thông tin để xác định loại hệ thống, quy mô, ràng buộc",
         "Chất lượng đầu ra tỉ lệ thuận với chất lượng đầu vào; agent sẽ đặt câu hỏi làm rõ "
         "khi thiếu thông tin trọng yếu"],
        ["2", "Bộ diagram kiến trúc được sinh tự động từ blueprint đã phê duyệt và đạt chuẩn "
              "trình bày để đưa thẳng vào tài liệu khách hàng",
         "Phụ thuộc Graphviz và thư viện diagrams; giảm 80% thời gian vẽ thủ công của SA"],
        ["3", "Tài liệu BRD được sinh tự động từ template chuẩn của công ty và chỉnh sửa "
              "được theo từng mục",
         "Phụ thuộc tính ổn định của template .docx; giảm sai sót định dạng và thời gian "
         "soạn thảo của BA"],
        ["4", "WBS và ước lượng effort được sinh theo định mức nội bộ, có công thức sống "
              "trong Excel để PM tinh chỉnh",
         "Phụ thuộc bảng định mức (master data) do PM duy trì; giảm rủi ro ước lượng lệch"],
        ["5", "Mọi quyết định trọng yếu đều dừng chờ người phê duyệt tại các cổng HITL",
         "Giảm rủi ro agent tự ý cam kết sai với khách hàng; đổi lại thời gian chờ phụ thuộc "
         "tốc độ phản hồi của người duyệt"],
        ["6", "Hệ thống có kết nối Internet tới nhà cung cấp LLM, dịch vụ tìm kiếm và "
              "Composio (Gmail/Calendar)",
         "Phụ thuộc hạn mức API và tình trạng dịch vụ bên thứ ba; cần cơ chế fallback model"],
        ["7", "Dữ liệu phiên làm việc được lưu trên PostgreSQL nội bộ của công ty",
         "Phụ thuộc hạ tầng Docker/PostgreSQL; bảo đảm dữ liệu khách hàng không rời khỏi "
         "vùng kiểm soát ngoài phần gửi tới LLM"],
    ], widths=[0.4, 3.0, 3.0]),
]

# ══════════════════════════ 3. FUNCTIONAL REQUIREMENTS ═══════════════════
FR_LIST = [
    ("FR01", "Tiếp nhận và phân tích yêu cầu", "1a",
     "Nhận yêu cầu dạng chat hoặc tệp đính kèm, bóc tách thành mô hình yêu cầu có cấu trúc "
     "và đề xuất diagram brief"),
    ("FR02", "Đề xuất technology stack", "2a",
     "Đối chiếu thông tin thị trường qua web research (ngân sách 10 truy vấn/phiên, chia theo "
     "chủ đề) rồi đề xuất tech stack; dừng chờ phê duyệt"),
    ("FR03", "Đề xuất blueprint kiến trúc", "3a",
     "Sinh blueprint gồm component, cluster, luồng dữ liệu, đối chiếu WAF; dừng chờ phê duyệt"),
    ("FR04", "Sinh và kết xuất diagram", "4a",
     "Phân giải icon, sinh mã diagrams-as-code, render PNG, kết xuất .drawio và tự phê bình "
     "chất lượng bản vẽ"),
    ("FR05", "Chỉnh sửa diagram tại chỗ", "4b",
     "Đọc bản kiểm kê phần tử của .drawio và vá đúng phần tử được yêu cầu, không vẽ lại toàn bộ"),
    ("FR06", "Lập kế hoạch WBS và kết xuất Excel", "5a",
     "Phân rã công việc theo phase/module, ước lượng effort theo định mức, kết xuất workbook "
     "có công thức sống"),
    ("FR07", "Sinh báo cáo PDF và đề xuất PowerPoint", "6a",
     "Tổng hợp artifact đã phê duyệt thành báo cáo PDF và bộ slide đề xuất theo nhận diện "
     "thương hiệu"),
    ("FR08", "Sinh tài liệu BRD (.docx) từ template", "7a",
     "MỚI — Lập dàn ý BRD, soạn nội dung từng mục và điền vào template .docx chuẩn của công ty"),
    ("FR09", "Chỉnh sửa BRD theo từng section", "7b",
     "MỚI — Vá đúng một mục của tệp .docx theo phản hồi người dùng, giữ nguyên phần còn lại "
     "và tăng số hiệu phiên bản"),
    ("FR10", "Quản trị và truy vết giải pháp", "8a",
     "Duy trì mô hình CSM, nhật ký bằng chứng/quyết định/phát hiện, bình luận và ảnh chụp "
     "phiên bản đã phê duyệt"),
    ("FR11", "Bàn giao kết quả", "9a",
     "Gửi email kèm tệp, đề xuất và đặt lịch họp khách hàng (hai cổng riêng: chọn khung giờ rồi "
     "xác nhận cuộc họp), đồng bộ WBS sang Jira/Linear"),
    ("FR12", "Quản lý phiên và khôi phục hội thoại", "10a",
     "Lưu, liệt kê, đổi tên, xoá và khôi phục phiên làm việc kèm toàn bộ artifact"),
    ("FR13", "Phân tích business case (ROI/TCO)", "9b",
     "MỚI — Tính chi phí triển khai, chi phí vận hành hàng năm, lợi ích quy đổi, ROI/TCO/thời "
     "gian hoàn vốn; dừng chờ phê duyệt"),
    ("FR14", "Sinh diagram có kiểu (sequence/ERD/state machine)", "4c",
     "MỚI — Sinh sequence diagram, ERD và state machine dạng mã nguồn, kiểm tra cấu trúc tất "
     "định (dangling ref, PK thiếu, state không tới được) trước khi kết xuất"),
]

SECTIONS["functional-requirements-list"] = [
    P("Bảng dưới đây liệt kê toàn bộ yêu cầu chức năng của hệ thống. Các mục đánh dấu MỚI "
      "thuộc phạm vi phát triển của giai đoạn tiếp theo (module BRD Agent và module Business "
      "Case). Bản 1.1 sửa số cổng phê duyệt (13, không phải 12 như bản 1.0) và bổ sung FR13, "
      "FR14 cho hai năng lực đã có trong mã nguồn nhưng bản 1.0 chưa mô tả."),
    T([["ID", "NAME", "Step", "Description"]] +
      [[a, b, c, d] for a, b, c, d in FR_LIST], widths=[0.6, 1.7, 0.5, 3.6]),
    P(""),
    P("Luồng nghiệp vụ end-to-end được tách thành ba hình theo giai đoạn — một hình dồn cả "
      "13 cổng vào một trang (như bản 1.0) không đọc được:"),
    IMG("h4a_intake_blueprint.png", 3.0),
    CAP("Hình 4a — Intake → Tech stack → Blueprint (GATE 1-2)"),
    P(""),
    IMG("h4b_draw_loop.png", 3.2),
    CAP("Hình 4b — Vòng vẽ diagram và engineer loop (GATE 3)"),
    P(""),
    IMG("h4c_deliverable_handover.png", 3.6),
    CAP("Hình 4c — Chuỗi deliverable và bàn giao (GATE 4-13). Cổng GATE 8 (propose_deck_plan) "
        "đánh dấu * vì hiện chưa có thẻ giao diện riêng (ISS-06) — rơi vào thẻ mặc định."),
    P(""),
    IMG("h5_artifacts.png", 5.6),
    CAP("Hình 5 — Vòng đời artifact trong workspace theo từng phase (đã bổ sung 15 file thật "
        "bị bỏ sót ở bản 1.0 — xem Bảng 3.15.4)"),
    P(""),
    P("Cơ chế cổng phê duyệt (HITL) dùng chung cho cả 13 cổng — xem trình tự interrupt → card "
      "→ resume và vòng đời trạng thái của một cổng:"),
    IMG("s2_gate_lifecycle.png", 6.0),
    CAP("Hình S2 — Trình tự cổng HITL: interrupt → card → resume"),
    P(""),
    IMG("st1_gate_lifecycle.png", 5.4),
    CAP("Hình ST1 — Vòng đời trạng thái của một cổng HITL"),
]


def fr(code, name, desc_blocks, ui_blocks, data_blocks):
    """Sinh đủ 3 tiểu mục Description / Interface requirements / Data requirements."""
    out = [H(f"{code} – {name}", 2)]
    out += [H("Description", 3)] + desc_blocks
    out += [H("Interface requirements", 3)] + ui_blocks
    out += [H("Data requirements", 3)] + data_blocks
    return out


FR_BLOCKS = []

FR_BLOCKS += fr(
    "FR01", "Tiếp nhận và phân tích yêu cầu",
    [
        P("Người dùng nhập yêu cầu dạng văn bản tự do hoặc tải lên tệp (PDF, DOCX, MD, TXT). "
          "Hệ thống bóc tách nội dung, lưu vào vùng làm việc của phiên và gọi công cụ phân "
          "tích tất định để suy ra: loại ứng dụng, quy mô dự kiến, mức độ yêu cầu bảo mật, "
          "nhà cung cấp hạ tầng gợi ý và các mẫu kiến trúc phù hợp."),
        P("Sau đó agent lập diagram brief gồm mục tiêu, các bên liên quan, danh sách yêu cầu "
          "chức năng và phi chức năng, ràng buộc. Brief này là đầu vào bắt buộc cho toàn bộ "
          "các bước sau."),
        P("Luồng dữ liệu: tệp tải lên được ghi vào agent_space/uploads/{file_id}.md; kết quả "
          "phân tích ghi vào architecture_analysis.json và diagram_brief.json trong workspace "
          "của thread."),
    ],
    [P("Khung chat có nút đính kèm tệp; hiển thị tên tệp, số ký tự đã bóc tách và đoạn xem "
       "trước. Thẻ « Diagram Brief » hiển thị mục tiêu, stakeholder, FR/NFR, ràng buộc.")],
    [T([
        ["Fields", "Type", "Char", "Default", "Req", "Note"],
        ["file_id", "UUID", "36", "", "x", "Sinh tự động khi tải tệp"],
        ["filename", "Varchar", "255", "", "x", "Tên gốc của tệp"],
        ["kind", "Enum", "", "text", "x", "text | image"],
        ["char_count", "Int", "10", "0", "", "Số ký tự bóc tách được"],
        ["objective", "Text", "", "", "x", "Mục tiêu hệ thống, ghi vào diagram_brief.json"],
        ["stakeholders", "Array", "", "[]", "x", "Danh sách các bên liên quan"],
        ["requirements", "Array", "", "[]", "x", "Mỗi phần tử là một yêu cầu, gán mã REQ-xx"],
        ["constraints", "Array", "", "[]", "", "Ràng buộc kỹ thuật, ngân sách, thời gian"],
    ], widths=[1.2, 0.8, 0.5, 0.7, 0.4, 2.8])],
)

FR_BLOCKS += fr(
    "FR02", "Đề xuất technology stack",
    [
        P("Trước khi đề xuất, agent được phép thực hiện tìm kiếm web trực tuyến trong một "
          "phiên nhằm xác thực giá dịch vụ, phiên bản hiện hành và kiến trúc tham chiếu. Ngân "
          "sách là CỨNG và chia theo chủ đề: tối đa 10 truy vấn/phiên, trong đó tech stack ≤4, "
          "kiến trúc/blueprint ≤2, WBS ≤1, bằng chứng ≤2, việc khác ≤1. Đây là con số đã kiểm "
          "chứng trong mã nguồn (WEB_SEARCH_SESSION_CAP) — bản 1.0 ghi nhầm là 3."),
        P("Kết quả là một tech stack phân theo lớp (frontend, backend, dữ liệu, hạ tầng, "
          "AI/ML, tích hợp), mỗi lựa chọn kèm lý do và nguồn tham chiếu."),
        P("Đây là CỔNG PHÊ DUYỆT THỨ NHẤT: hệ thống dừng, phát thẻ phê duyệt lên giao diện "
          "và chờ quyết định của người dùng. Các quyết định hợp lệ: approve, "
          "approve_with_assumptions, accept_risk, reject, request_evidence, request_alternative."),
    ],
    [P("Thẻ « Technology Stack » dạng bảng theo lớp, mỗi dòng có tên công nghệ, phiên bản, "
       "lý do lựa chọn và liên kết nguồn. Cụm nút quyết định hiển thị đúng các hành động mà "
       "vai trò đang đăng nhập được phép thực hiện.")],
    [T([
        ["Fields", "Type", "Char", "Default", "Req", "Note"],
        ["layer", "Varchar", "50", "", "x", "frontend | backend | data | infra | ai | integration"],
        ["technology", "Varchar", "100", "", "x", "Tên công nghệ"],
        ["version", "Varchar", "30", "", "", "Phiên bản khuyến nghị"],
        ["rationale", "Text", "", "", "x", "Lý do lựa chọn"],
        ["evidence_id", "Varchar", "20", "", "", "Trỏ tới EVD-xx trong evidence_log.json"],
        ["decision", "Enum", "", "", "x", "Ghi vào decision_log.json khi người dùng phê duyệt"],
    ], widths=[1.2, 0.8, 0.5, 0.7, 0.4, 2.8])],
)

FR_BLOCKS += fr(
    "FR03", "Đề xuất blueprint kiến trúc",
    [
        P("Agent sinh blueprint gồm danh sách component, cách nhóm thành cluster, các cạnh "
          "biểu diễn luồng dữ liệu kèm nhãn mối quan tâm, và phần đối chiếu với khung "
          "Well-Architected. Hệ thống tự kiểm tra độ phủ: mỗi yêu cầu trong brief phải được "
          "ít nhất một component đáp ứng, nếu không sẽ cảnh báo thiếu độ phủ."),
        P("Blueprint được chuyển thành render_spec.json — đặc tả trung gian tất định dùng "
          "cho cả bước vẽ bằng Graphviz lẫn bước kết xuất .drawio gốc."),
        P("Đây là CỔNG PHÊ DUYỆT THỨ HAI."),
    ],
    [P("Thẻ « Architecture Blueprint » hiển thị cây component theo cluster, danh sách cạnh, "
       "bảng đối chiếu WAF và chỉ số độ phủ yêu cầu (%). Người dùng có thể bình luận neo "
       "vào từng component trước khi quyết định.")],
    [T([
        ["Fields", "Type", "Char", "Default", "Req", "Note"],
        ["component_id", "Varchar", "20", "", "x", "COMP-xx, ổn định qua các phiên bản"],
        ["name", "Varchar", "100", "", "x", "Tên hiển thị trên bản vẽ"],
        ["cluster", "Varchar", "100", "", "", "Nhóm chứa component"],
        ["satisfies", "Array", "", "[]", "x", "Danh sách REQ-xx mà component đáp ứng"],
        ["edges", "Array", "", "[]", "x", "{from, to, label, protocol}"],
        ["waf_pillar", "Varchar", "50", "", "", "Trụ cột WAF liên quan"],
    ], widths=[1.2, 0.8, 0.5, 0.7, 0.4, 2.8])],
)

FR_BLOCKS += fr(
    "FR04", "Sinh và kết xuất diagram",
    [
        P("Bước vẽ được giao cho hai tiến trình con chuyên trách. Tiến trình icon_resolver "
          "đọc render_spec.json và phân giải hàng loạt lớp node cùng đường dẫn icon từ bốn "
          "nguồn theo thứ tự ưu tiên: thư viện diagrams có sẵn, bộ icon nội bộ, dịch vụ "
          "Iconify và favicon của nhà cung cấp."),
        P("Tiến trình drawer sinh mã Python theo phong cách diagrams-as-code, chạy trong môi "
          "trường cách ly có kiểm tra tĩnh trước khi thực thi, render ra PNG và DOT, rồi kết "
          "xuất .drawio."),
        P("Vòng tinh chỉnh chất lượng gồm BA TẦNG, không phải một vòng critic đơn như bản 1.0 "
          "mô tả. Tầng 0 — sửa tất định, không tốn token: dựng tối đa 6 phương án bố cục và "
          "chọn phương án điểm cao nhất. Tầng 1-2 — vòng LLM có giới hạn: tối đa 2 lượt "
          "edit_drawio ⇄ inspect_render_quality, TỰ ĐỘNG HOÀN TÁC nếu điểm tụt quá 1 so với "
          "bản trước (đo thực tế trên một phiên đầy đủ: 9 lượt sửa, 7 lượt bị hoàn tác, không "
          "lượt nào đạt ngưỡng PASS — xem Hình ST3). Ngân sách chỉ được cấp lại khi người dùng "
          "thật sự từ chối ở cổng phê duyệt (trần cứng 2 lần)."),
        P("Tiến trình critic xem lại ảnh PNG đối chiếu blueprint và trả về phán quyết "
          "PASS hoặc REVISE kèm danh sách lỗi trình bày cụ thể. Khi PASS, agent mở "
          "CỔNG PHÊ DUYỆT THỨ BA để người dùng chốt bản vẽ."),
        P(""),
        IMG("s3_subagent_engineer_loop.png", 6.0),
        CAP("Hình S3 — Uỷ nhiệm subagent và engineer loop ba tầng"),
        P(""),
        IMG("st3_diagram_quality_loop.png", 5.4),
        CAP("Hình ST3 — Vòng chất lượng diagram (rendered → scored → kept/reverted → finalized)"),
    ],
    [P("Khung canvas hiển thị ảnh PNG với các tab: xem trước, mã nguồn diagram.py, nhật ký "
       "hoạt động của tiến trình con và bảng điểm chất lượng. Nút tải về cho PNG và .drawio.")],
    [T([
        ["Fields", "Type", "Char", "Default", "Req", "Note"],
        ["node_key", "Varchar", "80", "", "x", "Khoá node trong render_spec"],
        ["node_class", "Varchar", "120", "", "x", "Lớp của thư viện diagrams"],
        ["icon_path", "Varchar", "255", "", "", "Đường dẫn icon; NOT_FOUND nếu chưa phân giải được"],
        ["source", "Enum", "", "diagrams", "x", "diagrams | local | iconify | favicon"],
        ["verdict", "Enum", "", "", "x", "PASS | REVISE — kết quả của critic"],
        ["findings", "Array", "", "[]", "", "Danh sách lỗi trình bày kèm mức nghiêm trọng"],
    ], widths=[1.2, 0.8, 0.5, 0.7, 0.4, 2.8])],
)

FR_BLOCKS += fr(
    "FR05", "Chỉnh sửa diagram tại chỗ",
    [
        P("Khi người dùng yêu cầu sửa một chi tiết trên bản vẽ, hệ thống KHÔNG vẽ lại toàn "
          "bộ. Agent đọc bản kiểm kê rút gọn của tệp .drawio — mỗi phần tử một dòng gồm id, "
          "loại, nhãn và style — xác định đúng phần tử cần sửa, áp dụng thao tác vá, sau đó "
          "tự động chạy lại bộ kiểm tra cấu trúc và render lại ảnh xem trước."),
        P("Nguyên tắc này là tiền lệ trực tiếp cho cơ chế chỉnh sửa .docx theo từng section "
          "mô tả tại FR09."),
    ],
    [P("Ô chat cho phép câu lệnh tự nhiên như « đổi nhãn node API Gateway thành API Gateway "
       "(Kong) »; giao diện hiển thị khác biệt trước–sau và cho phép hoàn tác về phiên bản "
       "gần nhất.")],
    [T([
        ["Fields", "Type", "Char", "Default", "Req", "Note"],
        ["cell_id", "Varchar", "40", "", "x", "Định danh phần tử trong tệp .drawio"],
        ["operation", "Enum", "", "", "x", "set_label | set_style | move | delete | add_edge"],
        ["payload", "JSON", "", "{}", "x", "Tham số của thao tác"],
        ["revalidated", "Boolean", "", "true", "x", "Đã chạy lại linter sau khi vá"],
    ], widths=[1.2, 0.8, 0.5, 0.7, 0.4, 2.8])],
)

FR_BLOCKS += fr(
    "FR06", "Lập kế hoạch WBS và kết xuất Excel",
    [
        P("Tiến trình wbs_planner đọc ngữ cảnh giải pháp đã phê duyệt, dựng khung WBS ba "
          "giai đoạn, bổ sung hạng mục công việc theo module, rồi ước lượng effort. Chỉ "
          "effort của lập trình viên được ước lượng trực tiếp; effort của BA, QC và PM được "
          "suy ra theo tỉ lệ định mức của công ty."),
        P("Hệ thống mở lần lượt ba cổng phê duyệt: khung WBS, bản WBS đầy đủ có ước lượng, "
          "và việc kết xuất tệp Excel."),
        P("Workbook kết xuất giữ nguyên công thức sống: PM mở tệp và sửa một ô định mức thì "
          "toàn bộ effort, tiến độ và biểu đồ Gantt tự tính lại."),
    ],
    [P("Thẻ phê duyệt WBS hiển thị bảng phase–module–task với cột effort, đường găng và tổng "
       "hợp theo vai trò. Tab « WBS » trên canvas cho phép tải tệp wbs_filled.xlsx.")],
    [T([
        ["Fields", "Type", "Char", "Default", "Req", "Note"],
        ["wbs_id", "Varchar", "20", "", "x", "WBS-xx"],
        ["phase", "Varchar", "80", "", "x", "Giai đoạn"],
        ["module", "Varchar", "80", "", "x", "Module nghiệp vụ"],
        ["task", "Varchar", "200", "", "x", "Hạng mục công việc lá"],
        ["dev_effort_md", "Decimal", "8,2", "0", "x", "Man-day của lập trình viên"],
        ["ba_qc_pm_md", "Decimal", "8,2", "0", "", "Suy ra theo tỉ lệ trong sheet Master Data"],
        ["implements", "Varchar", "20", "", "", "Trỏ tới COMP-xx tương ứng"],
    ], widths=[1.2, 0.8, 0.5, 0.7, 0.4, 2.8])],
)

FR_BLOCKS += fr(
    "FR07", "Sinh báo cáo PDF và đề xuất PowerPoint",
    [
        P("Hệ thống tổng hợp toàn bộ artifact đã phê duyệt thành một cấu trúc dữ liệu báo "
          "cáo dùng chung, sau đó kết xuất song song hai định dạng: báo cáo HTML/PDF khổ A4 "
          "và bộ slide PowerPoint theo template thương hiệu của công ty."),
        P("Bộ slide được dựng từ storyboard đã phê duyệt, mỗi slide truy vết ngược về thực "
          "thể trong mô hình CSM. Sau khi dựng, hệ thống chạy một lượt kiểm tra trình bày "
          "tất định để phát hiện tràn chữ và tự động co giãn."),
    ],
    [P("Thẻ phê duyệt hiển thị danh sách mục sẽ đưa vào tài liệu, cho phép bỏ bớt mục kèm "
       "lý do. Tab « PDF » và « PPT » cho phép xem trước và tải về.")],
    [T([
        ["Fields", "Type", "Char", "Default", "Req", "Note"],
        ["title", "Varchar", "200", "", "x", "Tiêu đề tài liệu"],
        ["brand", "Varchar", "80", "", "", "Nhận diện thương hiệu áp dụng"],
        ["include_sections", "Array", "", "[]", "x", "Danh sách mục được đưa vào"],
        ["reason_for_subset", "Text", "", "", "", "Bắt buộc nếu chọn tập con các mục"],
        ["slide_traces", "Array", "", "[]", "", "SLIDE-xx → thực thể CSM tương ứng"],
    ], widths=[1.2, 0.8, 0.5, 0.7, 0.4, 2.8])],
)

FR_BLOCKS += fr(
    "FR08", "Sinh tài liệu BRD dạng .docx từ template  (MỚI)",
    [
        P("Đây là hạng mục phát triển mới. Hệ thống nhận template BRD chuẩn của công ty "
          "dưới dạng .docx, lập chỉ mục toàn bộ heading của template thành một bản đồ "
          "anchor, rồi soạn nội dung cho từng mục dựa trên ngữ cảnh đã phê duyệt: mô hình "
          "CSM, blueprint, tech stack, WBS và ảnh diagram."),
        P("Quy trình gồm bốn bước: (1) thu thập ngữ cảnh và soi cấu trúc template; "
          "(2) lập dàn ý BRD — ánh xạ mỗi section_id của template với nguồn dữ liệu và kiểu "
          "nội dung sẽ điền — và mở cổng phê duyệt dàn ý; (3) soạn nội dung từng mục; "
          "(4) điền vào template, nhúng diagram kèm chú thích, chạy bộ kiểm tra cấu trúc rồi "
          "mở cổng phê duyệt kết xuất."),
        P("Ràng buộc bắt buộc: quá trình điền KHÔNG được đụng tới styles.xml, numbering.xml, "
          "header/footer và trường mục lục của template — nhận diện thương hiệu và cách đánh "
          "số của công ty phải được giữ nguyên tuyệt đối."),
        P(""),
        IMG("h7_brd_agent.png", 5.4),
        CAP("Hình 7 — Kiến trúc luồng BRD Agent (module đề xuất)"),
    ],
    [P("Thẻ « BRD Outline » hiển thị cây mục của template kèm trạng thái mỗi mục (sẽ điền / "
       "giữ nguyên / bỏ qua) và nguồn dữ liệu tương ứng. Tab « BRD » trên canvas hiển thị "
       "bản xem trước theo mục và nút tải tệp out.brd.docx.")],
    [T([
        ["Fields", "Type", "Char", "Default", "Req", "Note"],
        ["section_id", "Varchar", "60", "", "x", "Khoá ổn định, sinh từ tiêu đề heading"],
        ["title", "Varchar", "200", "", "x", "Tiêu đề mục trong template"],
        ["level", "Int", "1", "1", "x", "Cấp heading 1–3"],
        ["source", "Enum", "", "", "x", "csm | blueprint | wbs | diagram | manual | template"],
        ["content_kind", "Enum", "", "p", "x", "p | bullet | table | image | caption"],
        ["status", "Enum", "", "fill", "x", "fill | keep | skip"],
        ["checksum", "Varchar", "16", "", "x", "SHA-256 rút gọn của thân mục, dùng khoá lạc quan"],
    ], widths=[1.2, 0.8, 0.5, 0.7, 0.4, 2.8])],
)

FR_BLOCKS += fr(
    "FR09", "Chỉnh sửa BRD theo từng section  (MỚI)",
    [
        P("Yêu cầu cốt lõi của module: khi người dùng nói « sửa mục 4.3 Security », hệ thống "
          "chỉ được vá đúng mục đó. Toàn bộ phần còn lại của tệp — kể cả các mục do người "
          "dùng tự sửa tay trước đó — phải giữ nguyên từng byte."),
        P("Cơ chế thực hiện gồm ba lớp. Lớp thứ nhất là bản đồ anchor: hệ thống duyệt thân "
          "tài liệu theo đúng thứ tự, xác định mỗi heading và vùng thân của nó tính đến "
          "heading kế tiếp có cấp bằng hoặc cao hơn, rồi tính checksum cho từng vùng."),
        P("Lớp thứ hai là tập thao tác vá: thay thân mục, chèn thêm block vào cuối mục, thêm "
          "mục mới sau một mục, xoá mục, và ghi lại dữ liệu một bảng theo chỉ số bảng trong "
          "mục. Mọi block mới đều mượn style có sẵn của template."),
        P("Lớp thứ ba là khoá lạc quan: mỗi lệnh vá phải kèm checksum mà bên gọi đã đọc. Nếu "
          "checksum hiện tại đã lệch — tức có người khác vừa sửa mục đó — lệnh vá bị từ chối "
          "và agent buộc phải lập chỉ mục lại trước khi thử lại."),
        P("Mỗi lần vá thành công tạo một bản ghi phiên bản trong brd_revisions/ kèm nhật ký "
          "thao tác, phục vụ so sánh khác biệt và hoàn tác."),
        P(""),
        IMG("s4_brd_section_edit.png", 6.0),
        CAP("Hình S4 — Trình tự chỉnh sửa BRD theo section (ba lớp: anchor map, patch ops, "
            "optimistic lock)"),
    ],
    [P("Người dùng chỉ định mục cần sửa bằng ngôn ngữ tự nhiên hoặc chọn trực tiếp trên cây "
       "mục. Giao diện hiển thị khác biệt trước–sau ở mức đoạn văn, kèm nút chấp nhận, sửa "
       "tiếp hoặc hoàn tác về phiên bản trước.")],
    [T([
        ["Fields", "Type", "Char", "Default", "Req", "Note"],
        ["section_id", "Varchar", "60", "", "x", "Mục bị tác động"],
        ["operation", "Enum", "", "", "x", "replace | append | insert_after | delete | set_table"],
        ["expect_checksum", "Varchar", "16", "", "x", "Checksum bên gọi đã đọc; lệch thì từ chối"],
        ["content", "JSON", "", "[]", "x", "Danh sách block mới theo lược đồ ở FR08"],
        ["revision", "Int", "5", "1", "x", "Số hiệu phiên bản, tăng đơn điệu"],
        ["patch_log", "Array", "", "[]", "x", "Nhật ký thao tác kèm thời điểm và người duyệt"],
    ], widths=[1.2, 0.8, 0.5, 0.7, 0.4, 2.8])],
)

FR_BLOCKS += fr(
    "FR10", "Quản trị và truy vết giải pháp",
    [
        P("Toàn bộ thông tin của một phiên được chiếu vào một mô hình dữ liệu chuẩn hoá dùng "
          "chung — Canonical Solution Model. Mô hình gồm các thực thể có mã ổn định: yêu cầu, "
          "ràng buộc, giả định, quyết định, thành phần, rủi ro, hạng mục công việc, bằng "
          "chứng, biện pháp kiểm soát và sản phẩm bàn giao; liên kết với nhau bằng các quan "
          "hệ có kiểu."),
        P("Bốn sổ cái chỉ-ghi-thêm được duy trì song song: bằng chứng, quyết định, phát hiện "
          "và bình luận. Mỗi lần một cổng được phê duyệt, hệ thống chụp một bản ảnh phiên bản "
          "để về sau có thể so sánh khác biệt và đánh giá phạm vi ảnh hưởng của thay đổi."),
        P("Ghi nhận thực tế (kiểm tra trên 59 workspace đã chạy): cơ chế build_solution_model "
          "tồn tại và được gọi tại mỗi cổng, nhưng solution_model.json chỉ xuất hiện ở 1/59 "
          "workspace; decision_log.json, comment_log.json và trace_links.json chưa xuất hiện "
          "ở bất kỳ workspace nào. FR10 mô tả năng lực ĐÃ THIẾT KẾ; mức độ ĐÃ CHẠY THẬT thấp "
          "hơn nhiều — xem ISS-12."),
        P(""),
        IMG("e2_csm_model.png", 6.0),
        CAP("Hình E2 — Mô hình dữ liệu CSM dạng ERD (9 quan hệ có kiểu)"),
    ],
    [P("Tab « Quality » hiển thị bảng điểm độ phủ yêu cầu, số phát hiện chưa xử lý và độ "
       "hoàn chỉnh bằng chứng. Tab « Comments » cho phép bình luận neo vào từng thực thể.")],
    [T([
        ["Fields", "Type", "Char", "Default", "Req", "Note"],
        ["entity_id", "Varchar", "20", "", "x", "REQ/CON/ASM/DEC/COMP/RISK/WBS/EVD/ART/CTRL-xx"],
        ["relation", "Enum", "", "", "x",
         "satisfies | constrains | assumes | supports | implements | mitigates | visualizes | claims"],
        ["provenance", "Enum", "", "agent", "x", "human | deterministic | agent"],
        ["revision", "Int", "5", "1", "x", "Tăng đơn điệu theo mỗi lần thay đổi"],
        ["content_hash", "Varchar", "64", "", "x", "SHA-256 nội dung thực thể"],
    ], widths=[1.2, 0.8, 0.5, 0.7, 0.4, 2.8])],
)

FR_BLOCKS += fr(
    "FR11", "Bàn giao kết quả",
    [
        P("Hệ thống hỗ trợ ba kênh bàn giao. Kênh thứ nhất là gửi email kèm các tệp bàn giao "
          "qua dịch vụ tích hợp Gmail (một cổng phê duyệt). Kênh thứ hai là đặt lịch họp — "
          "GỒM HAI BƯỚC riêng biệt: agent truy vấn khoảng trống trên lịch rồi mở thẻ chọn "
          "khung giờ (propose_meeting_slots, không phải cổng phê duyệt tiêu chuẩn mà là một "
          "interrupt riêng, thẻ giao diện slot_picker), sau đó mới mở cổng phê duyệt tạo sự "
          "kiện kèm liên kết họp trực tuyến (create_client_meeting). Kênh thứ ba là đồng bộ "
          "hạng mục WBS sang hệ quản lý công việc, mặc định chạy ở chế độ thử để người dùng "
          "đối chiếu trước khi ghi thật."),
        P("Việc đồng bộ là bất biến theo nội dung: hệ thống lưu ánh xạ giữa hạng mục nội bộ "
          "và mã công việc bên ngoài kèm mã băm nội dung, nên chạy lại nhiều lần không tạo "
          "bản ghi trùng."),
    ],
    [P("Thẻ « Email » hiển thị người nhận, tiêu đề, nội dung và danh sách tệp đính kèm để "
       "người dùng sửa trước khi gửi. Bộ chọn khung giờ hiển thị các lựa chọn còn trống. "
       "Thẻ đồng bộ hiển thị bảng so sánh: tạo mới / cập nhật / bỏ qua.")],
    [T([
        ["Fields", "Type", "Char", "Default", "Req", "Note"],
        ["recipients", "Array", "", "[]", "x", "Danh sách email người nhận"],
        ["attachments", "Array", "", "[]", "x", "pdf | pptx | xlsx | docx | drawio | png"],
        ["slot_start", "Datetime", "", "", "", "Thời điểm bắt đầu cuộc họp"],
        ["external_ref", "Varchar", "40", "", "", "Mã công việc phía Jira/Linear"],
        ["dry_run", "Boolean", "", "true", "x", "Mặc định chạy thử, không ghi thật"],
    ], widths=[1.2, 0.8, 0.5, 0.7, 0.4, 2.8])],
)

FR_BLOCKS += fr(
    "FR12", "Quản lý phiên và khôi phục hội thoại",
    [
        P("Mỗi phiên làm việc gắn với một thread_id. Người dùng có thể liệt kê, tạo mới, đổi "
          "tên và xoá phiên; khi mở lại một phiên, hệ thống khôi phục đầy đủ lịch sử hội "
          "thoại, trạng thái giao diện và toàn bộ artifact."),
        P("Trạng thái đồ thị và các cổng đang chờ phê duyệt được lưu bền vững, nên một cổng "
          "đang dừng vẫn sống sót qua lần khởi động lại dịch vụ. Vùng làm việc trên đĩa được "
          "cô lập theo thread và có cơ chế phục hồi từ cơ sở dữ liệu khi tệp bị mất."),
    ],
    [P("Thanh bên trái liệt kê phiên theo thứ tự mới nhất, hiển thị tên và tin nhắn cuối. "
       "Menu ngữ cảnh cho phép đổi tên và xoá. Trạng thái đang chờ phê duyệt được đánh dấu rõ.")],
    [T([
        ["Fields", "Type", "Char", "Default", "Req", "Note"],
        ["thread_id", "Varchar", "40", "", "x", "Khoá chính, dạng thread-<uuid12>"],
        ["name", "Varchar", "200", "Untitled", "x", "Tên do người dùng đặt, không bị ghi đè"],
        ["created_at", "Timestamptz", "", "NOW()", "x", ""],
        ["updated_at", "Timestamptz", "", "NOW()", "x", ""],
        ["messages_json", "Text", "", "[]", "x", "Lịch sử hội thoại"],
        ["state_json", "Text", "", "{}", "x", "Ảnh chụp trạng thái giao diện, dùng để phục hồi"],
        ["outcomes_json", "Text", "", "[]", "", "Nhật ký kết quả các cổng phê duyệt"],
    ], widths=[1.2, 0.8, 0.5, 0.7, 0.4, 2.8])],
)

FR_BLOCKS += fr(
    "FR13", "Phân tích business case (ROI/TCO/payback)  (MỚI)",
    [
        P("Đây là năng lực đã tồn tại trong mã nguồn (tool propose_business_case, cổng "
          "phê duyệt riêng) nhưng bản BRD 1.0 chưa mô tả. Người dùng chỉ cần cung cấp "
          "annual_benefit_usd (lợi ích quy đổi hàng năm) kèm benefit_basis (căn cứ ước "
          "lượng); phần chi phí xây dựng và chi phí vận hành TỰ ĐỘNG lấy từ wbs.json và "
          "tech_stack.json nếu không truyền tay."),
        P("Toàn bộ số học ROI/TCO/thời gian hoàn vốn được TÍNH TẤT ĐỊNH phía máy chủ "
          "(domain/reporting/business_case.py), không phải do mô hình ngôn ngữ suy đoán — "
          "agent chỉ cung cấp giả định đầu vào, máy chủ tính lại và hiển thị trên thẻ phê "
          "duyệt trước khi người dùng quyết định."),
    ],
    [P("Thẻ « Business Case » hiển thị chi phí triển khai, chi phí vận hành hàng năm (kèm "
       "nguồn: tự lấy hay người dùng ghi đè), lợi ích hàng năm, ROI%, TCO theo kỳ phân tích "
       "và thời gian hoàn vốn (để trống nếu dòng tiền không bao giờ hoà vốn).")],
    [T([
        ["Fields", "Type", "Char", "Default", "Req", "Note"],
        ["annual_benefit_usd", "Decimal", "12,2", "", "x", "Lợi ích quy đổi hàng năm, nên có evidence_id"],
        ["benefit_basis", "Text", "", "", "x", "Căn cứ ước lượng lợi ích (1-2 câu)"],
        ["implementation_cost_usd", "Decimal", "12,2", "", "", "Bỏ trống để tự lấy từ wbs.json"],
        ["annual_operating_cost_usd", "Decimal", "12,2", "", "", "Bỏ trống để tự lấy từ tech_stack.json × 12"],
        ["analysis_horizon_years", "Int", "2", "3", "x", "Kỳ phân tích, 1-10 năm"],
        ["roi_pct", "Decimal", "8,1", "", "x", "Tính tất định, không do mô hình suy đoán"],
        ["payback_period_years", "Decimal", "6,2", "", "", "Rỗng nếu dòng tiền không hoà vốn trong kỳ phân tích"],
    ], widths=[1.4, 0.8, 0.5, 0.7, 0.4, 2.6])],
)

FR_BLOCKS += fr(
    "FR14", "Sinh diagram có kiểu: sequence / ERD / state machine  (MỚI)",
    [
        P("Đây là năng lực đã tồn tại trong mã nguồn (prettygraph/native/{sequence,erd,"
          "state_machine}.py, tool render_typed_diagram) nhưng bản BRD 1.0 chỉ mô tả diagram "
          "kiến trúc — bỏ sót đúng loại hình mà bạn đọc BRD 1.0 đã chỉ ra là thiếu."),
        P("Agent viết một đoạn mã Python ngắn dùng DSL tương ứng (Sequence / ERD / "
          "StateMachine), gọi .render(\"out\") — bước này CHỈ ghi đặc tả JSON, chưa vẽ gì. "
          "Máy chủ đọc lại JSON, xác thực bằng Pydantic, chạy bộ kiểm tra cấu trúc tất định "
          "(tham chiếu treo, PK thiếu, FK mồ côi cho ERD; state không tới được, vòng lặp "
          "không lối ra cho state machine), rồi mới vẽ bằng engine native — cùng một engine "
          "dùng để vẽ diagram kiến trúc, không phải một công cụ riêng."),
        P("State machine diagram tự động xuất kèm transition_table.csv (bảng chuyển trạng "
          "thái dạng tất định, không do mô hình soạn) để đối chiếu độc lập với hình vẽ."),
    ],
    [P("Không có cổng phê duyệt riêng cho bước sinh — dùng chung finalize_diagram (GATE 3) "
       "như diagram kiến trúc. Canvas hiển thị cùng bộ tab: xem trước, mã nguồn, .drawio.")],
    [T([
        ["Fields", "Type", "Char", "Default", "Req", "Note"],
        ["kind", "Enum", "", "", "x", "sequence | erd | state_machine"],
        ["code", "Text", "", "", "x", "Script Python dùng DSL tương ứng, kết thúc bằng .render(\"out\")"],
        ["lint_errors", "Array", "", "[]", "", "Lỗi cấu trúc chặn kết xuất (vd terminal_with_outgoing)"],
        ["lint_warnings", "Array", "", "[]", "", "Cảnh báo không chặn kết xuất"],
        ["semantic_node_recall", "Decimal", "5,2", "", "", "Tỉ lệ node/tham chiếu giữ nguyên sau khi vẽ"],
    ], widths=[1.2, 0.8, 0.5, 0.7, 0.4, 2.8])],
)

FR_BLOCKS += [
    H("Bảng tổng hợp (traceability, gate registry, ngân sách)", 2),
    P("Hai bảng dưới đây tổng hợp thông tin đã tản mát khắp các mục FR ở trên thành một điểm "
      "tra cứu duy nhất — phục vụ đội phát triển và QA đối chiếu nhanh mà không phải đọc lại "
      "14 tiểu mục FR."),

    H("Đăng ký cổng phê duyệt (Gate Registry & Traceability)", 3),
    P("13 cổng phê duyệt (interrupt_on) cộng 1 điểm dừng riêng (propose_meeting_slots, không "
      "nằm trong danh sách GATE_TOOL_NAMES — dùng cơ chế interrupt() ngay trong thân tool) "
      "= 14 điểm dừng chờ người dùng."),
    T([
        ["Gate / Tool", "FR", "Quyết định hợp lệ", "Vai trò được phép*", "Card FE"],
        ["propose_tech_stack", "FR02", "approve · approve_with_assumptions · accept_risk · "
         "request_evidence · request_alternative · reject", "architect, lead, admin", "techstack_approval"],
        ["propose_blueprint", "FR03", "approve · approve_with_assumptions · accept_risk · "
         "request_alternative · request_evidence · reject", "architect, lead, admin", "blueprint_approval"],
        ["finalize_diagram", "FR04", "approve · reject", "architect, lead, admin", "result_review"],
        ["generate_pdf_report", "FR07", "approve · request_evidence · reject",
         "pm, lead, architect, admin", "pdf_report_approval"],
        ["propose_deck_plan", "FR07", "approve · request_alternative · reject",
         "(chưa gán)", "KHÔNG có card riêng — ISS-06"],
        ["generate_ppt_proposal", "FR07", "approve · request_evidence · reject",
         "pm, lead, architect, admin", "ppt_proposal_approval"],
        ["propose_wbs_skeleton", "FR06", "approve · request_alternative · reject",
         "(chưa gán)", "wbs_skeleton_approval"],
        ["propose_wbs", "FR06", "approve · approve_with_assumptions · accept_risk · "
         "request_alternative · reject", "pm, lead, architect, admin", "wbs_approval"],
        ["export_wbs_excel", "FR06", "approve · reject", "pm, lead, admin", "wbs_excel_approval"],
        ["propose_business_case", "FR13", "approve · approve_with_assumptions · accept_risk · "
         "request_evidence · reject", "pm, lead, architect, admin", "business_case_approval"],
        ["send_email", "FR11", "approve · reject", "pm, lead, admin", "email_approval"],
        ["propose_meeting_slots**", "FR11", "approve (kèm selected_slot) · khác = huỷ",
         "(không áp dụng)", "slot_picker"],
        ["create_client_meeting", "FR11", "approve · reject", "pm, lead, admin", "meeting_approval"],
        ["export_to_delivery", "FR11", "approve · reject", "pm, lead, admin", "delivery_export_approval"],
    ], widths=[1.35, 0.5, 2.3, 1.15, 1.2]),
    P("* Bảng phân quyền theo vai trò hiện ở mức KHUYẾN NGHỊ, không phải cưỡng chế: vi phạm "
      "được ghi log nhưng lệnh vẫn được thực thi (xem ISS-01). ** propose_meeting_slots không "
      "phải một trong 13 gate ở GATE_TOOL_NAMES — đây là interrupt() gọi trực tiếp trong thân "
      "tool, không đi qua HumanInTheLoopMiddleware.", italic=True),

    H("Ngân sách và trần số lần gọi", 3),
    T([
        ["Loại ngân sách", "Giá trị", "Nguồn (hằng số trong mã)"],
        ["Model call — main agent", "80 lần/run", "RUN_CALL_LIMIT"],
        ["Model call — icon_resolver / drawer / critic", "40 lần/run mỗi subagent", "ICON_CALL_LIMIT · DRAWER_CALL_LIMIT · CRITIC_CALL_LIMIT"],
        ["Model call — wbs_planner / ppt_generator", "60 lần/run mỗi subagent", "WBS_CALL_LIMIT · PPT_CALL_LIMIT"],
        ["Lời gọi task() (uỷ nhiệm subagent)", "12 lần/phiên", "TASK_CALL_LIMIT"],
        ["Bước đồ thị (recursion)", "450 bước/phiên", "RECURSION_LIMIT"],
        ["Tìm kiếm web", "10 truy vấn/phiên (tech_stack≤4, kiến trúc≤2, wbs≤1, bằng chứng≤2, khác≤1)", "WEB_SEARCH_SESSION_CAP"],
        ["Tìm icon", "20 truy vấn/phiên, ≤2 lần/1 truy vấn đơn", "ICON_SEARCH_DEFAULT_TOTAL_CAP · NODE_SINGLE_SEARCH_HARD_CAP"],
        ["Vòng render diagram", "3 lần bình thường, 6 lần trần cứng", "RENDER_SOFT_CAP · RENDER_HARD_CAP"],
        ["Vòng critic revise", "2 lần trần cứng, chỉ cấp lại khi bị từ chối thật", "CRITIC_REVISION_HARD_CAP"],
        ["Vòng edit_drawio / inspect / export native", "2 lần mỗi loại", "_DRAWIO_EDIT_CAP · _ENGINEER_INSPECT_CAP · _NATIVE_EXPORT_CAP"],
        ["Ngưỡng tự động hoàn tác", "Tụt > 1.0 điểm so với bản trước", "_EDIT_REGRESSION_TOLERANCE"],
        ["Code interpreter (run_python)", "6 lần/phiên, 60 giây/lần", "INTERPRETER_CALL_HARD_CAP"],
    ], widths=[2.0, 2.6, 1.8]),
    P("Bản 1.0 chỉ ghi hai loại ngân sách (web ≤3 lượt, render ≤3 vòng — cả hai đều sai so với "
      "mã nguồn). Bảng trên liệt kê đầy đủ 12 loại đang được cưỡng chế trong mã.", italic=True),
]

# ══════════════════ 4. SYSTEM FEATURES & NON-REQUIREMENTS ════════════════
SECTIONS["user"] = [
    P("Giao diện là ứng dụng web một trang, bố cục ba khung có thể kéo giãn: thanh phiên làm "
      "việc bên trái, khung hội thoại ở giữa, khung canvas hiển thị artifact bên phải."),
    B("Mọi phản hồi của agent phải hiển thị theo lối trực tuyến (streaming), không để người "
      "dùng chờ trước màn hình trống."),
    B("Tiến độ của các tiến trình con phải hiển thị theo thời gian thực dưới dạng dòng hoạt động."),
    B("Thẻ phê duyệt phải hiện ngay tại vị trí hội thoại, kèm đúng những hành động mà vai trò "
      "đang đăng nhập được phép thực hiện."),
    B("Mọi artifact phải tải về được từ canvas; ảnh diagram phải phóng to xem được."),
    B("Giao diện phải hỗ trợ tiếng Việt có dấu đầy đủ trên cả nội dung nhập và nội dung sinh ra."),
]

SECTIONS["hardware"] = [
    P("Hệ thống được đóng gói bằng Docker Compose và chạy trên một máy chủ Linux duy nhất "
      "hoặc trên hạ tầng container của công ty. Cấu hình khuyến nghị cho môi trường sản xuất "
      "quy mô một đội (10–20 người dùng đồng thời):"),
    T([
        ["Thành phần", "Cấu hình tối thiểu", "Khuyến nghị"],
        ["CPU", "4 vCPU", "8 vCPU"],
        ["RAM", "8 GB", "16 GB"],
        ["Đĩa", "50 GB SSD", "200 GB SSD (lưu artifact theo phiên)"],
        ["Mạng", "Kết nối Internet ra ngoài", "Băng thông ổn định, độ trễ thấp tới nhà cung cấp LLM"],
        ["GPU", "Không yêu cầu", "Không yêu cầu — suy luận thực hiện qua API"],
    ], widths=[1.5, 2.2, 2.7]),
    P("Các thành phần cần cài trong ảnh container: Graphviz để render diagram, trình duyệt "
      "không giao diện để kết xuất PDF, và bộ phông chữ hỗ trợ tiếng Việt."),
]

SECTIONS["software"] = [
    P("Hệ thống hoạt động theo mô hình agent điều phối (orchestrator) trên nền đồ thị trạng "
      "thái có điểm dừng (giới hạn 450 bước đồ thị/phiên — RECURSION_LIMIT). Một agent chính "
      "nắm 41 tool và uỷ nhiệm các phần việc chuyên môn cho 5 tiến trình con (subagent "
      "general-purpose mặc định của framework bị TẮT); trạng thái bền vững không nằm trong bộ "
      "nhớ đồ thị mà nằm ở các tệp artifact trong vùng làm việc của phiên — đây là lựa chọn "
      "thiết kế có chủ đích để mọi bước đều kiểm tra được bằng mắt và phục hồi được. Thực tế "
      "đây CHÍNH LÀ state machine duy nhất của sản phẩm: 6 giai đoạn (phase) được suy ra từ sự "
      "tồn tại của file trên đĩa, tính lại ở mỗi lần gọi mô hình — không có node chuyển trạng "
      "thái tường minh nào trong đồ thị LangGraph (xem Hình ST2)."),
    P(""),
    IMG("h3_agent.png", 5.4),
    CAP("Hình 3 — Kiến trúc Deep Agent, 12 lớp middleware và 5 tiến trình con"),
    P(""),
    P("Vòng đời một request chat, từ trình duyệt qua CopilotKit runtime tới LangGraph và "
      "ngược lại qua SSE:"),
    IMG("s1_request_lifecycle.png", 6.0),
    CAP("Hình S1 — Vòng đời một request chat (POST /agui → SSE)"),
    P(""),
    P("State machine phase — trạng thái thực tế của một phiên không nằm trong đồ thị mà suy "
      "từ file trên đĩa:"),
    IMG("st2_phase_state_machine.png", 6.0),
    CAP("Hình ST2 — State machine phase (intake → blueprint → draw → wbs → ppt → report)"),
    P(""),
    P("Lược đồ lưu trữ PostgreSQL 16 — bảng conversations do ứng dụng tự quản, cộng các bảng "
      "checkpoint/store do thư viện langgraph-checkpoint-postgres tạo:"),
    IMG("e1_storage_schema.png", 6.0),
    CAP("Hình E1 — Lược đồ lưu trữ PostgreSQL 16"),
    P(""),
    P("Bảng công nghệ sử dụng:"),
    T([
        ["No.", "Category", "Technologies"],
        ["1", "Framework", "FastAPI, LangGraph, LangChain, React 19, Vite 6, CopilotKit runtime "
                            "(Node ESM :3001 — cầu nối AG-UI ↔ /agui, không phải sandbox)"],
        ["2", "Ngôn ngữ lập trình", "Python 3.11, TypeScript 5.8"],
        ["3", "Cơ sở dữ liệu", "PostgreSQL 16 (checkpoint + hội thoại), tệp JSON theo phiên"],
        ["4", "Thư viện sinh tài liệu", "python-docx, python-pptx, openpyxl, Jinja2, Playwright"],
        ["5", "Thư viện vẽ", "diagrams (mingrammer), Graphviz, bộ chuyển DOT → .drawio"],
        ["6", "Giao diện", "Tailwind CSS 4, giao thức AG-UI trên nền Server-Sent Events"],
        ["7", "Tích hợp ngoài", "OpenAI / Anthropic API, Tavily, Composio (Gmail, Calendar, Meet), Jira"],
        ["8", "Vận hành", "Docker Compose, LangSmith (giám sát và truy vết lời gọi mô hình)"],
    ], widths=[0.5, 1.7, 4.2]),
    P(""),
    P("Kiến trúc triển khai:"),
    IMG("h2_deployment.png", 5.6),
    CAP("Hình 2 — Kiến trúc triển khai theo Docker Compose"),
]

SECTIONS["communication"] = [
    P("Giao tiếp giữa các thành phần trong hệ thống tuân theo mô hình client–server:"),
    B("Giao diện ↔ backend: HTTP/REST cho các thao tác quản lý phiên và tải tệp; một điểm "
      "cuối duy nhất theo giao thức AG-UI trên nền Server-Sent Events cho toàn bộ luồng hội "
      "thoại, sự kiện công cụ và cập nhật trạng thái."),
    B("Backend ↔ cơ sở dữ liệu: kết nối bất đồng bộ qua bể kết nối tối đa 20 phiên."),
    B("Backend ↔ nhà cung cấp mô hình: HTTPS, có cơ chế chuyển mô hình dự phòng khi lỗi và "
      "cơ chế thử lại chỉ dùng văn bản khi lời gọi kèm hình ảnh bị từ chối."),
    B("Backend ↔ dịch vụ ngoài: HTTPS qua Composio cho Gmail/Calendar/Meet và qua REST cho "
      "Jira; khoá bí mật truyền qua ngữ cảnh phiên, không đưa vào lời nhắc gửi tới mô hình."),
    B("Toàn bộ giao tiếp ra ngoài phải qua HTTPS; danh sách nguồn được phép gọi tới giao "
      "diện được cấu hình tường minh."),
]

SECTIONS["system-features"] = [
    T([
        ["No.", "Category", "Features"],
        ["1", "Phân tích yêu cầu",
         "Bóc tách tài liệu đính kèm; phân loại sự kiện – giả định – ràng buộc; lập diagram brief; "
         "đặt câu hỏi làm rõ khi thiếu thông tin"],
        ["2", "Thiết kế giải pháp",
         "Tìm kiếm web có ngân sách; đề xuất tech stack; đề xuất blueprint; đối chiếu khung "
         "Well-Architected; kiểm tra độ phủ yêu cầu"],
        ["3", "Sinh bản vẽ",
         "Phân giải icon đa nguồn; sinh mã diagrams-as-code; render PNG; kết xuất .drawio; "
         "tự phê bình chất lượng; chỉnh sửa tại chỗ"],
        ["4", "Sinh tài liệu",
         "Báo cáo PDF; đề xuất PowerPoint; WBS Excel có công thức sống; gói ADR; "
         "tài liệu BRD .docx và chỉnh sửa theo từng mục (MỚI)"],
        ["5", "Quản trị chất lượng",
         "Mô hình CSM; sổ bằng chứng; sổ quyết định; danh sách phát hiện; bình luận theo thực "
         "thể; so sánh phiên bản; đánh giá phạm vi ảnh hưởng"],
        ["6", "Bàn giao",
         "Gửi email kèm tệp; đặt lịch họp kèm liên kết trực tuyến; đồng bộ WBS sang Jira/Linear "
         "theo cơ chế bất biến"],
        ["7", "Kiểm soát vận hành",
         "Giới hạn số lời gọi mô hình theo từng tiến trình; ngân sách tìm kiếm web; nhật ký "
         "chi phí token theo từng agent; lọc công cụ theo giai đoạn"],
    ], widths=[0.4, 1.5, 4.5]),
]

SECTIONS["performance"] = [
    P("Bản 1.0 đặt một cột thời gian duy nhất cho mỗi chức năng — không phân biệt được thời "
      "gian agent tính toán và thời gian chờ người phê duyệt, nên không thể nghiệm thu. Bảng "
      "dưới đây tách hai loại và đối chiếu với số đo thật trên một phiên end-to-end đầy đủ "
      "(29 node kiến trúc, WBS + PDF 11 trang + PPTX 22 slide) trong artifacts/ của dự án."),
    T([
        ["Functions", "Agent compute time (cam kết)", "Đo thật (1 phiên đầy đủ)"],
        ["Phân tích yêu cầu và lập brief", "≤ 90 giây với tài liệu đầu vào ≤ 20 trang", "37 giây — đạt"],
        ["Đề xuất tech stack (không tính thời gian chờ duyệt)", "≤ 120 giây, gồm tối đa 10 truy vấn web",
         "5 phút 31 giây tính cả chờ duyệt GATE 1 (~4 phút); phần compute nằm trong cam kết"],
        ["Sinh và render diagram (không tính thời gian chờ duyệt)", "≤ 180 giây cho bản vẽ ≤ 40 node, "
         "tối đa 2 vòng tinh chỉnh Tier 1-2", "10 phút 34 giây cho 29 node — VƯỢT cam kết 3.5 lần "
         "(9 vòng edit_drawio, 7 vòng bị auto-revert)"],
        ["Kết xuất WBS Excel", "≤ 60 giây cho kế hoạch ≤ 300 hạng mục", "Chưa đo lại trên phiên này"],
        ["Sinh BRD .docx lần đầu", "≤ 150 giây cho tài liệu ≤ 40 mục", "Module chưa triển khai — chưa đo được"],
        ["Chỉnh sửa một mục của BRD", "≤ 20 giây, không phụ thuộc kích thước tài liệu", "Module chưa triển khai"],
        ["Khôi phục phiên làm việc", "Hiển thị đầy đủ hội thoại và artifact trong ≤ 3 giây", "Chưa đo lại"],
        ["Toàn phiên (yêu cầu → PPTX, gồm mọi lượt chờ duyệt)", "(không có cam kết ở bản 1.0)",
         "25 phút 28 giây wall-clock"],
        ["Đồng thời", "Phục vụ ≥ 20 phiên đồng thời trên cấu hình khuyến nghị", "Chưa kiểm thử tải"],
    ], widths=[2.0, 2.2, 2.2]),
    P("Ghi chú: cam kết \"≤ 400.000 token đầu ra/phiên\" ở bản 1.0 bị loại khỏi bảng vì không "
      "tìm thấy cơ chế đo hay cưỡng chế tương ứng trong mã nguồn (usage.json chỉ xuất hiện ở "
      "1/59 workspace đã kiểm tra) — cần điều tra trước khi đưa lại vào cam kết NFR.", italic=True),
]

SECTIONS["safety"] = [
    T([
        ["Possible damages", "Safety requirements", "Safeguards"],
        ["Agent tự ý cam kết kiến trúc hoặc chi phí sai với khách hàng",
         "Mọi quyết định trọng yếu phải được người có thẩm quyền phê duyệt",
         "13 cổng HITL bắt buộc (GATE_TOOL_NAMES) cộng 1 điểm dừng riêng cho chọn khung giờ "
         "họp; hệ thống dừng đồ thị và chỉ đi tiếp khi nhận được quyết định"],
        ["Nội dung tài liệu bịa đặt, không có căn cứ",
         "Mọi phát biểu định lượng phải có bằng chứng hoặc được đánh dấu là giả định",
         "Sổ bằng chứng; kiểm tra độ phủ; đánh dấu rõ phần suy đoán trong tài liệu"],
        ["Chỉnh sửa một mục làm hỏng phần còn lại của tài liệu",
         "Thao tác vá phải cô lập tuyệt đối trong phạm vi mục được chỉ định",
         "Bản đồ anchor kèm checksum; khoá lạc quan từ chối lệnh vá khi nội dung đã đổi; "
         "lưu phiên bản trước mỗi lần vá để hoàn tác"],
        ["Chạy mã do mô hình sinh ra gây tác động ngoài ý muốn",
         "Mã diagram phải được kiểm tra tĩnh trước khi thực thi",
         "Kiểm tra tĩnh bắt buộc; thực thi trong tiến trình con có giới hạn thời gian; "
         "chặn truy cập đường dẫn ngoài vùng làm việc"],
        ["Gửi email hoặc ghi dữ liệu sang hệ thống ngoài ngoài ý muốn",
         "Không thao tác ghi ra ngoài nếu chưa được duyệt tường minh",
         "Cổng phê duyệt riêng cho email, lịch họp và đồng bộ; chế độ chạy thử là mặc định"],
    ], widths=[1.9, 2.1, 2.4]),
]

SECTIONS["security"] = [
    T([
        ["Possible threats", "Security requirements", "Safeguards"],
        ["Rò rỉ tài liệu yêu cầu của khách hàng",
         "Dữ liệu phiên phải được cô lập theo thread và không rời khỏi hạ tầng công ty ngoài "
         "phần gửi tới nhà cung cấp mô hình",
         "Vùng làm việc tách theo thread; kiểm tra đường dẫn chống vượt thư mục; "
         "cơ sở dữ liệu đặt trong mạng nội bộ"],
        ["Lộ khoá API và khoá tài khoản tích hợp",
         "Khoá bí mật không được xuất hiện trong lời nhắc gửi tới mô hình hay trong nhật ký",
         "Khoá truyền qua ngữ cảnh phiên của đồ thị; tệp .env không đưa vào kho mã; "
         "che khoá trong toàn bộ nhật ký"],
        ["Người không đủ thẩm quyền phê duyệt cổng trọng yếu",
         "Quyền phê duyệt phải gắn với vai trò và được cưỡng chế ở phía máy chủ",
         "Bảng phân quyền theo cổng; cần nâng cấp từ mức khuyến nghị hiện tại lên mức "
         "cưỡng chế — xem Appendix B"],
        ["Chèn lệnh độc hại qua tài liệu đính kèm (prompt injection)",
         "Nội dung do người dùng cung cấp phải được đối xử như dữ liệu, không phải chỉ thị",
         "Tách rõ vùng dữ liệu và vùng chỉ thị trong lời nhắc; vô hiệu hoá thẻ điều khiển "
         "trong nội dung bóc tách; giới hạn công cụ theo giai đoạn"],
        ["Sửa đổi tài liệu bàn giao sau khi đã phê duyệt",
         "Mỗi phiên bản đã duyệt phải bất biến và truy vết được",
         "Ảnh chụp phiên bản kèm mã băm nội dung; sổ quyết định chỉ-ghi-thêm; "
         "nhật ký thao tác vá kèm người duyệt và thời điểm"],
    ], widths=[1.9, 2.1, 2.4]),
]

SECTIONS["quality"] = [
    T([
        ["Criterias", "Related factors", "Quality requirements"],
        ["Khả năng truy xuất", "Mô hình CSM, sổ bằng chứng",
         "Truy xuất được toàn bộ thao tác của agent, quyết định của người dùng và nguồn gốc "
         "của mỗi phát biểu trong tài liệu"],
        ["Tính chính xác", "Chất lượng mô hình, bộ eval",
         "Độ phủ yêu cầu ≥ 95%; số phát hiện nghiêm trọng chưa xử lý bằng 0 trước khi bàn giao"],
        ["Tính nhất quán", "Nguồn dữ liệu dùng chung",
         "Số liệu và thuật ngữ trùng khớp 100% giữa BRD, báo cáo PDF, bộ slide và WBS"],
        ["Tính toàn vẹn định dạng", "Cơ chế vá .docx",
         "Sau mỗi lần chỉnh sửa một mục, toàn bộ mục khác giữ nguyên từng byte; "
         "style, đánh số và mục lục của template không đổi"],
        ["Khả năng lặp lại", "Bộ eval hồi quy",
         "Bộ eval chạy tự động trên mỗi thay đổi mã; không cho phép chỉ số trung bình giảm "
         "quá 0,02 so với mốc chuẩn"],
        ["Khả năng phục hồi", "Lưu trạng thái bền vững",
         "Cổng đang chờ phê duyệt sống sót qua khởi động lại dịch vụ; phiên khôi phục đầy đủ "
         "hội thoại và artifact"],
        ["Trải nghiệm", "Giao diện trực tuyến",
         "Không có màn hình chờ quá 3 giây mà không có phản hồi tiến độ"],
    ], widths=[1.4, 1.6, 3.4]),
]

# ══════════════════════════ APPENDIX ═════════════════════════════════════
SECTIONS["analysis-models"] = [
    P("Danh sách các mô hình phân tích và tài liệu tham chiếu kèm theo BRD này. Bản 1.1 tăng "
      "từ 8 lên 16 hình: tách Hình 4 (13 gate dồn một trang, không đọc được) thành ba hình "
      "theo giai đoạn, thay Hình 6/7/8 (vẽ tay bằng diagrams, không đúng chuẩn UML) bằng hình "
      "sinh từ chính engine typed-diagram của sản phẩm, và bổ sung 5 sequence + 3 state machine "
      "diagram hoàn toàn mới để trả lời câu hỏi \"luồng agent chạy cụ thể ra sao\"."),
    T([
        ["DOCUMENT NAME", "DESCRIPTION", "LOCATION"],
        ["Hình 1 — System Context", "Sơ đồ ngữ cảnh: người dùng, hệ thống và các dịch vụ ngoài", "Mục 1.4"],
        ["Hình 2 — Deployment", "Kiến trúc triển khai Docker Compose (4 service, có copilot-runtime)", "Mục 4.1.3"],
        ["Hình 3 — Agent Architecture", "Agent chính (41 tool), 12 lớp middleware, 5 tiến trình con", "Mục 4.1.3"],
        ["Hình 4a — Intake → Blueprint", "Luồng GATE 1-2: tiếp nhận, tech stack, blueprint", "Mục 3.1"],
        ["Hình 4b — Draw Loop", "Luồng GATE 3: uỷ nhiệm vẽ và engineer loop ba tầng", "Mục 3.1"],
        ["Hình 4c — Deliverable & Handover", "Luồng GATE 4-13: báo cáo, WBS, business case, bàn giao", "Mục 3.1"],
        ["Hình 5 — Artifact Lifecycle", "Vòng đời artifact trong workspace theo phase (đầy đủ)", "Mục 3.1"],
        ["Hình S1 — Request Lifecycle", "Sequence: một request chat từ trình duyệt tới SSE", "Mục 4.1.3"],
        ["Hình S2 — Gate Lifecycle", "Sequence: interrupt → card → resume, cơ chế 13 cổng dùng chung", "Mục 3.1"],
        ["Hình S3 — Subagent + Engineer Loop", "Sequence: icon_resolver → drawer → engineer loop → critic", "Mục 3.5 (FR04)"],
        ["Hình S4 — BRD Section Edit", "Sequence: vá 1 mục BRD qua anchor map + optimistic lock", "Mục 3.10 (FR09)"],
        ["Hình ST1 — Gate State Machine", "State machine: vòng đời một cổng HITL (idle→…→resumed)", "Mục 3.1"],
        ["Hình ST2 — Phase State Machine", "State machine: 6 phase suy từ file trên đĩa", "Mục 4.1.3"],
        ["Hình ST3 — Diagram Quality Loop", "State machine: rendered→scored→kept/reverted→finalized", "Mục 3.5 (FR04)"],
        ["Hình E1 — Storage Schema", "ERD: bảng conversations + checkpoint/store PostgreSQL", "Mục 4.1.3"],
        ["Hình E2 — CSM Data Model", "ERD: mô hình dữ liệu chuẩn hoá và 9 quan hệ có kiểu", "Mục 3.11 (FR10)"],
        ["Mã nguồn hình kiến trúc", "diagrams + Graphviz — H1/H2/H3/H4a-c/H5", "BRD/figs_src/figs_arch.py, figs_flow.py"],
        ["Mã nguồn hình sequence/ERD/state machine", "Dogfood prettygraph.native — cùng engine sản phẩm dùng để vẽ",
         "BRD/figs_src/figs_typed.py, render_typed.py"],
        ["Kế hoạch xây dựng BRD Agent", "Design doc chi tiết: tool spec, state, eval plan",
         "KE_HOACH_BRD_AGENT.md"],
    ], widths=[2.0, 3.3, 1.5]),
]

SECTIONS["issues-list"] = [
    P("Các vấn đề còn tồn đọng, ghi nhận tại thời điểm lập tài liệu. Những mục này cần được "
      "xử lý hoặc chấp nhận rủi ro tường minh trước khi đưa hệ thống vào sử dụng rộng rãi. "
      "Cột Owner/Due chưa có trong hệ thống quản lý công việc của dự án tại thời điểm viết "
      "bản 1.1 nên để trống thay vì bịa — xem cột Mức độ để ưu tiên xử lý."),
    T([
        ["ISSUE ID", "ISSUE DESCRIPTION", "Mức độ", "STATUS"],
        ["ISS-01", "Phân quyền phê duyệt theo vai trò hiện chỉ ở mức khuyến nghị: vi phạm "
                   "được ghi nhật ký nhưng vẫn cho đi tiếp. Cần cưỡng chế phía máy chủ.", "Cao", "Open"],
        ["ISS-02", "Tài liệu README của kho mã đã lệch so với mã nguồn thực tế (đường dẫn "
                   "module, số cổng phê duyệt, giới hạn đệ quy).", "Thấp", "Open"],
        ["ISS-03", "Tồn tại hai bản cấu hình song song (module và package) gần trùng nhau, "
                   "cùng nhiều module chỉ làm lớp chuyển tiếp — nợ kỹ thuật cần dọn.", "Trung bình", "Open"],
        ["ISS-04", "Năng lực truy hồi tri thức dự án cũ (RAG) đang bị tắt hoàn toàn ở cả tầng "
                   "công cụ lẫn tầng hạ tầng.", "Thấp", "Deferred"],
        ["ISS-05", "Ba tài liệu kỹ năng không được nạp bởi bất kỳ agent nào và hai bản sao "
                   "kỹ năng đã lỗi thời vẫn nằm trong kho.", "Thấp", "Open"],
        ["ISS-06", "Cổng phê duyệt storyboard bộ slide (propose_deck_plan) chưa có thẻ giao "
                   "diện tương ứng — rơi vào thẻ mặc định (WildcardGateCard), cũng chưa gán "
                   "vai trò được phép duyệt.", "Trung bình", "Open"],
        ["ISS-07", "Nhận diện ý định trong câu tiếp theo của người dùng dựa trên đối sánh cụm "
                   "từ; khi thêm loại tài liệu mới (BRD) phải chèn đúng thứ tự ưu tiên.", "Trung bình", "Open"],
        ["ISS-08", "Vùng làm việc dùng chung từng bị xoá nhầm giữa các phiên; đã có cơ chế "
                   "phục hồi từ cơ sở dữ liệu nhưng cần kiểm thử tải để khẳng định.", "Cao", "Monitor"],
        ["ISS-09", "Chưa có bộ eval cho luồng sinh và chỉnh sửa BRD — phải xây cùng module mới.", "Trung bình", "New"],
        ["ISS-10", "Chưa xác định chính sách lưu trữ và xoá dữ liệu khách hàng theo thời hạn.", "Trung bình", "Open"],
        ["ISS-11", "Điểm \"editability\" trong quality_history.json luôn bằng 0.0 ở mọi vòng "
                   "quan sát được (9/9 vòng trên một phiên thật) — có thể là lỗi tính điểm "
                   "chưa ai phát hiện, cần điều tra trước khi dùng điểm này để quyết định gì.",
                   "Cao", "New"],
        ["ISS-12", "Mô hình CSM (solution_model.json) và các sổ cái decision/comment/"
                   "trace_links gần như không được ghi trong thực tế (1/59 và 0/59 workspace "
                   "kiểm tra có file) dù code path tồn tại — FR10 đang mô tả năng lực đã thiết "
                   "kế như thể đã chạy. Cần xác định đây là bug hay tính năng chưa kích hoạt.",
                   "Cao", "New"],
        ["ISS-13", "usage.json (chi phí token theo agent) chỉ xuất hiện ở 1/59 workspace dù "
                   "UsageLoggingMiddleware chạy ở mọi lời gọi model — cam kết NFR \"≤400.000 "
                   "token/phiên\" ở bản 1.0 không có cơ chế đo hậu thuẫn, đã gỡ khỏi bản 1.1.",
                   "Trung bình", "New"],
    ], widths=[0.7, 3.8, 0.8, 0.9]),
]
