# 0001 — Memory là file; Qdrant chỉ là tool truy xuất

**Ngày ghi lại:** 2026-07-26 (quyết định có từ trước, đây là bản ADR hồi tố)
**Trạng thái:** accepted

## Bối cảnh

Agent cần nhớ hai loại thứ rất khác nhau:
1. Sự thật bền về người dùng và dự án — cần đúng, cần audit được, cần luôn có mặt.
2. Kho ~116 dự án BnK cũ (tự sự + số liệu WBS) — lớn, chỉ thỉnh thoảng cần, và cần khớp theo ngữ nghĩa.

Đưa cả hai vào cùng một cơ chế sẽ hỏng một trong hai: nhét corpus vào prompt thì phình context, còn để memory bền trong vector store thì không ai đọc được, không diff được, không audit được lần ghi nào.

## Quyết định

**Tách đôi.**

- **Memory bền = file.** `/memories/AGENTS.md` (theo thread) và `/global-memories/AGENTS.md` (xuyên thread), nạp vào system prompt mỗi lượt. Không embedding pipeline, không retrieval step lúc query. Trạng thái phiên đi vào file JSON trong workspace, không vào memory.
- **Corpus past-project = tool.** `solution_memory.json` + Qdrant collection `bnk_solutions`, truy cập qua `find_similar_solutions` / `benchmark_solution`. Kết quả vào **message**, không vào system prompt.

Giữ `case_library.json` + `pick_case_study` theo keyword làm fallback khi Qdrant vắng mặt.

## Phương án đã loại

- **Vector DB làm memory mặc định** — loại vì memory không đọc được bằng mắt thì không audit được, và mỗi lượt phải trả thêm một retrieval step cho thứ hầu như luôn cần.
- **Nhét corpus dự án cũ vào system prompt** — loại vì phình context tuyến tính theo kích thước corpus, và 95% thời gian là vô dụng.
- **Ba collection theo granularity (`bnk_projects` / `bnk_modules` / `bnk_wbs_items`) làm giao diện chính** — giữ cho tương thích ngược, nhưng `bnk_solutions` hợp nhất mới là thứ được ưu tiên: một hit trả lời được cả "đã giải bài toán gì" lẫn "tốn bao nhiêu", thay vì bắt agent join ba lần.

## Hệ quả

- **Dễ hơn:** đọc/sửa memory bằng tay; audit mọi lần ghi qua git và log; chạy hệ thống hoàn toàn không cần Qdrant.
- **Khó hơn:** `AGENTS.md` phải giữ ngắn (vài trăm từ) — nó vào prompt mỗi lượt, phình lên là trả giá ở **mọi** lượt. Cần nói rõ trong prompt cái gì **không** được lưu (credential, thông tin nhất thời).
- **Rủi ro tồn dư:** Qdrant vắng mặt là **suy giảm chất lượng trong im lặng** — `find_similar_solutions` trả `status: "ERROR"` và agent đi tiếp mà không có tham chiếu dự án cũ. Đây là đánh đổi có chủ ý (không chặn luồng), nhưng phải kiểm `status` chứ đừng chỉ nhìn có kết quả hay không.
- Ghi song song vào cùng một file memory là last-write-wins. Tách memory theo chủ đề nếu contention thành vấn đề.
