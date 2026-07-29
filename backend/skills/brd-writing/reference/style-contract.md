# Style contract — what an edit may and may not touch

The template is treated as a contract, not a starting point to redecorate.
This is enforced in code (`domain/brd/brd_docx.py`'s snapshot + semantic-
preservation guard reverts a batch that violates it — see
`docs/plans/2026-07-29-brd-agent.md` §C3), but knowing the rule up front
means you draft content that never triggers a revert:

- **Never** invent a new heading style, font, color, or table style — every
  new block borrows an existing style already used in the template
  (`build_block` does this automatically; you only choose `type`, not styling).
- **Never** write `type="heading"` in drafted content — a new section/heading
  is created only through `insert_section`, which knows how to assign it a
  stable id and correct numbering. A stray heading block would bypass both.
- **A table's row 0 is always the header.** Column count must match every
  other row — ragged tables are a validate_brd error (`table_column_mismatch`).
- **An image block is always followed by a caption block.** A dangling image
  with no caption is a validate_brd warning (`image_missing_caption`).
- **Section ids are hierarchical paths** (`frN/description`, not a bare
  number) — never guess one; always take it from `inspect_brd_template()` /
  `read_brd_outline()`.
- Placeholder text (`TODO`, `TBD`, `XXX`, `Lorem ipsum`, `«…»`, `<…>`) is a
  hard error at `validate_brd` — if you don't have real content yet, mark the
  outline item `status="skip"` with a reason instead of writing a placeholder.
