# Domain Glossary

Từ vựng nghiệp vụ của hệ thống. Hiểu sai ngữ nghĩa ở đây là loại bug khó phát hiện nhất — code vẫn chạy, kết quả vẫn "trông đúng", chỉ là sai nghĩa.
Schema chi tiết: `data-contracts.md`.

---

## 1. Pipeline — mỗi mục là một file JSON trong workspace của thread

| Thuật ngữ | Định nghĩa ở | Nghĩa thật |
|---|---|---|
| **workspace** | `backend/src/backends.py` | Thư mục artifact **theo thread**. Mặc định `backend/agent_space/workspaces/<thread_id>`; trong Docker là `ARTIFACTS_DIR/<thread_id>`. Thread `thread-default` rơi về workspace dùng chung. |
| **brief** (`diagram_brief.json`) | `tools/schemas/brief.py` | Phát biểu *sơ đồ phải truyền đạt điều gì*, viết **trước** tech stack và blueprint. Gồm `diagram_kind`, mục tiêu, loại ứng dụng, tín hiệu scale/security/provider, FR/NFR, ràng buộc layout, giả định. Không phải gate. |
| **tech stack** (`tech_stack.json`) | `tools/schemas/tech_stack.py` | Lựa chọn công nghệ theo lớp, kèm `cost_tier`, chi phí/tháng ước tính, capacity sizing, 1–5 tiêu chí quyết định, phương án thay thế + `why_rejected`, `SolutionAssumptions` (budget tier, MAU/DAU/peak RPS, compliance) và `scaling_roadmap`. **Gate.** |
| **blueprint** (`blueprint.json`) | `tools/schemas/blueprint.py` | Kiến trúc có cấu trúc: nodes / clusters / edges + pattern + key decisions + phủ WAF pillar + mapping NFR + legend + chrome slide. Là **nguồn sự thật** cho render, deck và WBS. **Gate.** |
| **CSM / Canonical Solution Model** (`solution_model.json`) | `memory/stores/csm.py` | Mô hình miền trung tâm có ID (`REQ-`, `CON-`, `ASM-`, `DEC-`, `COMP-`, `RISK-`, `WBS-`, `EVD-`, `CTRL-`, `SLIDE-`…). Các artifact là **phép chiếu** của nó; `csm_adapter.py` dựng CSM từ các file JSON. Mỗi lần duyệt gate thì snapshot thành `approved/REV-<n>.json`. |
| **deck plan** (`deck_plan.json`) | `domain/deck/deck.py` | Storyboard PPT được duyệt trước khi render. Mỗi slide neo vào entity CSM qua `source_refs`. **Gate.** |
| **WBS** | `domain/wbs/` | Work Breakdown Structure kiểu BnK. Cấp bậc là **phase → module → (group) → leaf feature**. Hệ thống này **không** dùng từ "activity". |
| **case study** (`backend/data/case_library.json`) | `scripts/build_case_library.py` | Bản digest thuần tự sự của các deck đề xuất BnK cũ. Dùng để điền slide SUCCESS STORY. Corpus cũ, giữ cho fallback keyword. |
| **solution memory** (`backend/data/solution_memory.json`) | `scripts/build_solution_memory.py`, `rag/solution_memory.py` | Corpus **hợp nhất**: tự sự case study **ghép với số liệu WBS thật** (effort MD, tech, khung module) khi có join cùng-dự-án do LLM xác nhận. Một hit trả lời được cả "đã giải bài toán gì" lẫn "tốn bao nhiêu". Index vào Qdrant collection `bnk_solutions`. |
| **effort norms** (`EFFORT_NORMS`) | `domain/wbs/wbs_tools.py`; bản cho người đọc: `backend/skills/wbs-planning/reference/effort-norms.md` | Bảng 30 mục benchmark **khoảng man-day dev theo loại feature** (`login_auth_web`, `crud_list`, `workflow_approval`, `ai_finetune_sft`…), rút từ ~50 file WBS thật của BnK. Tool `get_effort_norms()`. |
| **gate** | `tools/__init__.py` | Tool bị bọc `interrupt_on` — run dừng lại, frontend hiện thẻ duyệt. 16 gate. Xem `agent-design.md` §4. |
| **finding** | `domain/diagram/findings.py`, `domain/validation/solution_validator.py` | Khiếm khuyết có cấu trúc: severity (`low|medium|high|critical`), confidence, `dimension`, `repair_strategy`. `BLOCKING_SEVERITY = "high"`. Finding thẩm mỹ **không bao giờ** chặn. |
| **evidence** | `memory/stores/evidence.py` | Một khẳng định có nguồn: claim + URL + `fetched_at` + confidence, append-only, chiếu vào CSM qua link `supports`. Là thứ cho phép nói "SOC 2 ready" mà không bịa. |
| **compliance pack** | `compliance/packs/*.json` | Khai báo các control mà một chuẩn yêu cầu; `apply_pack` sinh entity `Control` và nối link `implements`/`mitigates`. |
| **reality sync / drift** | `domain/reporting/reality_sync.py` | Nạp repo/Terraform/k8s/compose/OpenAPI thật vào `current_state_model.json`, diff với CSM mong muốn → `drift_report.json` (designed-not-built / built-not-designed / matched). |
| **epistemic summary** | `csm.SolutionModel.epistemic_summary()` | Phần in ra ở **mọi gate**: cái gì đã biết chắc, cái gì là giả định cần xác nhận (`must_confirm`/`should_confirm`/`nice_to_confirm`), quyết định còn treo, ràng buộc. |
| **artifact (frontend)** | `frontend/src/lib/artifacts.ts`, `runtime/src/artifact-substitution.ts` | `ArtifactRef = {__artifact, mime, filename}` — con trỏ thay cho 4 field base64 lớn. `drawio` **không** bị thay vì cần nguyên văn trong URL fragment mở draw.io. |
| **stage marker / budget** | `tools/stage_markers.py` | Các file JSON đếm nhỏ trong workspace ép thứ tự và trần: `render_count.json`, `web_search_budget.json`, `pending_gate.json`… |

---

## 2. Từ vựng WBS

**Hai bộ role tồn tại song song, tuyệt đối không trộn:**

- `domain/wbs/wbs_schema.py::ROLE_ALIASES` — 5 key cho WBS **nhập từ file lịch sử**: `be_coding`, `fe_mobile_coding`, `requirement_analysis`, `testing`, `project_management` (map ~60 biến thể nhãn thô; không map được thì rơi về `be_coding`).
- `domain/wbs/wbs_effort.py` — 6 key cho WBS **do agent sinh**: `be`, `fe`, `mobile`, `ai`, `ba`, `qc`, `pm`; gom về 5 cột của template qua `to_wbs_columns()` (`be | fe_mobile | ba | qc | pm`), trong đó fe + mobile + ai đều rơi vào `fe_mobile`.

| Thuật ngữ | Nghĩa |
|---|---|
| **phase_type** | Cổng vai trò cho một leaf: `development` (dev+BA+QC+PM), `requirement` (BA+PM), `design` (BE+PM), `uiux` (FE+PM), `deployment` (BE, PM=0), `support` |
| **ratio model / overhead BnK** | `ba_on_dev=0.10`, `qc_on_dev=0.30`, `pm_on_total=0.10` (trên dev+BA+QC) → tổng ≈ **1.54 × dev**. Đúng bằng ô C4/C5/C7 sheet `4. Master Data` của workbook |
| **rate card** | PM 4000 / BE 3200 / FE_Mobile 2800 / BA 2600 / QC 2200 / Developer 3000 USD **mỗi man-month** |
| **20 vs 22 ngày công** | `MANDAYS_PER_MONTH = 22.0` cho lịch/man-month; `RATE_CARD_WORKDAYS_PER_MONTH = 20.0` cho tiền. **Cố ý khác nhau** — trộn là sai giá 10% |
| **PERT** | `optimistic/likely/pessimistic` → `pert_expected_md`, `pert_p50_md`, `pert_p80_md`. **Chỉ phục vụ lập lịch**, không nuôi mô hình effort/ratio |
| **CPM** | `critical_path()` — FS/SS/FF + lag, trả `float_md` và `critical`. Chu trình phụ thuộc thì **suy giảm thành "không có thông tin float"**, không raise |

---

## 3. Từ vựng sơ đồ

| Thuật ngữ | Nghĩa |
|---|---|
| **diagram kind** | `architecture`, `bpmn`, `sequence`, `erd`, `state_machine`, `c4` (+ `deployment`, `code_map` placeholder) |
| **preset** (`style_preset`) | **`refined`** — mặc định cho architecture: look tài liệu phẳng kiểu playbook, 1920×1080, zone trung tính + ≤3 hue nhấn, icon màu đầy đủ. **`icon`** — look AWS stencil cũ, bị **ép** cho topology `hub_spoke`/`hierarchy`/`mesh`. **`bpmn`** — swimlane pool, chấm theo profile riêng |
| **native engine** | `prettygraph/native/` — builder spec→.drawio tất định, **0 token LLM**. Đối lập với đường Graphviz cũ (`diagram.py` + `gv_to_drawio.py`) nay chỉ còn cho codegen (C4, poster) |
| **zone** | `BPCluster.zone` — kiểu ranh giới topology có lồng nhau thật: `cloud|vpc|subnet_public|subnet_private|az|onprem`. Rỗng = tier logic (vẽ thành dải màu). Khác với `tier`/`accent`. Cần chuỗi `parent` đầy đủ mới vẽ ra |
| **engineer loop / auto_repair** | `native/repair.py` — dựng ≤6 phương án layout, chấm từng cái bằng validator + scorecard, giữ cái thắng; luôn giữ một baseline "unplanned" làm sàn. Ghi `engineer_report.json` |
| **scorecard** (`production_scorecard`) | Điểm QA 0–100 trên 8 chiều có trọng số. **PASS khi và chỉ khi** total ≥85 **và** node_recall=1 **và** edge_recall=1 **và** 0 lỗi XML **và** 0 va chạm card **và** `arrow_clarity_score` ≥75 |
| **layout_intent** | Gợi ý bố cục, gồm cả topology: `hub_spoke|hierarchy|mesh|sequence|hybrid`. `grid` là **thử nghiệm**, opt-in |
| **density** | `standard|detailed|poster`, mặc định `detailed` |

---

## 4. Từ vựng deck

| Thuật ngữ | Nghĩa |
|---|---|
| **section contract** | `domain/deck/deck_sections.py` — khai báo từng section chuẩn của deck BnK: layout, block, nguồn dữ liệu, param bắt buộc, `status` (`ready` / `new_block` / `new_block+new_data` / `structural`). Bản song sinh cho người đọc: `backend/docs/bnk_deck_sections.md` — **sửa một thì sửa cả hai** |
| **layout** | Tên layout trong template PPTX BnK: `Cover-01`, `Head Page`, `Head-01`, `Detail-01`, `Overview-01`, `Empty`, `BnK`, `"C2 -  Separator/ Dark"` (chú ý **hai dấu cách** trong cái cuối) |
| **block** | Bộ render nội dung một slide: `bullets`, `tech_stack_table`, `func_nfr`, `sdlc`, `delivery_effort`, `pricing`, `milestones`, `team`, `gantt`, `case_study`, `wbs_detail_image`, `diagram_image` |
| **narrative_role** | Vai trò của slide trong mạch kể (problem / approach / proof / ask…) — dùng để chọn case study và kiểm tra mạch |

Quy tắc của registry: **bỏ qua và cảnh báo, không bao giờ render slide rỗng.**
