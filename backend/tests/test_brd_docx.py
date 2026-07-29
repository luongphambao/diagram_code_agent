"""Tests for domain/brd/brd_docx.py (docs/plans/2026-07-29-brd-agent.md).

python-docx's blank template ships built-in numbering definitions (numId 1-9,
abstractNumId 0-8 for its default List Bullet/List Number styles), so the
fixture below registers its OWN multilevel-heading + bullet numbering under
unused ids (90/91) rather than colliding with those.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

import brd_docx as bd

_HEADING_NUM_ID = 90
_BULLET_NUM_ID = 91


def _register_numbering(doc) -> None:
    numbering_el = doc.part.numbering_part.element
    heading_abstract = f"""<w:abstractNum {nsdecls("w")} w:abstractNumId="{_HEADING_NUM_ID}">
      <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
      <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2."/></w:lvl>
      <w:lvl w:ilvl="2"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2.%3."/></w:lvl>
    </w:abstractNum>"""
    heading_num = f'<w:num {nsdecls("w")} w:numId="{_HEADING_NUM_ID}"><w:abstractNumId w:val="{_HEADING_NUM_ID}"/></w:num>'
    bullet_abstract = f"""<w:abstractNum {nsdecls("w")} w:abstractNumId="{_BULLET_NUM_ID}">
      <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="-"/></w:lvl>
    </w:abstractNum>"""
    bullet_num = f'<w:num {nsdecls("w")} w:numId="{_BULLET_NUM_ID}"><w:abstractNumId w:val="{_BULLET_NUM_ID}"/></w:num>'
    for xml in (heading_abstract, bullet_abstract, heading_num, bullet_num):
        numbering_el.append(parse_xml(xml))


def _heading(doc, text: str, level: int):
    p = doc.add_paragraph(text, style=f"Heading {level}")
    numPr = p._p.get_or_add_pPr().get_or_add_numPr()
    numPr.get_or_add_ilvl().val = level - 1
    numPr.get_or_add_numId().val = _HEADING_NUM_ID
    return p


def _make_doc():
    """A small but representative BRD skeleton: two FRs each with the same three
    child-heading titles (Description / Interface requirements) — this is
    exactly the shape that broke the prototype's positional dedup."""
    doc = Document()
    _register_numbering(doc)

    _heading(doc, "INTRODUCTION", 1)
    _heading(doc, "Purpose", 2)
    doc.add_paragraph("Mục tiêu của tài liệu.")
    _heading(doc, "Scope", 2)
    doc.add_paragraph("Phạm vi trong.")
    doc.add_paragraph("Phạm vi ngoài.")

    _heading(doc, "FUNCTIONAL REQUIREMENTS", 1)
    _heading(doc, "FR01 – Login", 2)
    _heading(doc, "Description", 3)
    doc.add_paragraph("Người dùng đăng nhập bằng email/mật khẩu.")
    _heading(doc, "Interface requirements", 3)
    doc.add_paragraph("Form đăng nhập.")

    _heading(doc, "FR02 – Logout", 2)
    _heading(doc, "Description", 3)
    doc.add_paragraph("Người dùng đăng xuất.")
    _heading(doc, "Interface requirements", 3)
    doc.add_paragraph("Nút đăng xuất.")

    _heading(doc, "BUDGET", 1)
    doc.add_table(rows=2, cols=2)
    tbl = doc.tables[-1]
    for ci, val in enumerate(["Hạng mục", "Man-day"]):
        bd._set_cell_text(tbl.cell(0, ci), val, bold=True)
    for ci, val in enumerate(["BE", "10"]):
        bd._set_cell_text(tbl.cell(1, ci), val)

    return doc


def _roundtrip(doc):
    """Save + reload — mirrors what happens in apply_brd_ops."""
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# index_document
# --------------------------------------------------------------------------- #
def test_index_finds_every_section_with_correct_hierarchy():
    doc = _make_doc()
    _, sections = bd.index_document(doc)
    ids = [s.section_id for s in sections]
    assert ids == [
        "introduction",
        "introduction/purpose",
        "introduction/scope",
        "functional-requirements",
        "functional-requirements/fr01",
        "functional-requirements/fr01/description",
        "functional-requirements/fr01/interface-requirements",
        "functional-requirements/fr02",
        "functional-requirements/fr02/description",
        "functional-requirements/fr02/interface-requirements",
        "budget",
    ]


def test_requirement_code_collapses_to_short_id():
    doc = _make_doc()
    _, sections = bd.index_document(doc)
    by_id = {s.section_id: s for s in sections}
    assert "functional-requirements/fr01" in by_id
    assert by_id["functional-requirements/fr01"].title == "FR01 – Login"


def test_own_body_excludes_children_but_sub_body_includes_them():
    doc = _make_doc()
    _, sections = bd.index_document(doc)
    by_id = {s.section_id: s for s in sections}

    fr = by_id["functional-requirements"]
    assert fr.own_end == -1, "a section whose very next block is a child heading has an empty own body"
    assert fr.n_paragraphs == 0
    assert fr.sub_end > fr.sub_start  # subtree spans both FRs and their children

    leaf = by_id["functional-requirements/fr01/description"]
    assert leaf.n_paragraphs == 1
    assert leaf.own_checksum == leaf.sub_checksum  # a leaf's own body IS its whole subtree


def test_editing_a_leaf_never_changes_an_ancestor_own_checksum(tmp_path):
    doc = _make_doc()
    path = tmp_path / "doc.docx"
    doc.save(path)
    _, before = bd.index_document(path)
    before_by_id = {s.section_id: s.own_checksum for s in before}

    leaf = bd.resolve_section_ref(before, "functional-requirements/fr01/description")
    result = bd.apply_brd_ops(
        path,
        [
            {
                "op": "replace_body",
                "section": leaf.section_id,
                "expect": leaf.own_checksum,
                "reason": "t",
                "content": [{"type": "p", "text": "new"}],
            }
        ],
    )
    assert result.ok, result.failed

    _, after = bd.index_document(path)
    after_by_id = {s.section_id: s.own_checksum for s in after}
    for sid in ("functional-requirements", "functional-requirements/fr01"):
        assert after_by_id[sid] == before_by_id[sid], (
            f"{sid} own_checksum drifted from a sibling/descendant edit"
        )
    assert after_by_id[leaf.section_id] != before_by_id[leaf.section_id]


def test_id_component_strips_a_legacy_manual_outline_number():
    """The REAL company template (backend/templates/brd_template.docx) bakes a
    manual outline number into heading text alongside Word's OWN auto-numbering
    — e.g. the heading's actual run text is '3.2.1\\tDescription'. Without
    stripping this, ids would drift on renumber exactly like the position-based
    ids this module replaces."""
    assert bd.id_component("3.2.1\tDescription") == "description"
    assert bd.id_component("3.2.2 Interface requirements") == "interface-requirements"
    assert bd.id_component("FR1 – Lập hợp đồng") == "fr1"  # unaffected: matches the code pattern first


# --------------------------------------------------------------------------- #
# id stability — the prototype's core bug (docs/plans/2026-07-29-brd-agent.md §Context B)
# --------------------------------------------------------------------------- #
def test_id_assignment_is_scoped_to_parent_not_document_position():
    """Inserting a new FR with the SAME child titles ('Description', ...) between
    two existing FRs must not change either existing FR's ids — reproduces (and
    fixes) the exact failure that made description-7 silently repoint to FR06."""
    heads_before = [
        (0, 1, "FUNCTIONAL REQUIREMENTS"),
        (1, 2, "FR01 – Login"),
        (2, 3, "Description"),
        (3, 3, "Interface requirements"),
        (4, 2, "FR02 – Logout"),
        (5, 3, "Description"),
        (6, 3, "Interface requirements"),
    ]
    ids_before = bd.assign_section_ids(heads_before)

    # insert FR01b between FR01 and FR02, with the identical child titles
    heads_after = (
        heads_before[:4]
        + [
            (4, 2, "FR01b – Refresh token"),
            (5, 3, "Description"),
            (6, 3, "Interface requirements"),
        ]
        + [(i + 3, lv, t) for i, lv, t in heads_before[4:]]
    )
    ids_after = bd.assign_section_ids(heads_after)

    fr02_desc_before = ids_before[5]  # FR02's "Description"
    fr02_desc_after = ids_after[-2]  # FR02's "Description", now shifted later in the list
    assert fr02_desc_before == fr02_desc_after == "functional-requirements/fr02/description"


def test_sibling_title_collision_is_disambiguated_within_parent_only():
    heads = [
        (0, 1, "A"),
        (1, 2, "Description"),
        (2, 2, "Description"),
        (3, 1, "B"),
        (4, 2, "Description"),
    ]
    ids = bd.assign_section_ids(heads)
    assert ids == ["a", "a/description", "a/description~2", "b", "b/description"]


# --------------------------------------------------------------------------- #
# resolve_section_ref — no fuzzy fallback
# --------------------------------------------------------------------------- #
def test_resolve_exact_id():
    doc = _make_doc()
    _, sections = bd.index_document(doc)
    sec = bd.resolve_section_ref(sections, "functional-requirements/fr01/description")
    assert sec.section_id == "functional-requirements/fr01/description"


def test_resolve_unique_suffix():
    doc = _make_doc()
    _, sections = bd.index_document(doc)
    sec = bd.resolve_section_ref(sections, "fr02/description")
    assert sec.section_id == "functional-requirements/fr02/description"


def test_resolve_ambiguous_suffix_lists_all_candidates_and_does_not_guess():
    doc = _make_doc()
    _, sections = bd.index_document(doc)
    with pytest.raises(bd.AmbiguousSectionError) as exc:
        bd.resolve_section_ref(sections, "description")
    msg = str(exc.value)
    assert "functional-requirements/fr01/description" in msg
    assert "functional-requirements/fr02/description" in msg


def test_resolve_unknown_id_lists_every_valid_id():
    doc = _make_doc()
    _, sections = bd.index_document(doc)
    with pytest.raises(bd.SectionNotFoundError) as exc:
        bd.resolve_section_ref(sections, "does-not-exist")
    assert "budget" in str(exc.value)


# --------------------------------------------------------------------------- #
# patch ops — own-vs-subtree, optimistic lock, block addressing
# --------------------------------------------------------------------------- #
def test_replace_body_on_a_parent_never_touches_its_children(tmp_path):
    """Reproduces the prototype incident: replace_section on a section whose
    heading is immediately followed by a child heading must not delete the
    child. Here we exercise it on 'functional-requirements/fr01', which has an
    own body of zero blocks — append_body is the meaningful op for it."""
    doc = _make_doc()
    path = tmp_path / "doc.docx"
    doc.save(path)
    _, before = bd.index_document(path)
    fr01 = bd.resolve_section_ref(before, "functional-requirements/fr01")
    before_ids = {s.section_id for s in before}

    result = bd.apply_brd_ops(
        path,
        [
            {
                "op": "append_body",
                "section": fr01.section_id,
                "expect": fr01.own_checksum,
                "reason": "t",
                "content": [{"type": "p", "text": "ghi chú thêm"}],
            }
        ],
    )
    assert result.ok, result.failed

    _, after = bd.index_document(path)
    after_ids = {s.section_id for s in after}
    assert before_ids == after_ids, "append_body on a childful section must not add/remove any section"
    fr01_desc = bd.resolve_section_ref(after, "functional-requirements/fr01/description")
    assert fr01_desc.n_paragraphs == 1, "the child's own body must be untouched"


def test_optimistic_lock_rejects_stale_checksum(tmp_path):
    doc = _make_doc()
    path = tmp_path / "doc.docx"
    doc.save(path)
    _, sections = bd.index_document(path)
    sec = bd.resolve_section_ref(sections, "introduction/purpose")

    result = bd.apply_brd_ops(
        path,
        [
            {
                "op": "replace_body",
                "section": sec.section_id,
                "expect": "deadbeef00000000",
                "reason": "t",
                "content": [{"type": "p", "text": "x"}],
            }
        ],
    )
    assert not result.ok
    assert any("checksum" in f for f in result.failed)

    # file on disk must be byte-identical to before the rejected op
    assert path.read_bytes() == doc_bytes_of(doc)


def doc_bytes_of(doc) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_unknown_section_ref_fails_without_creating_anything(tmp_path):
    doc = _make_doc()
    path = tmp_path / "doc.docx"
    doc.save(path)
    before_bytes = path.read_bytes()

    result = bd.apply_brd_ops(
        path,
        [{"op": "replace_body", "section": "does-not-exist", "expect": "x", "reason": "t", "content": []}],
    )
    assert not result.ok
    assert path.read_bytes() == before_bytes


def test_delete_section_with_children_requires_cascade(tmp_path):
    doc = _make_doc()
    path = tmp_path / "doc.docx"
    doc.save(path)
    _, sections = bd.index_document(path)
    fr01 = bd.resolve_section_ref(sections, "functional-requirements/fr01")

    result = bd.apply_brd_ops(
        path,
        [{"op": "delete_section", "section": fr01.section_id, "expect": fr01.own_checksum, "reason": "t"}],
    )
    assert not result.ok
    assert any("cascade" in f for f in result.failed)

    _, after = bd.index_document(path)
    assert any(s.section_id == "functional-requirements/fr01" for s in after)


def test_delete_section_with_cascade_removes_the_whole_subtree(tmp_path):
    doc = _make_doc()
    path = tmp_path / "doc.docx"
    doc.save(path)
    _, sections = bd.index_document(path)
    fr01 = bd.resolve_section_ref(sections, "functional-requirements/fr01")

    result = bd.apply_brd_ops(
        path,
        [
            {
                "op": "delete_section",
                "section": fr01.section_id,
                "expect": fr01.own_checksum,
                "reason": "t",
                "cascade": True,
            }
        ],
    )
    assert result.ok, result.failed

    _, after = bd.index_document(path)
    after_ids = {s.section_id for s in after}
    assert "functional-requirements/fr01" not in after_ids
    assert "functional-requirements/fr01/description" not in after_ids
    assert "functional-requirements/fr02" in after_ids, "sibling must survive"


def test_insert_section_creates_a_new_leaf_without_disturbing_others(tmp_path):
    doc = _make_doc()
    path = tmp_path / "doc.docx"
    doc.save(path)
    _, sections = bd.index_document(path)
    fr01 = bd.resolve_section_ref(sections, "functional-requirements/fr01")
    fr02_before = bd.resolve_section_ref(sections, "functional-requirements/fr02")

    result = bd.apply_brd_ops(
        path,
        [
            {
                "op": "insert_section",
                "section": fr01.section_id,
                "expect": fr01.own_checksum,
                "reason": "t",
                "where": "after",
                "title": "FR03 – Refresh token",
                "level": 2,
                "content": [{"type": "p", "text": "noi dung"}],
            }
        ],
    )
    assert result.ok, result.failed

    _, after = bd.index_document(path)
    after_ids = {s.section_id for s in after}
    assert "functional-requirements/fr03" in after_ids
    fr02_after = bd.resolve_section_ref(after, "functional-requirements/fr02")
    assert fr02_after.own_checksum == fr02_before.own_checksum


def test_block_address_self_heals_after_an_earlier_insert(tmp_path):
    doc = _make_doc()
    path = tmp_path / "doc.docx"
    doc.save(path)
    _, sections = bd.index_document(path)
    sec = bd.resolve_section_ref(sections, "introduction/scope")
    own = bd._own_body(bd.index_document(path)[0], sec)
    last_addr = bd.block_addr(own[-1], len(own) - 1, bd.index_document(path)[0])

    # insert a new paragraph at the front of the same section's own body
    result = bd.apply_brd_ops(
        path,
        [
            {
                "op": "insert_blocks",
                "section": sec.section_id,
                "expect": sec.own_checksum,
                "reason": "t",
                "at": bd.block_addr(own[0], 0, bd.index_document(path)[0]),
                "position": "before",
                "content": [{"type": "p", "text": "moi chen dau"}],
            }
        ],
    )
    assert result.ok, result.failed

    _, after = bd.index_document(path)
    after_sec = bd.resolve_section_ref(after, "introduction/scope")
    ordinal, _ = bd.resolve_block_ref(bd.index_document(path)[0], after_sec, last_addr)
    assert ordinal == 2, "the stale ordinal (now shifted by the insert) must resolve via digest, not raise"


def test_stale_block_address_with_no_digest_match_is_a_clear_error(tmp_path):
    doc = _make_doc()
    path = tmp_path / "doc.docx"
    doc.save(path)
    _, sections = bd.index_document(path)
    sec = bd.resolve_section_ref(sections, "introduction/scope")

    result = bd.apply_brd_ops(
        path,
        [
            {
                "op": "replace_block",
                "section": sec.section_id,
                "expect": sec.own_checksum,
                "reason": "t",
                "at": "b0#00000000",
                "content": [{"type": "p", "text": "x"}],
            }
        ],
    )
    assert not result.ok
    assert any("Đọc lại read_brd_section" in f for f in result.failed)


# --------------------------------------------------------------------------- #
# table ops
# --------------------------------------------------------------------------- #
def test_table_ops_round_trip(tmp_path):
    doc = _make_doc()
    path = tmp_path / "doc.docx"
    doc.save(path)
    _, sections = bd.index_document(path)
    sec = bd.resolve_section_ref(sections, "budget")
    own = bd._own_body(bd.index_document(path)[0], sec)
    tbl_addr = bd.block_addr(own[0], 0, bd.index_document(path)[0])

    result = bd.apply_brd_ops(
        path,
        [
            {
                "op": "set_cell",
                "section": sec.section_id,
                "expect": sec.own_checksum,
                "reason": "t",
                "at": tbl_addr,
                "row": 1,
                "col": 1,
                "value": "20",
            }
        ],
    )
    assert result.ok, result.failed

    _, sections = bd.index_document(path)
    sec = bd.resolve_section_ref(sections, "budget")
    own = bd._own_body(bd.index_document(path)[0], sec)
    assert own[0].cell(1, 1).text == "20"

    tbl_addr2 = bd.block_addr(own[0], 0, bd.index_document(path)[0])
    result2 = bd.apply_brd_ops(
        path,
        [
            {
                "op": "append_row",
                "section": sec.section_id,
                "expect": sec.own_checksum,
                "reason": "t",
                "at": tbl_addr2,
                "row_values": ["FE", "5"],
            }
        ],
    )
    assert result2.ok, result2.failed
    _, sections = bd.index_document(path)
    sec = bd.resolve_section_ref(sections, "budget")
    own = bd._own_body(bd.index_document(path)[0], sec)
    assert len(own[0].rows) == 3
    assert own[0].cell(2, 0).text == "FE"


def test_set_table_on_empty_table_raises_clear_error_not_indexerror():
    doc = Document()
    tbl = doc.add_table(rows=0, cols=0)
    with pytest.raises(ValueError, match="không có dòng nào"):
        bd.op_set_table(tbl, [["a", "b"]])


# --------------------------------------------------------------------------- #
# style/numbering invariant + revert-on-loss
# --------------------------------------------------------------------------- #
def test_only_document_xml_changes_on_a_single_section_edit(tmp_path):
    import zipfile

    doc = _make_doc()
    path = tmp_path / "doc.docx"
    doc.save(path)
    before_bytes = path.read_bytes()
    _, sections = bd.index_document(path)
    sec = bd.resolve_section_ref(sections, "introduction/purpose")

    result = bd.apply_brd_ops(
        path,
        [
            {
                "op": "replace_body",
                "section": sec.section_id,
                "expect": sec.own_checksum,
                "reason": "t",
                "content": [{"type": "p", "text": "noi dung moi"}],
            }
        ],
    )
    assert result.ok, result.failed
    after_bytes = path.read_bytes()

    with zipfile.ZipFile(io.BytesIO(before_bytes)) as za, zipfile.ZipFile(io.BytesIO(after_bytes)) as zb:
        changed = [n for n in za.namelist() if n in zb.namelist() and za.read(n) != zb.read(n)]
    assert changed == ["word/document.xml"]


def test_check_semantic_preservation_flags_a_corrupted_styles_part():
    doc = _make_doc()
    before_bytes = doc_bytes_of(doc)
    _, before_sections = bd.index_document(io.BytesIO(before_bytes))

    doc2 = Document(io.BytesIO(before_bytes))
    doc2.styles["Heading 1"].font.size = None  # touches styles.xml
    after_bytes = doc_bytes_of(doc2)
    _, after_sections = bd.index_document(io.BytesIO(after_bytes))

    findings = bd.check_semantic_preservation(
        before_bytes, before_sections, after_bytes, after_sections, ops=[]
    )
    assert any("styles.xml" in f for f in findings)


def test_apply_brd_ops_snapshots_before_writing(tmp_path):
    doc = _make_doc()
    path = tmp_path / "doc.docx"
    doc.save(path)
    revisions_dir = tmp_path / "brd_revisions"
    _, sections = bd.index_document(path)
    sec = bd.resolve_section_ref(sections, "introduction/purpose")

    result = bd.apply_brd_ops(
        path,
        [
            {
                "op": "replace_body",
                "section": sec.section_id,
                "expect": sec.own_checksum,
                "reason": "t",
                "content": [{"type": "p", "text": "x"}],
            }
        ],
        revisions_dir=revisions_dir,
    )
    assert result.ok
    assert result.revision_path == revisions_dir / "REV-0.docx"
    assert (revisions_dir / "REV-0.docx").exists()


def test_snapshot_keeps_only_last_n_revisions(tmp_path):
    doc = _make_doc()
    path = tmp_path / "doc.docx"
    doc.save(path)
    revisions_dir = tmp_path / "brd_revisions"
    for _ in range(3):
        bd.snapshot(revisions_dir, path, keep=2)
    remaining = sorted(p.name for p in revisions_dir.glob("REV-*.docx"))
    assert len(remaining) == 2
    assert remaining == ["REV-1.docx", "REV-2.docx"]
