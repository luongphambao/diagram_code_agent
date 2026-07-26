# Data Contracts

Hình dạng dữ liệu chảy qua pipeline. Đây là **contract**, không phải mô tả code — đổi field ở đây là breaking change cho mọi stage phía sau.
Ngữ nghĩa từng thuật ngữ: `domain-glossary.md`. Code là nguồn sự thật cuối cùng; file này ghi *tên field và bất biến*, không ghi chữ ký hàm.

---

## 1. `diagram_brief.json` — `DiagramBrief`
`tools/schemas/brief.py`

```
diagram_kind, objective, application_type, scale_level, security_level,
provider_preference, analysis_signals[], stakeholders[],
functional_requirements[], non_functional_requirements[],
layout_constraints[], assumptions[]
```

---

## 2. `tech_stack.json`
`tools/schemas/tech_stack.py`

Mỗi lựa chọn: layer, công nghệ, `cost_tier`, `estimated_monthly_cost_usd`, `capacity_sizing`, `decision_criteria[1..5]` (`TechCriteria`), `alternatives[]` mỗi cái kèm `why_rejected`.
Kèm `SolutionAssumptions` (budget tier, MAU/DAU/peak RPS, compliance…) và `scaling_roadmap`.

---

## 3. `blueprint.json` — `Blueprint`
`tools/schemas/blueprint.py`

```
audience, detail_level, layout_intent, presentation_style(slide|diagram), density,
slide_title, slide_kicker, brand, diagram_title,
pattern, pattern_rationale, key_decisions[], c4_level,
pillar_coverage(PillarCoverage: 6× WAFPillar{addressed_by[], gaps[]}),
nfr_mapping[NFRMapping{nfr, mechanism, node_ids[]}],
legend[LegendEntry{label, flow}],
hub, nodes[BPNode], clusters[BPCluster], edges[BPEdge],
process(Optional[ProcessBlueprint])
```

- `BPNode`: `id, label, tech, cluster, type`
- `BPCluster`: `id, label, tier, parent, accent, number, zone`
- `BPEdge`: `from` (alias của `from_`), `to, label, protocol, flow, style`

**Bất biến:**
- Cả ba đều có `model_validator(mode="before")` ép alias: `title|name` → `label`; `source|src|source_id|from_id` → `from`; `target|dst|…` → `to`. Đừng bỏ các validator này — model rất hay dùng tên khác.
- `zone` chỉ vẽ ra khi có **chuỗi parent đầy đủ**: `cloud > vpc > (subnet_public|subnet_private) > az`. Một cluster phẳng có `zone` sẽ bị bỏ qua **im lặng**.
- `Blueprint.process` là di sản — kiểu sơ đồ mới **không** thêm field vào `Blueprint`, mà thêm nhánh vào `DiagramSpec` (xem §4 và ADR `0003`).

---

## 4. Diagram spec / IR

- **`DiagramSpec`** (`tools/schemas/diagram_spec.py`) — union phân biệt theo `kind`: `ArchitectureSpec | ProcessSpec | SequenceSpec | ERDSpec | StateMachineSpec`. Envelope `DiagramPlan`: `kind, title, objective, audience, source_type, presentation_style, spec`.
- **`render_spec.json`** — dict **phẳng** mà native renderer tiêu thụ (mọi kind dùng chung), dựng bởi `_build_render_spec` trong `tools/schemas/coercion.py`. Key: `style_preset, nodes, edges, clusters, hub, process, layout_intent`.
- **Renderer registry** (`prettygraph/native/registry.py`): `RendererEntry{kind, backend:"native"|"codegen", tree_builder, style_preset_label, semantic_ids_fn}`. Contract của tree builder: `(spec, *, flat, plan) -> (Diagram, root)`.
- **`icon_plan.json`** — output của subagent `icon_resolver`: map node id → icon path / node class. `icon_resolver` bị **deny write** file này ở permission layer; nó ghi qua tool chuyên trách.
- **`engineer_report.json`** — `chosen plan`, per-candidate `{score, pass, collisions, …}`, `final_score`, `final_pass`. Scorecard phơi ra: `arrow_clarity_score, visible_edge_count, bundled_edge_count, crossings_per_edge, long_edge_ratio, icon_coverage, ratio, page_fill`.

---

## 5. `wbs.json` — WBS do agent sinh
`domain/wbs/wbs_tools.py`

```
project_info{name, project_code(mặc định "BNK"), client, solution_type, business_domain}
ratios{ba_on_dev, qc_on_dev, pm_on_total}
phases[{code:"I|II|III", name, modules[{code:"II.A", name}]}]
items[<leaf>]
# sau finalize_wbs, thêm:
effort_totals, effort_by_module, timeline, team, milestones,
resource_leveling, <các field critical path>, validation
```

**Leaf:**
```
seq, ref_code ("<project_code>-<seq>"), phase_code, module_code, group,
name, description, phase_type, remark,
be, fe, mobile, ai, fe_mobile, ba, qc, pm, total,
optimistic, likely, pessimistic, pert_expected_md, pert_p50_md, pert_p80_md,
predecessors[], dependencies[], owner, acceptance_criteria[]
```

**Bất biến:**
- Schema model nhìn thấy là `LeafIn` — model **chỉ** ước lượng `be/fe/mobile/ai` (+ `ba` khi `phase_type=="requirement"`). Mọi thứ còn lại do `derive_leaf_effort` suy ra. `apply_wbs_reestimate` **cố tình ghi đè** mọi `qc`/`pm`/`total` mà script `run_python` ghi vào.
- Rollup: `total_mandays, total_manmonths, effort_by_role{BE,FE_Mobile,BA,QC,PM}, effort_pct_by_role, cost_by_role_usd, total_cost_usd, rate_card_usd_per_month`.
- CPM: `project_duration_md, critical_path_ref_codes[], items[{ref_code, early_start, early_finish, late_start, late_finish, float_md, critical}]`.
- `dependencies` chỉ còn đọc để tương thích ngược file cũ; schema model-facing đã bỏ `DependencyEdge` giàu field (mimo hay stringify dict lồng nhau).

**WBS nhập từ lịch sử** — `WbsProject` (`domain/wbs/wbs_schema.py`):
`project_code, name, client, business_domain, solution_type, description, objectives[], technology_stack[], total_mandays, modules[WbsModule], wbs_items[WbsItem], risks[], raw_summary`.
53 file WBS lịch sử dùng ~40 biến thể schema top-level và ~60 biến thể nhãn role — `_extract_wbs_items` xử lý list phẳng / dict-of-lists / `tasks` lồng / `sub_items`.

**Excel** (`wbs_excel.py`): clone `backend/src/data/wbs_template.xlsx` và **giữ công thức sống** tham chiếu sheet `4. Master Data`. Nghĩa là mô hình effort được mã hoá **hai lần** — trong Python và trong sheet. Đổi một bên mà không đổi bên kia thì số liệu phân kỳ trong im lặng.

---

## 6. Deck

- **`SlideSpec`** (`domain/deck/deck.py`): `slide_no, section, title, layout, block, bullets[], asset_ref, narrative_role, source_refs[], client_facing, params{}`.
- **`DeckPlan`**: `revision, created_at, title, subtitle, brand, audience, slides[]` + `content_hash()`.
- **`SectionContract`** (`domain/deck/deck_sections.py`): `key, section, kind, title, role, layout, block, data_source, status, params[Param{name,desc,required}], required_inputs[], slide_count(min,max), optional, notes`.
- `VALID_LAYOUTS` / `VALID_BLOCKS` (`domain/reporting/ppt_reporting.py`) — xem `domain-glossary.md` §4. **`IMPLEMENTED_BLOCKS` là tập con** của literal `Block`; block gắn `new_block` chưa có renderer.
- `DEFAULT_PPT_SECTIONS` (13) và `DEFAULT_REPORT_SECTIONS` (11) mỗi bộ có `SECTION_ALIASES` riêng. Tên section không nhận diện được sẽ ra WARNING; nếu >50% là rác thì rơi về default.

---

## 7. Corpus past-project

**`case_library.json`** (mỗi entry): `slug, folder, title, client, type, domain[], tech[], problem, solution, outcome, image_ref`.

**`solution_memory.json`** = superset của trên, thêm:
```
estimate{effort_md, timeline_months, timeline_text, team_bnk_roles, team_client_roles,
         capex_usd, capex_note, opex_annual_usd, pricing_model}
wbs_join_reasoning, wbs_match{…, total_mandays, source_file},
source ("narrative" | "narrative+wbs" | "wbs_only"), _source_mtime
```

Chiếu sang embedding (`rag/solution_memory.py`): `page_content` = phần tự sự nối lại; `metadata` là **scalar phẳng** (`granularity, slug, folder, title, client, type, domain, tech_keywords, business_domain, solution_type, total_mandays, capex_usd, opex_annual_usd, pricing_model, timeline_months, image_ref, source, wbs_source_file`) — Qdrant filter chỉ lọc được scalar phẳng.

Collection Qdrant (`rag/indexer.py`): `bnk_projects`, `bnk_modules`, `bnk_wbs_items`, và bản hợp nhất **được ưu tiên** `bnk_solutions`. Embedding `text-embedding-3-small`, dim 1536, cosine.

---

## 8. CSM — `solution_model.json`
`memory/stores/csm.py`, `SCHEMA_VERSION = "1.0"`

```
schema_version, revision, created_at,
requirements[], constraints[], assumptions[], decisions[], components[],
risks[], work_items[], evidence[], controls[], deliverables[], trace_links[]
```

- `TraceLink{from_id, to_id, relation, confidence, provenance}`, `relation` ∈ `satisfies | constrains | assumes | supports | implements | mitigates | visualizes | claims | supersedes | accepts`.
- `content_hash()` **cố ý loại trừ** `created_at`, `revision`, `schema_version` — để so sánh nội dung thật sự đổi hay không.
- Log append-only đi kèm: `findings_log.json`, `evidence_log.json`, `comment_log.json`, decision records.

---

## 9. Artifact ref (frontend ↔ runtime)

```ts
ArtifactRef = { __artifact: string, mime: string, filename: string }
```

`runtime/src/artifact-substitution.ts` thay 4 field — `png_base64`, `pdf_base64`, `pptx_base64`, `wbs_xlsx_base64` — bằng ref, phục vụ tại `GET /api/artifacts/:key`.
Field `drawio` **giữ nguyên inline**: nội dung XML cần nguyên văn trong URL fragment để mở draw.io.
