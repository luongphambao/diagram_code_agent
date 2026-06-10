# Plan Nâng Diagram Agent Lên Internal Production

## Summary
Ưu tiên production nội bộ với trọng tâm cost + reliability. Giữ flow hiện tại, không tách nhiều agent. Thêm `requirements_analyst`, giảm context lặp, thêm guardrails để tránh loop, tăng eval/trace, và harden upload/render vừa đủ cho team dùng ổn định.

## Key Changes
- Token/cost:
  - Thêm `requirements_analyst` subagent để đọc full `requirements.md` một lần và trả structured brief ngắn.
  - Main agent dùng brief thay vì đọc full docs + skills.
  - Main agent không nhận `skills=SKILL_PATHS`; chỉ drawer dùng render skills.
  - Task drawer/critic không truyền full blueprint/tech stack trong description; bảo subagent đọc `tech_stack.json` và `blueprint.json`.
  - Giảm context cleanup trigger từ `30_000` xuống khoảng `12_000`.
  - Giữ `search_icons(...)` cho drawer, cho phép gọi song song nhưng bắt lập exact icon plan trước.

- Reliability:
  - Thêm stage/state guard: không render nếu thiếu approved blueprint; không finalize nếu chưa có critic `PASS`.
  - Fix todo lifecycle để cuối run không còn step stale `in_progress`.
  - Thêm max retry rõ cho critic-revise loop: tối đa 2 vòng, sau đó finalize kèm residual findings.
  - Thêm deterministic `validate_blueprint_coverage` trước critic/finalize để check node/edge labels từ `blueprint.json` so với rendered DOT/sidecar.

- Observability:
  - Log structured metrics mỗi run: model calls, input/output tokens, cache_read, render count, revise count, tool counts, duration.
  - Lưu token summary vào conversation metadata hoặc run artifact để xem lại trong UI/debug.
  - LangSmith tags theo stage: `requirements`, `tech_stack`, `blueprint`, `drawer`, `critic`, `finalize`.

- Internal production hardening:
  - Upload limit: max file size, allowed extensions, max extracted chars.
  - Render timeout giữ hiện tại nhưng thêm cleanup workspace per thread/run để tránh artifact lẫn nhau.
  - CORS default vẫn dev, nhưng Docker/internal prod bắt buộc set `ALLOWED_ORIGINS`.
  - Health endpoint mở rộng thành readiness nhẹ: env key present, Graphviz available, workspace writable, Postgres connected nếu dùng `DATABASE_URL`.

- Eval coverage:
  - Thêm eval cases cho 3 dạng: simple web app, SaaS/POC like current log, complex multi-tier.
  - Acceptance metrics: diagram produced, drawio produced, no missing blueprint nodes, no missing edge labels, critic pass or residual findings recorded.
  - Add token budget regression: fail/warn nếu root run vượt ngưỡng target.

## Test Plan
- Unit tests:
  - `requirements_analyst` brief schema parse.
  - `search_icons` giới hạn tối đa 3 lần cho cùng icon/query/provider và handles misses.
  - `validate_blueprint_coverage` catches missing node/edge labels.
  - upload limits reject oversized/unsupported files.

- Integration tests:
  - Run same JSON-log scenario and compare:
    - no `ls /`, no `glob **/requirements.md`
    - fewer root input tokens
    - drawer and critic still run
    - final output has `out.png` + `out.drawio`
  - Simulate critic `REVISE` then `PASS`.
  - Simulate critic keeps failing; verify max 2 revise loops then final review with residual findings.

- Production smoke:
  - Docker compose up.
  - `/health` readiness passes.
  - Upload doc, approve tech stack, approve blueprint, receive final review.
  - Restart backend with Postgres enabled and confirm conversation resumes.

## Assumptions
- Target is internal production, not public SaaS.
- Main priority is cost + reliability.
- Keep current staged HITL flow.
- Keep drawer and critic subagents.
- Add only one new subagent: `requirements_analyst`.
- Security hardening is internal-grade, not full public abuse prevention.
