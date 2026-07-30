"""BRD Agent tools (docs/plans/2026-07-29-brd-agent.md §E2/§E3).

Ungated worker tools (brd_writer's) plus `import_brd_docx` and the 3 HITL
gates (`propose_brd_outline`, `generate_brd_docx`, `edit_brd_section`) — all
MAIN-only. `import_brd_docx` itself is NOT a gate: importing a file the user
already provided isn't a decision a human needs to approve, only the edits
that follow it are.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

from docx import Document
from docx.oxml.ns import qn

from backends import AGENT_SPACE, WorkspaceFile, current_workspace
from domain.brd.brd_assembler import assemble_brd_context
from domain.brd.brd_docx import (
    AmbiguousSectionError,
    Section,
    SectionNotFoundError,
    apply_brd_ops,
    apply_ops,
    block_addr,
    blocks,
    index_document,
    resolve_section_ref,
)
from domain.brd.brd_validate import validate_brd as _validate_brd_report
from domain.reporting.reporting import record_report_step
from runtime.safe_path import safe_filename, safe_workspace_path

from ..schemas.brd import Block, BrdOp, OutlineItem

_TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"
_OUT_BRD_NAME = "out.brd.docx"
_TEMPLATE_MAP_FILE = WorkspaceFile("template_map.json")
_OUTLINE_DRAFT_FILE = WorkspaceFile("brd_outline_draft.json")
_OUTLINE_FILE = WorkspaceFile("brd_outline.json")
_VALIDATION_FILE = WorkspaceFile("brd_validation.json")
_SECTIONS_DIR_NAME = "brd_sections"
_REVISIONS_DIR_NAME = "brd_revisions"
_MAX_OPS_PER_CALL = 50

_OUTLINE_CAP = 120


# --------------------------------------------------------------------------- #
# formatting helpers — one-line-per-section / one-line-per-block, matching the
# read_drawio inventory convention (tools/rendering_tools.py:1517).
# --------------------------------------------------------------------------- #
def _format_outline(sections: list[Section]) -> str:
    if not sections:
        return "0 mục."
    lines = [
        f"{len(sections)} mục. `chk` = checksum THÂN RIÊNG (không gồm mục con). "
        "Sửa mục con KHÔNG BAO GIỜ đổi chk của mục cha — không cần đọc lại mục cha."
    ]
    shown = sections[:_OUTLINE_CAP]
    for i, s in enumerate(shown):
        indent = "  " * s.level
        tail = (
            f"{len(s.children)} con" if s.children else f"own: {s.n_paragraphs}p/{s.n_tables}t/{s.n_images}i"
        )
        lines.append(f"  [{i:>3}] {indent}{s.section_id:<50} L{s.level}  {tail:<22} chk={s.own_checksum}")
    if len(sections) > _OUTLINE_CAP:
        lines.append(
            f"\n... {len(sections) - _OUTLINE_CAP} mục khác bị cắt (trần {_OUTLINE_CAP}). Gọi read_brd_outline(section=...) để thu hẹp."
        )
    return "\n".join(lines)


def _format_section_blocks(doc, sec: Section) -> str:
    bs = blocks(doc)
    own = bs[sec.own_start : sec.own_end + 1] if sec.own_end >= sec.own_start else []
    lines = [
        f"Mục '{sec.section_id}' (L{sec.level}, own_checksum={sec.own_checksum}), {len(own)} block trong thân riêng."
    ]
    if sec.children:
        lines.append(f"Mục con: {', '.join(sec.children)}")
    for i, b in enumerate(own[:_OUTLINE_CAP]):
        addr = block_addr(b, i, doc)
        if hasattr(b, "rows"):
            preview = " | ".join(c.text for c in b.rows[0].cells) if b.rows else ""
            lines.append(f'  [{addr}] tbl {len(b.rows)}x{len(b.columns)} "{preview[:60]}"')
        else:
            text = (b.text or "").strip().replace("\n", " ")
            kind = "img" if b._p.findall(".//" + qn("a:blip")) else "p"
            lines.append(f'  [{addr}] {kind:<4} "{text[:70]}"')
    if len(own) > _OUTLINE_CAP:
        lines.append(f"... {len(own) - _OUTLINE_CAP} block khác bị cắt (trần {_OUTLINE_CAP}).")
    return "\n".join(lines)


def _read_json(f: WorkspaceFile) -> Optional[dict]:
    try:
        if not f.exists():
            return None
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _format_draft_outline(items: list[dict]) -> str:
    lines = [f"Nháp outline ({len(items)} mục, chưa sinh out.brd.docx):"]
    for it in items:
        lines.append(
            f"  [{it.get('status', 'fill'):<4}] {it.get('section_id')}  <- {it.get('source')}  {it.get('notes', '')}"
        )
    lines.append("\nGọi propose_brd_outline để trình duyệt, rồi generate_brd_docx để sinh file.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# brd_writer tools
# --------------------------------------------------------------------------- #
@tool
def load_brd_context() -> str:
    """Gather approved workspace context (analysis, brief, tech stack, blueprint,
    WBS, CSM) into one digest for authoring BRD section content. Read this
    BEFORE drafting any content — never invent a number this doesn't return."""
    ctx = assemble_brd_context(current_workspace())
    brief = ctx.get("brief") or {}
    lines = [
        f"Title: {ctx.get('title')!r}  Subtitle: {ctx.get('subtitle')!r}",
        f"Objective: {brief.get('objective', '(none)')}",
        f"Functional requirements: {len(brief.get('functional_requirements', []))}",
        f"Non-functional requirements: {len(brief.get('non_functional_requirements', []))}",
        f"Tech items: {len(ctx.get('tech_items', []))}",
        f"Traceability: {ctx.get('coverage_summary', 'N/A')}",
        f"Risks: {len(ctx.get('risks', []))}",
        f"Executive points: {len(ctx.get('executive_points', []))}",
    ]
    if ctx.get("capex_rows"):
        lines.append(f"WBS effort rows: {len(ctx['capex_rows'])}, tổng ${ctx.get('capex_total', 0):,.0f}")
    if not brief and not ctx.get("tech_items"):
        lines.append(
            "\nCẢNH BÁO: hầu như không có ngữ cảnh nào (chưa có brief/tech_stack/blueprint) — đừng bịa nội dung FR/NFR."
        )
    return "\n".join(lines)


@tool(parse_docstring=True)
def inspect_brd_template(template: str = "brd_template.docx") -> str:
    """Index the company BRD template and cache its section map for this workspace.

    Call this before draft_brd_outline — every OutlineItem.section_id you draft
    MUST come from this list, never invented.

    Args:
        template: Filename under backend/templates/. Default is the standard BRD template.
    """
    tpl_path = _TEMPLATES_DIR / safe_filename(template)
    if not tpl_path.exists():
        return f"Không tìm thấy template '{template}' trong backend/templates/."
    _, sections = index_document(tpl_path)
    ws = current_workspace()
    ws.mkdir(parents=True, exist_ok=True)
    _TEMPLATE_MAP_FILE.write_text(
        json.dumps([s.to_dict() for s in sections], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return (
        _format_outline(sections)
        + f"\n\n{len(sections)} mục trong template — dùng section_id ở trên cho draft_brd_outline."
    )


@tool(parse_docstring=True)
def draft_brd_outline(items: list[OutlineItem]) -> str:
    """Draft the section-by-section outline (fill/keep/skip) before proposing it
    for approval. Every item.section_id must come from inspect_brd_template's
    output. This does NOT gate anything — the main agent calls
    propose_brd_outline afterwards.

    Args:
        items: One entry per template section, each with a fill/keep/skip decision
            and the data source backing it.
    """
    ws = current_workspace()
    ws.mkdir(parents=True, exist_ok=True)
    payload = [item.model_dump() for item in items]
    _OUTLINE_DRAFT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    n_fill = sum(1 for i in items if i.status == "fill")
    n_skip = sum(1 for i in items if i.status == "skip")
    record_report_step(
        ws,
        "draft_brd_outline",
        summary=f"Nháp outline: {len(items)} mục ({n_fill} fill, {n_skip} skip).",
        data=payload,
    )
    return f"Đã ghi nháp {len(items)} mục ({n_fill} fill, {n_skip} skip, {len(items) - n_fill - n_skip} keep). Gọi propose_brd_outline để trình duyệt."


def _section_content_filename(section_id: str) -> str:
    return safe_filename(section_id.replace("/", "__")) + ".json"


def _resolve_content_image_paths(ws: Path, content: list[dict]) -> None:
    """Rewrite each image block's `path` in place to an absolute path inside
    the workspace. The model only ever sees/writes workspace-relative paths
    (e.g. "out.png"); python-docx just does open(path) with no notion of the
    workspace, so without this it resolves against the process cwd instead
    and fails even for a correct filename. Leaves an unresolvable/escaping
    path untouched — build_block's image step reports that as a clean
    per-op failure rather than crashing the batch."""
    for block in content:
        if isinstance(block, dict) and block.get("type") == "image" and block.get("path"):
            try:
                block["path"] = str(safe_workspace_path(ws, block["path"]))
            except ValueError:
                pass


def _resolve_op_image_paths(ws: Path, op: dict) -> None:
    if op.get("content"):
        _resolve_content_image_paths(ws, op["content"])
    if op.get("image_path"):
        try:
            op["image_path"] = str(safe_workspace_path(ws, op["image_path"]))
        except ValueError:
            pass


@tool(parse_docstring=True)
def draft_section_content(section_id: str, content: list[Block]) -> str:
    """Write the drafted content for ONE outline section.

    Call once per section (or repeatedly for a small batch) — keeps context
    small and lets one section's content be redrafted without touching others.
    Table content: row 0 is always the header. Image blocks: always add a
    caption block immediately after.

    Args:
        section_id: The section_id from draft_brd_outline's items.
        content: The blocks to render for this section, in document order.
    """
    ws = current_workspace()
    sections_dir = ws / _SECTIONS_DIR_NAME
    sections_dir.mkdir(parents=True, exist_ok=True)
    fname = _section_content_filename(section_id)
    (sections_dir / fname).write_text(
        json.dumps(
            {"section_id": section_id, "content": [b.model_dump() for b in content]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return f"Đã ghi nội dung nháp cho '{section_id}' ({len(content)} block)."


# --------------------------------------------------------------------------- #
# brd_writer + main tools
# --------------------------------------------------------------------------- #
@tool(parse_docstring=True)
def read_brd_outline(section: str = "") -> str:
    """Compact inventory of out.brd.docx for targeted edits.

    With no `section`: one line per section — id, level, own-body checksum, and
    child count. Editing a child NEVER changes a parent's checksum, so don't
    re-read a parent after editing one of its children.
    With `section`: the one-line-per-block inventory of THAT section's own
    body, with a block address for each — use these addresses with
    edit_brd_section. Cut off at 120 sections/blocks with a note to narrow.

    Args:
        section: A section_id (or unique trailing suffix) to drill into that
            section's blocks instead of listing the whole outline.
    """
    ws = current_workspace()
    path = ws / _OUT_BRD_NAME
    if not path.exists():
        draft = _read_json(_OUTLINE_DRAFT_FILE)
        if draft:
            return _format_draft_outline(draft)
        return (
            "Chưa có out.brd.docx. Gọi import_brd_docx(source=...) để nạp file có sẵn, "
            "hoặc dùng brd_writer để draft_brd_outline(...) rồi propose_brd_outline(...) để bắt đầu sinh mới."
        )
    doc, sections = index_document(path)
    if not section:
        return _format_outline(sections)
    try:
        sec = resolve_section_ref(sections, section)
    except (SectionNotFoundError, AmbiguousSectionError) as exc:
        return f"✗ {exc}"
    return _format_section_blocks(doc, sec)


@tool
def validate_brd() -> str:
    """Structural lint of out.brd.docx — duplicate/ambiguous ids, broken heading
    numbering, dangling image references, malformed tables, placeholder text
    left in, FR sections missing a required child (Description/Interface
    requirements/Data requirements)."""
    ws = current_workspace()
    path = ws / _OUT_BRD_NAME
    if not path.exists():
        return "Chưa có out.brd.docx để kiểm tra."
    outline = _read_json(_OUTLINE_FILE) or _read_json(_OUTLINE_DRAFT_FILE)
    result = _validate_brd_report(path, outline=_as_outline_map(outline))
    _VALIDATION_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"{result['error_count']} lỗi, {result['warning_count']} cảnh báo, {result['advice_count']} gợi ý, trên {result['section_count']} mục."
    ]
    for kind in ("errors", "warnings", "advice"):
        for f in result[kind][:10]:
            lines.append(f"- [{kind.rstrip('s')}] {f['message']}")
    return "\n".join(lines)


def _as_outline_map(draft) -> Optional[dict]:
    """draft_brd_outline writes a LIST of OutlineItem dicts; validate_brd wants a
    {section_id: item} map."""
    if not isinstance(draft, list):
        return None
    return {
        item.get("section_id"): item for item in draft if isinstance(item, dict) and item.get("section_id")
    }


# --------------------------------------------------------------------------- #
# main-only tool
# --------------------------------------------------------------------------- #
_FILE_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def _find_uploaded_docx(file_id: str) -> Optional[Path]:
    uploads_dir = AGENT_SPACE / "uploads"
    if not uploads_dir.exists():
        return None
    matches = sorted(uploads_dir.glob(f"{file_id}_*.docx"))
    return matches[0] if matches else None


@tool(parse_docstring=True)
def import_brd_docx(source: str) -> str:
    """Import an existing .docx as the working BRD document (out.brd.docx), so
    its sections can be read and patched with edit_brd_section instead of
    generating one from scratch.

    Args:
        source: Either the 12-hex-char file_id returned by /upload for a .docx
            attachment, or a plain filename already present in this workspace.
            Never a full filesystem path.
    """
    ws = current_workspace()
    if _FILE_ID_RE.match(source or ""):
        candidate = _find_uploaded_docx(source)
        if candidate is None:
            return f"Không tìm thấy file .docx đã upload với id '{source}'."
    else:
        try:
            candidate = safe_workspace_path(ws, source)
        except ValueError as exc:
            return f"Đường dẫn không hợp lệ: {exc}"
        if not candidate.exists():
            return f"Không tìm thấy file '{source}' trong workspace."

    ws.mkdir(parents=True, exist_ok=True)
    dest = ws / _OUT_BRD_NAME
    shutil.copyfile(candidate, dest)
    try:
        _, sections = index_document(dest)
    except Exception as exc:  # noqa: BLE001 — a bad/corrupt .docx is a data problem, not a bug
        dest.unlink(missing_ok=True)
        return f"'{source}' không phải .docx hợp lệ hoặc bị hỏng: {exc}"

    record_report_step(
        ws,
        "import_brd_docx",
        summary=f"Đã nạp '{source}' làm out.brd.docx ({len(sections)} mục).",
        data={"source": source, "section_count": len(sections)},
    )
    return (
        _format_outline(sections)
        + "\n\nĐã nạp làm out.brd.docx. Dùng read_brd_outline(section) rồi edit_brd_section để sửa từng mục."
    )


# --------------------------------------------------------------------------- #
# main-only HITL gates (§E3) — interrupt_on pauses BEFORE the body below runs
# (see agent/builder.py's `interrupt_on = {name: ... for name in GATE_TOOL_NAMES}`),
# so every function here executes only AFTER a human approves; it reads back
# whatever was drafted/persisted before the pause rather than trusting args
# the model may have re-typed for the approval card.
# --------------------------------------------------------------------------- #
@tool(parse_docstring=True)
def propose_brd_outline(question: str, items: Optional[list[OutlineItem]] = None) -> str:
    """Present the drafted BRD outline (fill/keep/skip per template section)
    for human approval. PAUSES before running. Call after brd_writer has
    drafted the outline (draft_brd_outline) — this does NOT generate any
    content itself, only promotes the draft to the approved brd_outline.json.

    Args:
        question: Approval question shown to the user.
        items: The outline items to show on the card — normally the exact
            list brd_writer already wrote via draft_brd_outline. If omitted,
            the last drafted outline on disk is used.
    """
    payload = [i.model_dump() for i in items] if items else _read_json(_OUTLINE_DRAFT_FILE)
    if not payload:
        return "Chưa có nháp outline — delegate brd_writer để draft_brd_outline trước."
    ws = current_workspace()
    ws.mkdir(parents=True, exist_ok=True)
    _OUTLINE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    n_fill = sum(1 for i in payload if i.get("status") == "fill")
    n_skip = sum(1 for i in payload if i.get("status") == "skip")
    record_report_step(
        ws,
        "propose_brd_outline",
        summary=f"Outline BRD được duyệt: {len(payload)} mục ({n_fill} fill, {n_skip} skip).",
        data=payload,
    )
    return (
        f"✓ Outline BRD ĐÃ DUYỆT: {len(payload)} mục ({n_fill} fill, {n_skip} skip).\n\n"
        "Bước tiếp theo: nếu các mục 'fill' chưa có nội dung nháp, delegate brd_writer "
        "để draft_section_content cho từng mục, rồi gọi generate_brd_docx()."
    )


@tool(parse_docstring=True)
def generate_brd_docx(
    question: str = "Generate the BRD .docx from the approved outline and drafted content?",
) -> str:
    """Render out.brd.docx from the company template, the approved outline
    (propose_brd_outline), and every section's drafted content
    (draft_section_content). PAUSES for approval first. Each 'fill' section's
    body is REPLACED in the template via the same targeted op edit_brd_section
    uses — never a bespoke from-scratch render — so the result stays
    addressable by read_brd_outline/edit_brd_section afterwards.

    Args:
        question: Approval question shown to the user.
    """
    ws = current_workspace()
    outline = _read_json(_OUTLINE_FILE) or _read_json(_OUTLINE_DRAFT_FILE)
    if not outline:
        return "Chưa có outline đã duyệt — gọi propose_brd_outline trước."
    template_path = _TEMPLATES_DIR / "brd_template.docx"
    if not template_path.exists():
        return "Không tìm thấy backend/templates/brd_template.docx."

    doc = Document(template_path)
    _, sections = index_document(doc)
    by_id = {s.section_id: s for s in sections}
    sections_dir = ws / _SECTIONS_DIR_NAME

    ops: list[dict] = []
    missing: list[str] = []
    for item in outline:
        if not isinstance(item, dict) or item.get("status") != "fill":
            continue
        sid = item.get("section_id", "")
        sec = by_id.get(sid)
        if sec is None:
            missing.append(f"{sid} (không có trong template)")
            continue
        drafted = _read_json(sections_dir / _section_content_filename(sid))
        if not drafted or not drafted.get("content"):
            missing.append(f"{sid} (chưa có draft_section_content)")
            continue
        _resolve_content_image_paths(ws, drafted["content"])
        ops.append(
            {"op": "replace_body", "section": sid, "expect": sec.own_checksum, "content": drafted["content"]}
        )

    succeeded, applied, failed = apply_ops(doc, ops)
    ws.mkdir(parents=True, exist_ok=True)
    doc.save(ws / _OUT_BRD_NAME)

    lines = [f"✓ Đã sinh out.brd.docx: {len(succeeded)}/{len(ops)} mục ghi thành công."]
    if missing:
        lines.append(f"{len(missing)} mục 'fill' bị bỏ qua: " + "; ".join(missing[:10]))
    if failed:
        lines.append(f"{len(failed)} op lỗi: " + "; ".join(failed[:10]))
    lines.append("\nDùng read_brd_outline(section) rồi edit_brd_section để sửa từng mục sau này.")
    record_report_step(
        ws,
        "generate_brd_docx",
        summary=f"Đã sinh out.brd.docx ({len(succeeded)}/{len(ops)} mục, {len(missing)} bị bỏ qua).",
        data={"applied": applied, "failed": failed, "missing": missing},
    )
    return "\n".join(lines)


@tool(parse_docstring=True)
def edit_brd_section(ops: list[BrdOp]) -> str:
    """Apply one or more targeted edits to out.brd.docx. PAUSES for approval
    with a diff of exactly what would change. Every op except
    append_body/insert_blocks/append_row MUST carry `expect` — the section's
    CURRENT own_checksum from read_brd_outline — or it is refused; a stale
    checksum means the section changed since you last read it, so re-read and
    retry rather than overriding. On any semantic-preservation violation
    (style/numbering corrupted, an unrelated section touched, headings losing
    their auto-number) the ENTIRE batch is reverted and the file on disk is
    left untouched.

    Args:
        ops: Up to 50 edit operations, applied in order (each re-indexes the
            document, so a later op sees the previous ops' effects).
    """
    ws = current_workspace()
    path = ws / _OUT_BRD_NAME
    if not path.exists():
        return "Chưa có out.brd.docx — gọi generate_brd_docx hoặc import_brd_docx trước."
    if len(ops) > _MAX_OPS_PER_CALL:
        return f"Quá nhiều op trong một lần gọi ({len(ops)} > {_MAX_OPS_PER_CALL}) — chia nhỏ lại."

    op_dicts = [op.model_dump(exclude_none=True) for op in ops]
    for op_dict in op_dicts:
        _resolve_op_image_paths(ws, op_dict)
    result = apply_brd_ops(path, op_dicts, revisions_dir=ws / _REVISIONS_DIR_NAME)

    if result.reverted:
        record_report_step(
            ws,
            "edit_brd_section",
            status="reverted",
            summary=f"Batch {len(ops)} op BỊ HOÀN TÁC: {'; '.join(result.revert_reasons)}",
            data={"failed": result.failed, "revert_reasons": result.revert_reasons},
        )
        return "✗ TOÀN BỘ BATCH BỊ HOÀN TÁC — file trên đĩa KHÔNG đổi:\n" + "\n".join(
            f"- {r}" for r in result.revert_reasons
        )

    lines = [f"✓ Đã áp dụng {len(result.applied)}/{len(ops)} op:"]
    lines.extend(f"  - {a}" for a in result.applied)
    if result.failed:
        lines.append(f"{len(result.failed)} op lỗi (KHÔNG áp dụng phần còn lại của batch nếu phụ thuộc):")
        lines.extend(f"  - {f}" for f in result.failed)
    record_report_step(
        ws,
        "edit_brd_section",
        summary=f"Đã sửa {len(result.applied)}/{len(ops)} op trên out.brd.docx.",
        data={"applied": result.applied, "failed": result.failed},
    )
    return "\n".join(lines)


BRD_WRITER_TOOLS = [
    load_brd_context,
    inspect_brd_template,
    draft_brd_outline,
    draft_section_content,
    read_brd_outline,
    validate_brd,
]

__all__ = [
    "BRD_WRITER_TOOLS",
    "load_brd_context",
    "inspect_brd_template",
    "draft_brd_outline",
    "draft_section_content",
    "read_brd_outline",
    "validate_brd",
    "import_brd_docx",
    "propose_brd_outline",
    "generate_brd_docx",
    "edit_brd_section",
]
