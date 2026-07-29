"""BRD Agent schemas — outline items, the section-content block model, and the
edit-op model for the 3 HITL gates (docs/plans/2026-07-29-brd-agent.md §B3/§E2/§E3)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field

from .coercion import CoercingModel

BlockKind = Literal["p", "bullet", "table", "image", "caption", "code"]


class Block(CoercingModel):
    """One content block for a BRD section body. Heading blocks are deliberately
    NOT representable here — creating a new heading/section goes through the
    insert_section op of edit_brd_section, which knows how to assign it a stable
    id; a bare heading block inside drafted content would bypass that."""

    type: BlockKind = "p"
    text: Optional[str] = Field(None, description="Content for p/bullet/caption/code.")
    rows: Optional[list[list[str]]] = Field(None, description="Table data, row 0 is the header.")
    widths: Optional[list[float]] = Field(None, description="Column widths in inches.")
    path: Optional[str] = Field(None, description="Workspace-relative image path.")
    width: float = Field(6.1, description="Image width in inches.")
    bold: bool = False
    italic: bool = False


class OutlineItem(CoercingModel):
    """One template section's fill/keep/skip decision — an item of
    draft_brd_outline's `items` list."""

    section_id: str = Field(description="Section id/path from inspect_brd_template — never invented.")
    title: str
    level: int = Field(ge=1, le=3)
    source: Literal["csm", "blueprint", "techstack", "wbs", "diagram", "manual", "template"] = Field(
        description="Where this section's content comes from — must trace back to something load_brd_context() returned."
    )
    content_kind: BlockKind = "p"
    status: Literal["fill", "keep", "skip"] = "fill"
    notes: str = Field("", description="Required explanation when status='skip'.")


BrdOpKind = Literal[
    "replace_body",
    "append_body",
    "insert_blocks",
    "replace_block",
    "delete_blocks",
    "set_table",
    "set_cell",
    "append_row",
    "delete_row",
    "replace_image",
    "rename_heading",
    "insert_section",
    "delete_section",
]


class BrdOp(CoercingModel):
    """One edit operation for edit_brd_section — a flat discriminated-union
    model (mirrors DrawioOp in tools/rendering_tools.py). Every op targets a
    `section` (a full section_id or unique trailing suffix from
    read_brd_outline); most also require `expect` to match that section's
    CURRENT own_checksum — a stale checksum is rejected rather than silently
    overwriting a concurrent edit. Fields irrelevant to a given `op` are simply
    left None; see docs/plans/2026-07-29-brd-agent.md §B2 for the per-op field
    table."""

    op: BrdOpKind
    section: str = Field(description="Section id or unique trailing suffix from read_brd_outline.")
    expect: Optional[str] = Field(
        None,
        description=(
            "own_checksum from read_brd_outline — required for every op EXCEPT "
            "append_body/insert_blocks/append_row (append-only, nothing to conflict with)."
        ),
    )
    content: Optional[list[Block]] = Field(None, description="New content blocks for body/block ops.")
    at: Optional[str] = Field(
        None, description="Block address (b<ordinal>#<digest>) from read_brd_outline(section=...)."
    )
    to: Optional[str] = Field(
        None, description="delete_blocks only: block address to delete UP TO (inclusive)."
    )
    position: Optional[Literal["before", "after"]] = Field(None, description="insert_blocks anchor side.")
    rows: Optional[list[list[str]]] = Field(
        None, description="set_table: full replacement rows, row 0 is the header."
    )
    row: Optional[int] = Field(None, description="set_cell/append_row/delete_row: 0-based row index.")
    col: Optional[int] = Field(None, description="set_cell: 0-based column index.")
    value: Optional[str] = Field(None, description="set_cell: new cell text.")
    row_values: Optional[list[str]] = Field(None, description="append_row: cell values for the new row.")
    image_path: Optional[str] = Field(
        None, description="replace_image: workspace-relative path to the new image."
    )
    image_width: Optional[float] = Field(None, description="replace_image: width in inches (default 6.1).")
    title: Optional[str] = Field(None, description="rename_heading's new title, or insert_section's title.")
    level: Optional[int] = Field(
        None, ge=1, le=3, description="insert_section: heading level of the new section."
    )
    where: Optional[Literal["first_child", "last_child", "before", "after"]] = Field(
        None, description="insert_section: placement relative to `section`."
    )
    cascade: Optional[bool] = Field(
        None, description="delete_section: must be true if `section` has children, else the op is refused."
    )


__all__ = ["BlockKind", "Block", "OutlineItem", "BrdOpKind", "BrdOp"]
