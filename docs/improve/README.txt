Nâng cấp diagram_code_agent — bộ tài liệu + code drop-in
=========================================================

1) NANG-CAP-DIAGRAM-AGENT.md
   Phân tích đầy đủ: số liệu đo trên 9 output của repo, 3 lỗi gốc rễ,
   9 patch có code, roadmap 4 sprint, definition-of-done mới.
   ĐỌC PHẦN 2 TRƯỚC — đó là gốc rễ của mọi lỗi còn lại.

2) text_metrics.py                → backend/src/prettygraph/text_metrics.py
   Font metrics thật, thay len(s)*6.6. Chạy trực tiếp để xem sai số:
       python text_metrics.py

3) semantic_gates.py              → backend/src/domain/validation/semantic_gates.py
   7 invariant (I1..I7) mà validator 1.6k dòng hiện tại chưa kiểm.
   Chạy triage ngay trên file drawio có sẵn:
       python semantic_gates.py example/*.drawio

Thứ tự làm: Patch 1 (text_metrics, cả engine LẪN validator) → Patch 2 (I1-I4)
→ hợp nhất skill duplicate. Đừng nhảy cóc: các metric hiện có chỉ nói thật
sau khi Patch 1 xong.
