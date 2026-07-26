# Gotchas

Mỗi mục là một cái bẫy đã cắn thật ít nhất một lần. Format: **hiện tượng → nguyên nhân → đúng/sai**.
Mắc lỗi mới vì một đặc thù không hiển nhiên? Thêm một mục.

---

## Môi trường & build

### `pytest` chết với `modal.exception.AuthError: Token missing`
- **Nguyên nhân:** `SANDBOX_PROVIDER` mặc định là `modal`; test nào có monkeypatch không còn chặn đúng chỗ sẽ gọi runner thật.
- **Đúng:** `SANDBOX_PROVIDER=local` khi chạy test cục bộ (chỉ hợp lệ khi `APP_ENV != production`), hoặc cấp `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET`.
- **Sai:** sửa test cho nó skip.

### Render qua Modal treo ~300s rồi fail, nhưng chỉ khi chạy trong Docker
- **Nguyên nhân:** DNS proxy nhúng của Docker (127.0.0.11) xử lý sai zone `task-<id>.w.modal.host` (DNSSEC, TTL 60s).
- **Đúng:** giữ `dns: [8.8.8.8, 1.1.1.1]` trên service `backend` trong `docker-compose.yml`.
- **Sai:** xoá dòng đó vì "trông thừa".

### Backend không ghi được `./artifacts/<thread>` trong Docker
- **Nguyên nhân:** Docker Desktop trình bày bind mount bên trong container là `0:0` bất kể quyền trên host, nên `user: 1000:1000` không bao giờ khớp.
- **Đúng:** giữ service một-lần `artifacts-init` (busybox `chmod 777 /app/artifacts`) chạy trước backend.
- **Sai:** xoá service đó → workspace theo thread hỏng.

### API key nằm trong Docker image
- **Nguyên nhân:** `.gitignore` **không** bảo vệ Docker build. Thiếu/hồi quy `.dockerignore` là `backend/.env` vào mọi layer, đọc được bằng `docker save` kể cả image chưa từng push.
- **Đúng:** giữ assertion trong `.github/workflows/ci.yml` (`docker run … test -f /app/backend/.env` phải fail build).
- **Sai:** tắt check cho nhanh.

### `uv sync` âm thầm resolve lại lockfile cũ
- **Nguyên nhân:** CI từng dùng `uv sync --frozen || uv sync`, che việc pytest/ruff/pyright không được khai trong `uv.lock`.
- **Đúng:** chỉ `uv sync --frozen`. Lockfile cũ **phải** làm đỏ CI.

### `find_similar_solutions` trả `status: "ERROR"` mà không ai để ý
- **Nguyên nhân:** service `qdrant` đang bị comment trong `docker-compose.yml`. Tool bắt lỗi và trả "Proceed without BnK past-project references" — **suy giảm chất lượng trong im lặng**, không crash.
- **Đúng:** khi cần RAG thì bật lại service + `QDRANT_URL`, và kiểm tra `status` chứ đừng chỉ nhìn có kết quả hay không.

### Git log toàn commit bạn không tạo
- **Nguyên nhân:** hook `PostToolUse` trong `.claude/settings.json` tự `git add` + `git commit -m "auto: update <file>"` sau **mọi** lần sửa `.py/.ts/.tsx/.js/.jsx/.json/.yaml/.yml/.toml/.sh`.
- **Đúng:** biết trước điều này khi làm việc theo nhánh; file `.md` không bị hook.

---

## Import & đóng gói

### `import wbs_tools` chạy được nhưng đường dẫn file lại là `domain/wbs/wbs_tools.py`
- **Nguyên nhân:** `pyproject.toml` đặt `[tool.hatch.build] sources = ["src"]`, và `[tool.pytest.ini_options].pythonpath` thêm `src` cùng `src/domain/{diagram,deck,reporting,wbs,validation}`. Repo import module domain bằng **tên phẳng top-level**.
- **Đúng:** thêm subpackage `domain/` mới thì thêm vào **cả** `pythonpath` **và** `[tool.pyright].extraPaths`.
- **Sai:** đổi sang import theo package rồi ngạc nhiên vì pytest không collect được.

### Test bắt đầu fail sau khi "dọn dẹp" `backends.py`
- **Nguyên nhân:** test suite monkeypatch trực tiếp `backends.WORKSPACE` / `backends._current_workspace`. Biến nó thành shim re-export là tách đôi module globals, patch mất tác dụng trong im lặng.
- **Đúng:** `backends.py` phải ở lại là module thật, top-level. `_current_workspace` ContextVar chỉ được định nghĩa ở **đúng một** module — hai bản là rò rỉ workspace chéo thread.

### Sửa `backend/src/agent.py` mà không thấy gì thay đổi
- **Nguyên nhân:** file đó không nên tồn tại. Nó đã được thay bằng package `agent/`; một `agent.py` phẳng sẽ **che** package và trở thành code chết.
- **Đúng:** sửa trong `agent/`. Test canh: `tests/test_no_legacy_agent_module.py`.

### Monkeypatch `create_deep_agent` không ăn
- **Nguyên nhân:** `build_agent` resolve nó qua module globals của chính nó.
- **Đúng:** patch `agent.builder.create_deep_agent`, không phải `agent.create_deep_agent`.

### Sửa `src/config.py` hoặc `src/runtime/backends.py` mà không có hiệu lực
- **Nguyên nhân:** cả hai là **code chết**. Package `src/config/` che `src/config.py`; `src/runtime/backends.py` là bản sao cũ của `src/backends.py` và không ai import.
- **Đúng:** sửa `src/config/` và `src/backends.py`.

---

## Agent & token

### Một run đốt hàng triệu token qua subagent
- **Nguyên nhân:** `create_deep_agent()` **âm thầm** thêm subagent `general-purpose` + tool `task` cho mọi agent. Một render fail làm drawer retry qua `task(general-purpose)` ba lần — agent lồng nhau, không state, không trần call. Đo được 1.66M token = 42% của một run 4M. Một trace 6M khác cho thấy `wbs_planner` làm y hệt.
- **Đúng:** `_set_general_purpose_enabled(False, ...)` cho **mọi** model lúc build (`agent/harness.py`). Test canh: `tests/test_general_purpose_disabled.py`.

### Subagent phá luật trong prompt và sửa file bị cấm
- **Nguyên nhân:** **mọi** subagent deepagents nhận đủ filesystem toolset bất kể `tools` khai báo. `icon_resolver` từng đốt ~40 call / ~1M token với 32× `edit_file` trên `icon_plan.json` dù prompt cấm rõ ràng.
- **Đúng:** `FilesystemPermission(operations=["write"], paths=[...], mode="deny")`.
- **Sai:** viết luật cấm to hơn trong prompt.

### Drawer chạy thêm một vòng sau khi critic nói REVISE
- **Nguyên nhân:** luật "một pass" chỉ nằm trong prompt.
- **Đúng:** `DrawerReviseGateMiddleware` chặn `task(drawer)` nếu chưa có ToolMessage `finalize_diagram` **sau** lần `task(critic)` gần nhất; `CRITIC_REVISION_HARD_CAP = 2`.

### Context không bao giờ co lại dù đã bật context editing
- **Nguyên nhân:** `ClearToolUsesEdit.apply()` dừng ngay khi thu hồi đủ `clear_at_least` token; edit là ephemeral, tính lại từ checkpoint đầy đủ mỗi call, nên giá trị nhỏ chỉ gọt được một lát ở đầu và sàn context leo mãi.
- **Đúng:** `clear_at_least=1_000_000, keep=4` — vô lý một cách cố ý để lần nào cũng dọn sạch ngoài `keep`.

### Ảnh render "tàng hình" với context editing
- **Nguyên nhân:** `count_tokens_approximately` định giá một ảnh cố định **85 token**, trong khi JPEG 800px thật sự tốn 7–27K qua Responses API.
- **Đúng:** `KeepLatestImagesEdit` (phải chạy **trước** `InjectVisionAsUserEdit`) + `INSPECT_MAX_WIDTH = 800`.

### `GraphRecursionError` không có suy giảm mềm
- **Nguyên nhân:** `RECURSION_LIMIT` dùng **chung** cho main + mọi subagent được `task` gọi. Main 46 call + icon_resolver 34 đã ~160 bước.
- **Đúng:** giữ `RECURSION_LIMIT = 450` và dựa vào `ModelCallLimitMiddleware` theo agent làm trần mềm.

### Một bước bị bỏ qua thì biến mất vĩnh viễn
- **Nguyên nhân:** phase machine "phase tiến xa nhất thắng". Có `wbs.json` là phase = `wbs`, và `propose_diagram_brief`/`propose_tech_stack`/`propose_blueprint` biến khỏi tool list mãi mãi → deck rỗng ở cuối.
- **Đúng:** `_ARTIFACT_BACKFILL_TOOLS` / `_missing_artifact_tools` giữ tool sản xuất còn sống khi file của nó chưa có; `_pending_gate_tools` giữ tool sống để gate đang hiện sửa lại được.

### `LLMToolSelectorMiddleware` crash trước cả khi gọi model
- **Nguyên nhân:** phase filter đã bỏ bớt tool, langchain validate `always_include` trên danh sách **đã lọc**, nên entry tĩnh như `finalize_diagram` raise.
- **Đúng:** `SafeLLMToolSelectorMiddleware` giao (intersect) `always_include` với tool khả dụng theo từng request.

### Đổi model sang provider có prompt caching mà không nhanh hơn
- **Nguyên nhân:** `PhasePromptFilterMiddleware` làm system prompt **biến thiên theo phase** (tiết kiệm ~2.5–3K token/lượt) — điều đó phá sạch cache prefix.
- **Đúng:** khi dùng provider có caching, tắt cả phase prompt filter lẫn tool filter và giữ prompt ổn định byte.

### mimo trả free text thay vì gọi tool
- **Nguyên nhân:** mimo stringify arg kiểu dict/list và không hỗ trợ structured output; thiếu `supports_structured_output: false` thì tool selector trả `KeyError 'tools'`. mimo cũng 400 khi gặp image block trong tool message (`vision_in_tools: false`) và cần field `text` trên **mọi** content block, kể cả `image_url`.
- **Đúng:** giữ cấu hình đó trong `config.yaml`; coercion ở `tool_coercion.py` + `schemas/coercion.py`.

### `ppt_generator` báo 404 hàng loạt khi đọc file
- **Nguyên nhân:** prompt bake đường dẫn host tuyệt đối. Với `virtual_mode=True`, filesystem tool re-root mọi path dưới `current_workspace()` → path tuyệt đối thành thư mục lồng không tồn tại.
- **Đúng:** prompt chỉ dùng root ảo `/workspace`.

### Một tin nhắn tiếp nối bình thường xoá sạch dự án
- **Nguyên nhân:** `clear_stage_markers()` xoá `tech_stack.json`/`blueprint.json`/`solution_model.json` giữa chừng vì tin nhắn không khớp danh sách keyword.
- **Đúng:** backstop `preserve_existing_project = solution_exists and not attached`. Thêm intent follow-up mới thì **mở rộng backstop**, đừng thêm danh sách keyword thứ hai.

---

## WBS & Excel

### Số trong Excel khác số trong `wbs.json`
- **Nguyên nhân:** `wbs_excel.py` clone template và **giữ công thức sống** trỏ vào sheet `4. Master Data`. Mô hình effort được mã hoá hai lần.
- **Đúng:** đổi ratio ở Python thì đổi cả ô tương ứng trong `backend/src/data/wbs_template.xlsx`.

### BA/QC/PM ra số lạ
- **Nguyên nhân:** ai đó ước lượng tay. Chúng là **derived**; `apply_wbs_reestimate` cố tình bỏ qua và ghi đè mọi `qc`/`pm`/`total` do script ghi.
- **Đúng:** chỉ ước lượng `be/fe/mobile/ai` (+ `ba` khi `phase_type=="requirement"`).

### `apply_wbs_reestimate` không đổi gì
- **Nguyên nhân:** truyền `source_file="wbs.json"`.
- **Đúng:** `source_file` phải là file **mới** do một lần `run_python` trước đó ghi ra.

### Đổi tên dự án cho đẹp làm mất WBS đang làm dở
- **Nguyên nhân:** guard reset dự án cũ so tên theo byte.
- **Đúng:** `_reset_if_stale_project` so qua `_norm_project_name` (bỏ dấu, bỏ dấu câu, bỏ khoảng trắng thừa) — "BnK Clinic" / "bnk  clinic!" / "BnK Clínic" không kích hoạt reset.

### Chi phí lệch đúng 10%
- **Nguyên nhân:** trộn `MANDAYS_PER_MONTH = 22.0` (lịch) với `RATE_CARD_WORKDAYS_PER_MONTH = 20.0` (tiền). **Hai hằng số này cố ý khác nhau.**

---

## Sơ đồ & draw.io

### Sơ đồ chật cứng vẫn báo PASS
- **Nguyên nhân:** trước đây chỉ chấm `total >= 85`.
- **Đúng:** va chạm card giờ là **hard block** trong `production_scorecard`. Lưu ý `dense_fallback` **không** phải hard block — nó trừ 4 điểm composition.

### Đặt `zone` nhưng chẳng vẽ ra gì
- **Nguyên nhân:** thiếu chuỗi parent `cloud > vpc > (subnet_public|subnet_private) > az`. Cluster phẳng có `zone` bị bỏ qua **im lặng**.

### Đặt `style_preset="refined"` mà vẫn ra look icon cũ
- **Nguyên nhân:** topology `hub_spoke`/`hierarchy`/`mesh` **luôn** render preset `icon` — chưa có layout refined cho chúng. `sequence`/`hybrid` thì kết hợp được với refined.

### Sơ đồ BPMN trượt gate dù trông đúng
- **Nguyên nhân:** chấm bằng profile architecture (icon/zone/ratio) trên một sơ đồ không có icon/zone.
- **Đúng:** BPMN dùng profile `bpmn` riêng trong `production_scorecard`.

### Query "API Gateway" trả về shape BPMN
- **Nguyên nhân:** catalog `bpmn_*` lẫn vào tìm kiếm chung.
- **Đúng:** bỏ qua stencil `bpmn_*` trong `search_icon`/`_resolve_node_icon` trừ khi query bắt đầu bằng "bpmn".

### Sơ đồ sequence/ERD ghi đè sơ đồ kiến trúc
- **Nguyên nhân:** `render_typed_diagram` ghi vào cùng `out.png`.
- **Đúng:** snapshot bằng `finalize_diagram(kind="sequence"|"erd"|…)` vào `diagram_manifest.json`.

### Vòng lặp fix→render không dứt
- **Nguyên nhân:** đuổi theo cảnh báo audit không thể giải quyết hết. Đây là lý do #1 chạm trần run limit.
- **Đúng:** tôn trọng `RENDER_SOFT_CAP=3` / `RENDER_HARD_CAP=6`. Lưu ý hard cap **không** phủ `export_drawio`.

### `refined_theme.py` dùng hex trần thay vì `light-dark()`
- **Nguyên nhân:** cố ý. Recipe refined vẽ nền trắng tường minh nên dark-mode vô nghĩa, và hex trần port được sang renderer không phải draw.io.
- **Sai:** "sửa" cho giống `theme.py`.

### Mũi tên xuyên qua tiêu đề card
- **Nguyên nhân:** z-order sai.
- **Đúng:** giữ thứ tự `Z_CONTAINER 0 < Z_EDGE 10 < Z_SHADOW 20 < Z_NODE 30 < Z_FORE 40 < Z_CHROME 50` (`native/builder.py`).

### `layout_intent="grid"` cho ra sơ đồ rối
- **Nguyên nhân:** nó là **thử nghiệm** — cạnh xuyên band bị rối và phí chỗ. Opt-in có chủ đích thôi.

### Output sandbox được tin tưởng quá sớm
- **Nguyên nhân:** run thành công ≠ output an toàn.
- **Đúng:** `.drawio`/SVG/DOT/tên file/stdout do sandbox sinh **phải** được validate trước khi phục vụ, nhúng vào PDF, hay import vào draw.io.

---

## PDF & deck

### Báo cáo 13 trang bỗng còn 3 trang
- **Nguyên nhân:** LLM truyền `include_sections` cụt, và `normalize_sections` từng **bỏ tên không nhận diện được trong im lặng** (`"tech_stack"` ≠ `"techstack"`).
- **Đúng:** gọi `generate_pdf_report({})` / `generate_ppt_proposal({})` **không tham số**. Giờ tên lạ ra WARNING và >50% rác thì rơi về default.

### "Slide không có nội dung"
- **Nguyên nhân:** `build_deck_plan` đọc JSON chỉ có dữ liệu kiến trúc, thiếu hẳn field tự sự nghiệp vụ (problem statement, success story, goals & value, KPI, thông tin khách).
- **Đúng:** registry phải **bỏ qua và cảnh báo, không bao giờ render slide rỗng**.

### Sửa `deck_sections.py` nhưng deck không đổi
- **Nguyên nhân:** header file ghi rõ "Wiring (spec — not yet applied)". Block gắn `new_block`/`new_block+new_data` **chưa có renderer**; `IMPLEMENTED_BLOCKS` mới là tập thật sự chạy.

### Sửa `improvement/README_IMPROVE.md` nhưng review vẫn nói cái cũ
- **Nguyên nhân:** `improvement/README_IMPROVE.md` và `improvement/diagram_code_agent_review.md` **giống nhau từng byte**. Sửa một cái là hai file phân kỳ.

---

## Tài liệu

### `README.MD` ở root mâu thuẫn với code
- **Nguyên nhân:** nó auto-generated và đã cũ — mô tả `backend/src/diagram_mcp/`, `agent.py`, `tools.py`, `RECURSION_LIMIT = 160`, 4 gate. Thực tế: `backend/src/server.py`, package `agent/`, 450, 13 gate.
- **Đúng:** coi `AGENTS.md` + `docs/` là contract. Đừng trích README như nguồn sự thật.
