---
name: wbs-planning
description: How to break a software solution into a BnK-format Work Breakdown Structure and estimate effort — the 3-phase spine, module catalog, the dev-only estimation + ratio-derivation model, phase-gating, and the tool order. Consult before producing any WBS.
---

# wbs-planning

Turn an approved solution (diagram brief + tech stack + blueprint) into a BnK-format
WBS: a hierarchy of phases → modules → features, each with a defensible effort
estimate, plus a delivery timeline, team and milestones. The output is a live
formula-driven `.xlsx` matching the BnK template.

**Golden rule of estimation:** you only size *development* effort (BE / FE / Mobile /
AI man-days) per feature. Business Analysis, QC and Project Management are DERIVED
automatically from fixed ratios — never estimate them by hand. This keeps every WBS
internally consistent and matches how BnK actually builds these spreadsheets.

## The estimation pipeline (call the tools IN THIS ORDER)

1. `load_solution_context()` — pull objective, functional requirements, tech layers
   and blueprint clusters/nodes. Your modules and features must trace back to these.
2. `get_effort_norms()` — benchmark dev man-day ranges per feature type. Anchor every
   estimate to these; do not invent numbers far outside the ranges without a reason.
3. `draft_wbs_skeleton(project_info, phases)` — define the phase/module tree only
   (no effort yet). Use the 3-phase spine + module catalog below.
4. **`propose_wbs_skeleton()` — HITL gate.** Get the STRUCTURE approved before
   estimating. If rejected, revise the skeleton and re-propose.
5. `add_wbs_items(items)` — add leaf features one module at a time. Estimate only
   be/fe/mobile/ai; set `phase_type` correctly (it gates which roles apply).
6. `compute_wbs_rollup()` — aggregate to module/phase/role totals.
7. `plan_timeline_and_sprints()` — duration, 2-week sprints, months, Gantt grid.
8. `plan_team_and_resources()` — team composition from the role totals.
9. `define_milestones()` — defaults to the BnK 5-milestone spine.
10. `validate_wbs()` — fix any warnings you can.
11. **`propose_wbs()` — HITL gate.** Get the full plan/effort approved.
12. **`export_wbs_excel()` — HITL gate.** Produce the `.xlsx` deliverable.

## The 3-phase spine (always use these phase codes/names)

- **I — SET UP & INSTALLATION**
  - `I.A Solution Design` — Database Design, System/Architecture Design, Data Security,
    UI/UX Design, Code Base Setup. (`phase_type=design`, except UI/UX → `uiux`.)
  - `I.B System Operation` — Deployment Setup, Infrastructure/Error/APM Monitoring.
    (`phase_type=design`.)
  - Optionally a `REQUIREMENT GATHERING` module with workshop/BRD items
    (`phase_type=requirement`).
- **II — DEVELOPMENT** — the bulk. One module per product surface or architecture
  tier (see catalog). Leaves are `phase_type=development` (BE + FE/Mobile).
- **III — TESTING & DEPLOYMENT SUPPORT**
  - `III.A Solution Qualification` — "Fix SIT/UAT Issues" support block
    (`phase_type=support`, sized to a ~1-month window).
  - `III.B Deployment & Maintenance` — Production Deployment, App-store Submission,
    Data Migration (`phase_type=deployment`, PM=0), Post Go-live Support.

Module codes are roman-phase + letter: `I.A`, `II.A`, `II.B`, `III.A`. For dense
DEVELOPMENT modules you may use sub-module **groups** (e.g. `Common Module`,
`Account Module`) via the `group` field on items — these render as light sub-headers.

## Module catalog (DEVELOPMENT)

Web Portal · Mobile Application · Core Service · Common Module/Frame ·
Authentication & Authorization · Dashboard · Admin Portal · Client Portal ·
Entity/Record Management (list + detail) · Notification (Email/SMS/In-App/WhatsApp) ·
3rd-party Integration (SSO / Payment Gateway / Public API) · Reporting & Export ·
Search/Filter · Workflow/Approval · Rule/Calculation Engine · KYC · Audit Trail.
For AI builds add: AI Models, Dataset/Pipeline, Rule Engine, Streaming/Clip/Incident
engines.

## The effort model (what the tools do for you)

```
dev = BE + FE + Mobile + AI          # you estimate ONLY this
BA  = 0.10 × dev                     # derived
QC  = 0.30 × dev                     # derived
PM  = 0.10 × (dev + BA + QC)         # derived (some projects use 0.05)
total = dev + BA + QC + PM ≈ 1.54 × dev
```

**Phase-gating — set `phase_type` so the right roles apply:**

| phase_type | roles applied | use for |
|---|---|---|
| `development` | BE + FE/Mobile + BA + QC + PM | normal features (the default) |
| `requirement` | BA + PM only (put MD in `ba`) | workshops, BRD, requirement refinement |
| `design` | BE + PM only | DB/system/security design, setup, monitoring |
| `uiux` | FE/Mobile + PM only | UI/UX design |
| `deployment` | BE only, PM = 0 | prod deploy, app-store, data migration |
| `support` | BE/FE + derived BA/QC/PM | UAT-fix / post-go-live support block |

## Sizing guidance

- Anchor each leaf to `get_effort_norms()` (e.g. Login ~1–4.6 total, Registration ~13,
  Dashboard ~4.6, a CRUD module ~2–8.5, KYC ~12.3, a 3rd-party integration ~1.5–18.5,
  a report ~7.7–17). See `reference/effort-norms.md`.
- Decompose to leaves of roughly **0.5–10 dev MD**. Split anything bigger.
- A typical small system lands at 80–150 MD; a mid-size build 250–500 MD.

## Timeline & team

- 1 sprint = 2 weeks, 1 month = 4 weeks. `duration_months ≈ total_MD / (22 × peak_devs)`.
- The Delivery Plan grid is generated dynamically — it ALWAYS has enough month columns
  for the duration. Pass `duration_weeks` explicitly if the client fixed the schedule.
- Team ramps up then down; PM ~0.3 FTE flat; QC peaks late around UAT.

## Milestones (BnK 5-milestone spine — the default)

Contract Signoff → Requirement Confirmation/Signoff (BRD) → Development Completion &
UAT Initiation (System in UAT + Test Cases/Report) → Completion of UAT (Source Code +
User Guide + Tech Spec) → Completion of Post-Launch Support (~3-month nursing).

See `reference/template-layout.md` for the exact sheet/column/formula structure and
`reference/examples.md` for condensed real WBS skeletons.
