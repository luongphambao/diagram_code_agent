---
name: brd-writing
description: How to draft a BnK-format Business Requirements Document (.docx) from the approved solution context, and how to revise it one section at a time without regenerating the whole file. Consult before drafting any BRD outline or section content.
---

# brd-writing

Turn an approved solution (diagram brief, tech stack, blueprint, WBS, CSM) into
a BnK-format BRD `.docx`, section by section — or revise ONE section of an
already-generated (or client-provided) BRD without touching any other. The
document is a versioned asset, not a one-shot render: every write goes through
a targeted op (see `reference/style-contract.md`), never a full regeneration.

## Tool order (brd_writer subagent)

```
load_brd_context()
  → inspect_brd_template()
  → draft_brd_outline(items)          # fill/keep/skip per template section
  → draft_section_content(section_id, content)   # one call per section (or a small batch)
```

The main agent then reviews and approves the outline and the generated file
(gates land in a later change); `read_brd_outline` / `validate_brd` work on an
already-generated or imported `out.brd.docx`.

## Golden rules

1. Never invent a `section_id` — it must come from `inspect_brd_template()`'s
   output. If you need a section the template doesn't have, that's an
   `insert_section` op at edit time, not something to draft ahead of the
   template.
2. Every quantitative claim traces back to something `load_brd_context()`
   returned, or is explicitly flagged as an assumption — never a bare guess.
3. Table content: row 0 is always the header. Image blocks: always followed by
   a caption block.
4. `status="skip"` on an `OutlineItem` requires a real reason in `notes` — an
   empty section with no explanation just looks broken later.
5. If `load_brd_context()` comes back nearly empty (no brief, no blueprint),
   say so and stop — don't fabricate FR/NFR content from nothing.

## Content formula by section (see `reference/section-recipes.md` for the full
table)

| section (suffix) | source | shape |
|---|---|---|
| `purpose` | `brief.objective` | 1 lead paragraph + 4–6 objective bullets |
| `scope` | `brief` + `blueprint` | 2 blocks: "In scope" / "Out of scope" |
| `user-needs` | CSM stakeholders | table: No. / Name / Type / Description |
| `functional-requirements-list` | CSM Requirement × Component | table: ID / Name / Step / Description |
| an FR's `description` / `interface-requirements` / `data-requirements` | Requirement + Component + WorkItem | 3 sub-blocks matching those 3 names |
| `non-functional-requirements/*` | NFR-kind requirements grouped by concern | table: Function × Performance requirement |
| `analysis-models` | the diagrams already finalized this session | table: Document / Description / Location |

See `reference/template-map.md` for what each template section actually means,
and `reference/style-contract.md` for what you may and may not touch in the
underlying OOXML.
