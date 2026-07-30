# 0002 — Tắt subagent `general-purpose` ngầm của deepagents

**Ngày ghi lại:** 2026-07-26 (quyết định có từ trước, ADR hồi tố)
**Trạng thái:** accepted

## Bối cảnh

`create_deep_agent()` **âm thầm** thêm một subagent `general-purpose` cùng tool `task` vào **mọi** agent, kể cả subagent. Không có tài liệu nào ở tầng gọi cho biết điều đó, và nó không xuất hiện trong danh sách `subagents` mình khai.

Hai trace thật cho thấy hậu quả:
- Run 4M token: một lần render fail khiến `drawer` retry qua `task(general-purpose)` ba lần. Các agent lồng nhau này không có state, không có trần call, và thừa hưởng đúng bộ tool của agent cha. **1.66M token = 42% toàn bộ run.**
- Run 6M token sau đó: `wbs_planner` — subagent duy nhất còn được giữ `general-purpose` — làm y hệt.

## Quyết định

Tắt subagent `general-purpose` cho **mọi** model tại thời điểm build: `_set_general_purpose_enabled(False, ...)` trong `agent/harness.py`, gọi từ `agent/builder.py`. Tool `task` chỉ còn tồn tại ở main agent để dispatch 6 subagent đã khai báo tường minh.

Chốt canh bằng test: `tests/test_general_purpose_disabled.py` kiểm cả 6 lần gọi `create_deep_agent`.

## Phương án đã loại

- **Giữ `general-purpose` cho `wbs_planner` với `task_call_limit=3`** — đã thử, rồi bỏ. Lý do: GP thừa hưởng đúng bộ tool của agent cha, nên **không bao giờ** làm được gì mà agent cha không tự làm được. Nó chỉ thêm một tầng lồng và một khoản token.
- **Cấm bằng prompt ("đừng gọi `task`")** — loại. Bài học lặp lại ở nhiều chỗ trong hệ thống này: cấm bằng prompt không giữ được khi model gặp lỗi và bắt đầu thử mọi cách.
- **Đặt trần call cho GP** — loại vì chữa triệu chứng: cái phải chặn là con đường lồng nhau, không phải độ sâu của nó.

## Hệ quả

- **Dễ hơn:** token spend dự đoán được; mỗi delegate đều thấy được trên trace với một trần call gắn tên.
- **Khó hơn:** không còn "thoát hiểm chung chung". Một subagent gặp việc ngoài tool của nó thì **thất bại** thay vì tự xoay xở. Đó là điều mong muốn — thất bại là dấu hiệu tool list hoặc phân rã đang sai.
- Cần nhớ khi nâng version deepagents: hành vi thêm-ngầm này có thể đổi tên hoặc đổi cơ chế. Nếu test canh đỏ sau khi nâng, **đừng sửa test** — kiểm lại xem kill switch còn ăn không.
- Nguyên tắc tổng quát rút ra: **hành vi phải chặn ở tầng cấu hình/permission, không phải ở prompt.** Xem thêm `FilesystemPermission` của `icon_resolver` trong `agent-design.md` §2.
