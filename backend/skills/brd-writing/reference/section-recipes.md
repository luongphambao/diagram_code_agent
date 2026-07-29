# Section content recipes

Each row: `section_id` suffix → where the content comes from (via
`load_brd_context()`, unless noted) → what shape to draft with
`draft_section_content`.

| section_id suffix | source | content shape |
|---|---|---|
| `purpose` | `brief.objective` | 1 lead paragraph + 4–6 bullet objectives |
| `intended-audience` | (template boilerplate) | `status="keep"` — don't rewrite |
| `intended-use` | (template boilerplate) | `status="keep"` |
| `scope` | `brief` + `blueprint` | 2 blocks: "In scope" bullets / "Out of scope" bullets |
| `abbreviations-and-acronyms` | terms actually used elsewhere in this draft | table: Term / Meaning |
| `document-conventions` | (template boilerplate) | `status="keep"` |
| `user-needs` | CSM stakeholders (via `load_brd_context`) | table: No. / Name / Type / Description |
| `assumptions-and-dependencies` | CSM `Assumption` entities | bullets, one per assumption, flag `confidence_tier` if low |
| `functional-requirements-list` | CSM Requirement × Component | table: ID / Name / Step / Description |
| `frN/description` | Requirement.statement + Component.purpose | 1 lead paragraph + bullets for edge cases |
| `frN/interface-requirements` | blueprint nodes/edges touching the Component | bullets or a small table of screen/API/event |
| `frN/data-requirements` | ERD content if rendered this session, else Component notes | table: Entity / Field / Note |
| `external-interface-requirements/user` | `tech_stack` frontend layer + audience | 1-2 paragraphs |
| `external-interface-requirements/hardware` | `tech_stack` infra layer | bullets |
| `external-interface-requirements/software` | `tech_stack` full stack | table: Layer / Technology |
| `external-interface-requirements/communication` | blueprint external edges (protocols) | bullets |
| `system-features` | rollup of the FR list | bullets, one per FR, 1 line each |
| `non-functional-requirements/performance` | `brief.non_functional_requirements` (perf-tagged) | table: Function / Performance requirement |
| `non-functional-requirements/safety` | `brief.non_functional_requirements` (safety-tagged) | bullets |
| `non-functional-requirements/security` | `brief.non_functional_requirements` (security-tagged) + tech_stack compliance | bullets |
| `non-functional-requirements/quality` | `brief.non_functional_requirements` (quality-tagged) | bullets |
| `analysis-models` | diagrams already finalized this session | table: Document / Description / Location |
| `issues-list` | CSM `Risk` entities | table: Issue / Impact / Note — no Owner/Due column unless a real one exists |

## Rules that apply to every row above

- If the source data doesn't exist yet (e.g. no WBS run, no ERD rendered),
  `status="skip"` with a `notes` reason — never fill with a placeholder.
- A table's row 0 is always the header. An image block is always followed by
  a `caption` block.
- Numbers (percentages, costs, counts) must come from `load_brd_context()`'s
  digest, not be estimated inline while drafting prose.
