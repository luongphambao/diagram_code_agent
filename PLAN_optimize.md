# Plan Giảm Token Cho Diagram Agent

## Summary
Giảm token chủ yếu ở 4 nguồn trong log: main agent đọc skill quá sớm, dò filesystem nhiều lượt, task description lặp lại full blueprint/tech stack, và context cleanup kích hoạt quá trễ. Mục tiêu: giữ chất lượng diagram nhưng giảm input context và số model turns.

## Key Changes
- Main agent không đọc skills render nữa:
  - Bỏ `skills=SKILL_PATHS` khỏi main `create_deep_agent(...)`.
  - Giữ skills cho drawer subagent.
  - Sửa main prompt: không yêu cầu đọc `pro-style` / `diagrams-as-code` khi propose tech stack/blueprint.

- Tránh `ls/glob` để tìm requirements:
  - Server message ghi exact path: `/app/backend/agent_space/workspace/requirements.md`.
  - Prompt hướng dẫn đọc đúng file đó, không `ls`, không `glob`.
  - Giới hạn đọc ban đầu khoảng 120-180 lines; chỉ đọc tiếp nếu thiếu thông tin.

- Không nhồi full blueprint vào mọi `task(...)`:
  - Drawer/critic task description chỉ nói: đọc `tech_stack.json` và `blueprint.json` trong workspace.
  - Với revision task, chỉ truyền findings cần sửa.
  - Drawer/critic tự đọc approved files khi cần.

- Context cleanup sớm hơn:
  - Giảm `CONTEXT_TRIGGER_TOKENS` từ `30_000` xuống khoảng `12_000`.
  - Giữ `keep=4` hoặc `keep=6`.
  - Mục tiêu clear các `read_file` outputs cũ trước khi blueprint/task args làm context phình.

- Compact `pro-style` skill:
  - Rút `backend/skills/pro-style/SKILL.md` thành quickstart ngắn.
  - Chuyển phần dài như infographic/layout advanced sang reference file riêng.
  - Drawer chỉ đọc reference chuyên sâu khi request thuộc dạng infographic hoặc layout phức tạp.

- Giới hạn icon search:
  - Giữ `search_icons(query, provider=...)` cho drawer để tool calls có thể chạy song song.
  - Prompt drawer phải lập exact icon plan trước khi search.
  - Chặn quá 3 lần search cho cùng icon/query/provider để tránh tool chatter.

- Giảm reasoning token:
  - Cho phép env config `REASONING_EFFORT`.
  - Default đề xuất: `low` cho main/critic, giữ `medium` cho drawer nếu cần render phức tạp.
  - Nếu muốn code đơn giản, đặt global default `low` trước, đo lại chất lượng.

## Test Plan
- Unit/static checks:
  - Main prompt không còn yêu cầu đọc skills.
  - Main agent không nhận `skills=SKILL_PATHS`.
  - Drawer vẫn nhận skills.
  - Task prompt không yêu cầu truyền full blueprint trong description.

- Regression run với cùng requirements:
  - Kỳ vọng không còn `ls /`, `ls /app`, `glob **/requirements.md`.
  - Kỳ vọng main run đọc tối đa 1 requirements file pass ban đầu.
  - Kỳ vọng drawer/critic task args ngắn hơn nhiều.
  - Kỳ vọng vẫn có flow: tech stack -> blueprint -> drawer -> critic -> finalize.

- Token acceptance:
  - Main root input tokens trước render giảm đáng kể so với log hiện tại.
  - Target thực tế: giảm khoảng 30-50% input token ở root run.
  - Không fail render/export/final review.

## Assumptions
- Tối ưu áp dụng cho `backend/src/diagram_mcp` diagram agent, đúng theo JSON log bạn đưa.
- Giữ staged HITL flow hiện tại.
- Không bỏ critic gate, vì critic đã bắt lỗi thật trong run này.
- Không giảm chất lượng bằng cách bỏ blueprint chi tiết; chỉ tránh lặp lại blueprint trong các task sau.
