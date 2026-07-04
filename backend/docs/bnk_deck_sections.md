# BnK Proposal Deck — Section Spec

Cấu trúc chuẩn của một deck **proposal BnK**, rút ra từ ~10 deck thật trong
`DATA/SLIDE_IMAGES/*/slide_text.json` (Clinic Management, DAMS Phase 2, Driver Safe,
FSD Chat, Maritime ERP, Makalot, Aquila, Ex Umbra…).

Đây là **spec để build agent gen từng phần**. Bản máy-đọc-được nằm ở
[`backend/src/deck_sections.py`](../src/deck_sections.py) (`SECTION_CONTENT_CONTRACTS`) —
file này là bản người-đọc đi kèm; giữ 2 file đồng bộ khi sửa.

---

## 1. Nguyên tắc rút ra từ deck thật

- **Backbone rất nhất quán**: 15–25 slide, 4–6 mục La Mã. Mỗi mục mở đầu bằng 1 slide
  *divider* (`Head Page`, ví dụ `I. Executive Summary`), theo sau là các slide con đặt tên
  `SECTION | Sub-topic` (ví dụ `PROPOSED SOLUTION | Technical Stack`) trên layout `Detail-01`.
- **Luồng chuẩn**:
  ```
  Cover → [Agenda] → I. Executive Summary → II. Success Story
        → III. Solution Proposal (+ Scope of Work + Project Delivery)
        → IV/V. Pricing → [Reference] → Thank you (BnK brand slide)
  ```
- **Mỗi slide = 1 content-contract**: title cố định + danh sách `params` (nội dung cần sinh)
  + `required_inputs` (data phải có, nếu thiếu thì **bỏ slide + cảnh báo**, KHÔNG render slide rỗng).
- **Case study không có layout riêng** trong template — nó chỉ là `Detail-01` + ảnh. Tương tự
  các slide diagram (architecture/data-flow) là ảnh full-width trên layout `Empty`.

## 2. Vì sao slide hiện tại "méo có nội dung"

Pipeline hiện chỉ đọc data thiên về kỹ thuật (`diagram_brief.json` / `tech_stack.json` /
`wbs.json`) do luồng diagram-agent sinh ra. Các mục mà deck BnK thật **luôn có** — Problem
Statement, Success Story, Goals & Value, KPIs, Client Info — **không có field nguồn nào**, nên
`build_deck_plan()` không có chỗ chứa và tầng fallback render ra bullet rỗng. → Cần một artifact
mới `business_narrative.json` + cơ chế skip-and-warn theo từng section (xem `deck_sections.py`).

## 3. Bảng section + param

Trạng thái render:
`ready` = block + data đã có · `new_block` = cần thêm renderer (data đã có/default cố định) ·
`new_block+new_data` = cần cả renderer LẪN data mới từ `business_narrative.json`.

| # | Slide (title thật) | Layout / Block | Params (nội dung cần sinh) | Nguồn data (required_inputs) | Status |
|---|---|---|---|---|---|
| 0 | *(Cover)* | `Cover-01` / cover | project_title, date, client_brand | blueprint.slide_title \| brief.objective | `ready` |
| — | Agenda *(tùy)* | `Detail-01` / agenda | section_list | (dẫn xuất từ outline) | `new_block` |
| 1 | `I. Executive Summary` | `Head Page` / divider | roman | — | structural |
| 2 | `EXECUTIVE SUMMARY \| Overview` | `Detail-01` / bullets | intro_paragraph, key_objectives[3–5] | brief.objective | `ready` |
| 3 | `EXECUTIVE SUMMARY \| Goals & Value Proposition` | `Detail-01` / goals_value | value_props[3–4] (title + sub-bullets) | business_narrative.value_props | `new_block+new_data` |
| 4 | `II. Success Story` | `Head Page` / divider | roman | — | structural |
| 5 | `SUCCESS STORY \| <case>` | `Detail-01` / case_study | case_title, context_paragraph, outcome, image_ref | business_narrative.case_study | `new_block+new_data` |
| 6 | `III. Solution Proposal` | `Head Page` / divider | roman | — | structural |
| 7 | `Solution Proposal <NAME>` | `Overview-01` / bullets | solution_name, subtitle | blueprint | `ready` |
| 8 | `PROPOSED SOLUTION \| Overview` | `Detail-01` / func_nfr | functionality[], non_functionality[] | brief.functional_requirements | `ready` |
| 9 | `PROPOSED SOLUTION \| Feature List` | `Detail-01` / feature_list | features[4–6] (name + description) | brief.functional_requirements | `new_block` |
| 10 | `PROPOSED SOLUTION \| Technical Stack` | `Detail-01` / tech_stack_table | tech_rows (Layer/Tech/Description) | tech_stack.layers | `ready` |
| 11 | `PROPOSED SOLUTION \| Data Flow Architecture` | `Empty` / diagram | diagram_image | out.png | `ready` |
| 12 | `SCOPE OF WORK \| SDLC Phases` | `Detail-01` / sdlc | sdlc_phases (6 phase, in/out scope) | (default template) | `ready` |
| 13 | `SCOPE OF WORK \| Change Request Definition` | `Detail-01` / change_request | change_request_process | (default cố định) | `new_block` |
| 14 | `V. Project Delivery` | `Head Page` / divider | roman | — | structural |
| 15 | `PROJECT DELIVERY \| Estimated Effort` | `Detail-01` / delivery_effort | total_md, effort_rows (Module/MD) | wbs.effort_totals | `ready` |
| 16 | `PROJECT DELIVERY \| Master Plan & Milestones` | `Detail-01` / bullets | timeline_phases (phase + duration) | wbs.timeline | `ready` |
| 17 | `PROJECT DELIVERY \| Risk & Mitigation` | `Detail-01` / risk_table | risks (Risk/Mitigation) | csm.risks | `new_block` |
| 18 | `PROJECT DELIVERY \| Development Methodology` | `Detail-01` / methodology | methodology (Agile/Scrum) | (default cố định) | `new_block` |
| 19 | `PROJECT DELIVERY \| Post-Launch Support` | `Detail-01` / post_launch | sla_process (Ticket→…→Close) | (default cố định) | `new_block` |
| 20 | `PROJECT DELIVERY \| Team Structure` *(tùy)* | `Detail-01` / team | client_team, bnk_team | (default) | `ready` |
| 21 | `IV. Pricing` | `Head Page` / divider | roman | — | structural |
| 22 | `PRICING \| CAPEX` | `Detail-01` / pricing | total_cost, cost_rows, net_note | wbs.effort_totals | `ready` |
| 23 | `PRICING \| OPEX` *(tùy)* | `Detail-01` / opex | opex_rows | tech_stack.opex \| tech_stack.cost | `new_block` |
| 24 | `PRICING \| Payment Milestones` | `Detail-01` / milestones | milestones (30/30/30/10), invoice_terms | (default) | `ready` |
| 25 | `Reference` *(tùy)* | `Head Page` + `Detail-01` | screens (title + ảnh) | mockups | `ready` |
| 26 | *(Thank you / BnK)* | `BnK` / closing | — | template | structural |

### Optional extras (deck thiên tư vấn — Ex Umbra)

| Slide | Block | Params | required_inputs | Status |
|---|---|---|---|---|
| `EXPECTED RESULTS \| KPIs` | kpis | kpis (Module/Metric), business_goals | business_narrative.kpis | `new_block+new_data` |
| `CLIENT \| Overview` | client_info | client_info (client/platform/geo/regulatory) | CSM constraints/assumptions/NFR + wbs.project_info (business_narrative chỉ override) | `new_block` (data đã CSM-derivable, xem §8.5) |
| `ADVICE PHASE \| Overview` | bullets | advice_scope, advice_deliverable | business_narrative.advice_phase | (data only) |

## 4. Trạng thái implement so với `ppt_reporting.py`

- **Đã có (VALID_BLOCKS)**: `bullets`, `tech_stack_table`, `func_nfr`, `sdlc`,
  `delivery_effort`, `pricing`, `milestones`, `team` + layouts `Cover-01` / `Overview-01` /
  `Empty` (diagram) / `BnK` (closing).
- **Cần thêm renderer (11 block)** — `NEW_BLOCKS` trong `deck_sections.py`:
  `agenda`, `goals_value`, `case_study`, `feature_list`, `change_request`, `methodology`,
  `post_launch`, `risk_table`, `opex`, `kpis`, `client_info`.
  - 8 block chỉ cần renderer (data đã CSM-derivable / default cố định): `change_request`,
    `methodology`, `post_launch`, `risk_table`, `opex`, `feature_list`, `agenda`,
    `client_info` (§8.5 — suy từ CSM, `business_narrative` chỉ override).
  - Còn lại cần thêm cả data từ `business_narrative.json`: `goals_value`, `case_study`
    (có thể tự match từ case-library, §8.4), `kpis`.

## 5. `business_narrative.json` — artifact mới cần thu thập upstream

Schema đề xuất (thu thập qua 1 tool `capture_business_narrative` có HITL, tương tự
`propose_diagram_brief`):

```json
{
  "problem_statement": ["..."],
  "value_props": [{"title": "...", "points": ["..."]}],
  "case_study": {"title": "...", "context": "...", "outcome": "...", "image_ref": null},
  "business_goals": ["..."],
  "kpis": [{"module": "...", "metric": "..."}],
  "client_info": {"client": "...", "platform": "...", "geography": "...", "regulatory": "..."},
  "engagement_mode": "development",
  "advice_phase": null
}
```

## 6. Cách agent dùng registry để gen từng phần

```python
from deck_sections import SECTION_CONTENT_CONTRACTS, plannable_contracts, REQUIRED_KEYS

# available = tập input key resolve được cho workspace hiện tại
available = {"brief.objective", "brief.functional_requirements",
             "tech_stack.layers", "wbs.effort_totals", "wbs.timeline", "out.png"}

for contract, missing in plannable_contracts(available):
    if contract.kind != "content":
        emit_structural(contract)               # cover / divider / closing
        continue
    if missing:
        warn(f"skip {contract.key}: thiếu {missing}")   # KHÔNG render slide rỗng
        continue
    # có đủ input → gen đúng params rồi render đúng block
    generate_and_render(contract)               # dùng contract.params + contract.block
```

Nguyên tắc cốt lõi: **thiếu required_inputs → bỏ + cảnh báo, không render slide rỗng** — đây
chính là fix cho lỗi "méo có nội dung". Mỗi section gen/validate độc lập nên lỗi khu trú ở 1
section thay vì hỏng cả outline (khác với `_generate_slide_outline` hiện gọi 1 phát cho cả deck).

## 7. Bước wiring tiếp theo (chưa làm — registry mới chỉ là xương sống)

1. `deck.py`: thêm 4 role mới (`case_study`, `kpis`, `client_info`, `advice`) vào
   `NarrativeRole`; đổi `build_deck_plan()` để lặp `SECTION_CONTENT_CONTRACTS` thay vì chuỗi
   `add(...)` tay; thêm dimension `narrative_gap` trong `validate_deck()`.
2. `ppt_reporting.py`: thêm 11 `NEW_BLOCKS` vào `VALID_BLOCKS` + viết renderer mỗi block
   (mẫu theo `_team_slide` / `_pricing_slide`); cập nhật `_OUTLINE_SYSTEM_PROMPT`.
3. `tools/analysis_tools.py`: thêm tool `capture_business_narrative` (ghi
   `business_narrative.json`); `_refresh_deck_plan()` đọc và truyền vào `build_deck_plan()`.
4. `skills/ppt-generator/SKILL.md`: bổ sung `business_narrative.json` vào bảng context + 5 mục
   section mới.

---

## 8. Worked example — dự án L/C (đã verify trên workspace thật)

Workspace tham chiếu: `artifacts/thread-mr64q5zv-1lz0x` — **L/C & Documentary Trade Management
System** (banking, AWS). Dùng để chứng minh resolver [`deck_resolver.py`](../src/deck_resolver.py)
lấp đầy nội dung từ CSM.

### 8.1 Root cause "méo có nội dung" (quan trọng)

Workspace này **KHÔNG còn** `blueprint.json` / `diagram_brief.json` / `tech_stack.json` /
`deck_plan.json` — toàn bộ data đã gộp vào **`solution_model.prev.json` (CSM)** + `wbs.json` +
`out.slide.json`. Nhưng `ppt_reporting._build_outline_context()` / `assemble_report_data()` /
SKILL cũ **đọc thẳng các file legacy đã biến mất** ⇒ context rỗng ⇒ slide rỗng, **dù data thật
rất giàu**. `deck_resolver.py` sửa gốc: đọc CSM/WBS/out.slide.json thay vì file legacy.

### 8.2 Map data thật → slide (đã chạy resolver)

| Slide | Nội dung resolver trả ra | Nguồn |
|---|---|---|
| Cover | "L/C & Documentary Trade Management System" / "Banking-Grade Trade Finance Platform on AWS" | `out.slide.json` |
| Exec Summary \| Overview | intro + 10 mục tiêu (L/C lifecycle, SWIFT MT700/734/740/799/202, sanctions, AI discrepancy UCP 600) | CSM requirements |
| Proposed Solution \| Technical Stack | **8 layer / 35 component**: Client&Edge, App Services, AI/Doc (Textract, Comprehend, SageMaker), Data (Aurora, Redis, OpenSearch, S3/Glacier), SWIFT, Security, Observability | CSM components-by-cluster |
| Architecture | `out.png` | out.slide.json |
| Delivery \| Estimated Effort | **Total 1060.56 MD (~48.21 MM)** + 11 module (Core LC 170.94, AI/ML 197.12…) | wbs.effort_totals + effort_by_module |
| Delivery \| Master Plan | 64 weeks / 16 months / 32 sprints | wbs.timeline |
| Delivery \| Risk & Mitigation | **20 risk có mitigation** (Ant Design→code splitting; JVM cold start→GraalVM; Aurora 7-yr→Glacier…) | CSM risks |
| Delivery \| Team | PM 90.96 MD, Dev 726 MD (~2.27 HC), BA 69.9, QC 173.7 | wbs.team_composition |
| Pricing \| Milestones | Contract Signoff → Requirement/BRD → Dev+UAT → UAT complete → Post-Launch | wbs.milestones |
| **Success Story** | tự match **BCA Finance (banking)** từ case-library | `pick_case_study(model, library)` |

### 8.3 Kết quả `plannable_contracts()` — kiểm chứng

Sau khi thêm `_infer_client_info()` (client_info suy từ CSM, không cần `business_narrative`)
và rate-card CAPEX (§8.6), demo thật đã render **27 slide**, chỉ còn **3 slide** thiếu data
đúng nghĩa business: `exec_summary_goals_value`, `kpis`, `advice_phase` → cần
`business_narrative.json`.

Đây chính là bằng chứng lỗi "méo có nội dung" đã hết: **thiếu data thì skip + cảnh báo, không
render slide rỗng**; phần lớn slide được lấp đầy tự động từ CSM/WBS. Deck demo đã lưu tại
`artifacts/thread-mr64q5zv-1lz0x/out.pptx` (script sinh: xem §8.7).

### 8.4 case_study — bóc từ kho dự án cũ

`backend/scripts/build_case_library.py` parse 62 file `DATA/SLIDE_IMAGES/*/analysis.md` →
`backend/data/case_library.json` (57 case, bỏ 5 file introduction/manual/kick-off). Mỗi entry:
`title / client / domain[] / tech[] / problem / solution / outcome / image_ref`.
`pick_case_study(model, library)` chấm điểm overlap tech/domain giữa CSM hiện tại và từng case,
chọn top-1 (domain nhân đôi trọng số). Dự án L/C → **BCA Finance**. Chạy lại script để refresh
khi thêm deck mới vào `DATA/SLIDE_IMAGES/`.

### 8.5 client_info từ CSM (không cần business_narrative cho case phổ biến)

`deck_resolver._infer_client_info(model, wbs)` suy `client_info` thẳng từ CSM/WBS, KHÔNG
cần đợi `business_narrative.json`:
- `client` / `business_domain` ← `wbs.project_info` (đã có sẵn từ lúc khởi tạo dự án)
- `geography` ← constraints/assumptions chứa từ khóa vùng miền (Singapore, Vietnam,
  ap-southeast, APAC, EU…)
- `regulatory` ← NFR requirements chứa từ khóa compliance (PCI-DSS, UCP 600, AML, KYC,
  GDPR, HIPAA…)
- `platform` ← assumptions dạng "Existing … infrastructure/platform to integrate with"

`business_narrative.client_info` (nếu có) chỉ **override/bổ sung** những field CSM chưa suy
ra được — không phải nguồn bắt buộc.

### 8.6 Rate card CAPEX — lấy đúng từ sheet `4. Master Data` của WBS Excel

Template WBS Excel (`backend/src/data/wbs_template.xlsx`) đã có sẵn cột **Rate** ở
`4. Master Data!C11:C14` (PM / BA / Developer / QC) mà `1. Effort` sheet nhân thẳng vào MD
(`K6 = E6 * 'Master Data'!$C$13`) — nghĩa là các ô này phải là **giá theo NGÀY**, không phải
theo tháng. Trước đây các ô này để trống trong template.

`wbs_effort.DEFAULT_RATE_CARD_USD_PER_MONTH` (2,000–4,000 USD/tháng tùy role/trình độ:
PM 4000, BE 3200, FE/Mobile 2800, BA 2600, QC 2200, Developer blended 3000) +
`rate_per_manday()` quy đổi tháng→ngày dùng **`RATE_CARD_WORKDAYS_PER_MONTH = 20`**
— **khác với `MANDAYS_PER_MONTH = 22`** dùng cho tính man-month ở chỗ khác. Đừng nhầm lẫn
2 hằng số này.

- `wbs_effort.rollup()` giờ luôn kèm `cost_by_role_usd` + `total_cost_usd` +
  `rate_card_usd_per_month` vào `effort_totals` — mọi WBS rollup mới đều có cost sẵn.
- `wbs_excel._write_master_data_rate_card()` ghi rate/ngày vào `4. Master Data!C11:C14` của
  file Excel thật khi build (`build_wbs_workbook`), Developer = rate blended (BE+FE/Mobile
  gộp chung 1 rate, đúng theo cấu trúc template — template chỉ có 1 dòng "Developer").
- `deck_resolver._b_capex` dùng `effort_totals.cost_by_role_usd`/`total_cost_usd` nếu có,
  fallback tính tại chỗ từ `effort_by_role` + rate card — CAPEX **luôn** derive được từ WBS,
  không bao giờ bị chặn vì thiếu `business_narrative`.

Verify trên dự án L/C: **Total Cost: 157,826 USD (NET)** (1060.56 MD ở rate mặc định).

### 8.7 Cách gọi (cho agent gen từng phần)

```python
import json
import deck_resolver as R
import deck_sections as S
from csm import SolutionModel

model = SolutionModel.model_validate(json.load(open("solution_model.json", encoding="utf-8")))
wbs   = json.load(open("wbs.json", encoding="utf-8"))
meta  = json.load(open("out.slide.json", encoding="utf-8"))   # title/kicker/brand/png
nar   = json.load(open("business_narrative.json", encoding="utf-8"))  # optional
lib   = json.load(open("backend/data/case_library.json", encoding="utf-8"))

avail = R.available_inputs(model, wbs, narrative=nar, meta=meta, has_diagram=True)
for contract, missing in S.plannable_contracts(avail):
    if contract.kind != "content":
        continue                       # cover / divider / closing: render structural
    if missing:
        warn(f"skip {contract.key}: thiếu {missing}")   # KHÔNG render slide rỗng
        continue
    params = R.csm_to_slide_params(model, wbs, contract, narrative=nar, meta=meta, library=lib)
    render_block(contract.block, params)   # gen đúng block với params đã map
```
