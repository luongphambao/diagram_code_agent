# Template map — `backend/templates/brd_template.docx`

Real output of `inspect_brd_template()` on the current template (`FR1`/`FR2`
are the template's two SAMPLE requirements — `propose_brd_outline` normally
removes them and drafts one section per real requirement in the CSM).

```
- introduction (L1) — "INTRODUCTION"
  - introduction/purpose (L2) — "Purpose"
  - introduction/intended-audience (L2) — "Intended Audience"
  - introduction/intended-use (L2) — "Intended Use"
  - introduction/scope (L2) — "Scope"
  - introduction/abbreviations-and-acronyms (L2) — "Abbreviations and Acronyms"
  - introduction/document-conventions (L2) — "Document Conventions"
- general-description (L1) — "GENERAL DESCRIPTION"
  - general-description/user-needs (L2) — "User Needs"
  - general-description/assumptions-and-dependencies (L2) — "Assumptions and Dependencies"
- functional-requirements-description (L1) — "Functional requirements description"
  - functional-requirements-description/functional-requirements-list (L2) — "Functional requirements list"
  - functional-requirements-description/frN (L2) — "FRN – <name>"        (one per requirement)
    - .../description (L3), .../interface-requirements (L3), .../data-requirements (L3)
- system-features-and-non-requirements (L1) — "System features and Non-requirements"
  - .../external-interface-requirements (L2)
    - .../user (L3), .../hardware (L3), .../software (L3), .../communication (L3)
  - .../system-features (L2)
  - .../non-functional-requirements (L2)
    - .../performance (L3), .../safety (L3), .../security (L3), .../quality (L3)
- analysis-models (L1) — "Analysis Models"
- issues-list (L1) — "Issues List"
```

## What each section actually means

| section (suffix) | meaning |
|---|---|
| `purpose` | Why this document exists, in the client's own domain terms — not a generic "this BRD describes..." paragraph. |
| `intended-audience` / `intended-use` | Who reads this and what decision it supports (sign-off, dev handoff, etc.) — usually `status="keep"`, the template's own boilerplate is fine. |
| `scope` | What's in vs. explicitly out — pulls from `brief.functional_requirements` (in) and anything the blueprint/tech-stack explicitly ruled out (out). |
| `abbreviations-and-acronyms` | Table of every domain term/acronym used elsewhere in the doc — fill LAST, once you know what you've actually used. |
| `document-conventions` | Numbering/heading convention boilerplate — `status="keep"` almost always. |
| `user-needs` | CSM stakeholders as a table (No./Name/Type/Description). |
| `assumptions-and-dependencies` | CSM `Assumption` entities, one per bullet, with `confidence_tier` noted if low. |
| `functional-requirements-list` | One table row per FR: ID / Name / brief step / description — the index the `frN` sections below expand on. |
| `frN` (one per real requirement) | The parent heading only — content lives in its 3 children below. |
| `frN/description` | What the feature does, from the CSM Requirement's `statement` + the Component(s) that implement it. |
| `frN/interface-requirements` | Screens/APIs/events involved — from the blueprint's nodes/edges touching that Component. |
| `frN/data-requirements` | Entities/tables/fields touched — from ERD content if one was rendered, else the Component's data notes. |
| `external-interface-requirements/*` | User/Hardware/Software/Communication interfaces — from `tech_stack` layer choices and the blueprint's external edges. |
| `system-features` | High-level feature list — usually a rollup of the FR list, not new content. |
| `non-functional-requirements/*` | Performance/Safety/Security/Quality — from `brief.non_functional_requirements`, grouped by concern. |
| `analysis-models` | Table: Document / Description / Location — one row per diagram already finalized this session (`finalize_diagram` manifest), not a place to describe requirements again. |
| `issues-list` | Open questions/risks — from CSM `Risk` entities. Only include a row with a real owner/severity if you actually have one; don't fabricate. |
