"""Tests for the 3 BRD HITL gates (docs/plans/2026-07-29-brd-agent.md §E3):
propose_brd_outline, generate_brd_docx, edit_brd_section — plus the diff-card
computation (preview_ops + session.gate_decisions._card_for) that runs BEFORE
each gate's tool body, since interrupt_on pauses ahead of the tool.
"""

from __future__ import annotations

import contextvars
import json

import backends
import brd_docx as bd
from test_brd_docx import _heading, _make_doc, _register_numbering  # noqa: F401 — shared fixture helpers

from docx import Document

from session.gate_decisions import _card_for
from tools import draft_brd_outline, edit_brd_section, generate_brd_docx, propose_brd_outline
from tools.schemas.brd import Block, BrdOp, OutlineItem


def _use_workspace(monkeypatch, tmp_path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends,
        "_current_workspace",
        contextvars.ContextVar("current_workspace", default=tmp_path),
    )


# --------------------------------------------------------------------------- #
# propose_brd_outline
# --------------------------------------------------------------------------- #
def test_propose_brd_outline_without_a_draft_asks_for_one(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    out = propose_brd_outline.func(question="Approve?")
    assert "draft_brd_outline" in out
    assert not (tmp_path / "brd_outline.json").exists()


def test_propose_brd_outline_promotes_the_draft_to_the_approved_file(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    draft_brd_outline.func(
        items=[
            OutlineItem(section_id="introduction/purpose", title="Purpose", level=2, source="manual"),
            OutlineItem(
                section_id="introduction/scope",
                title="Scope",
                level=2,
                source="manual",
                status="skip",
                notes="not yet scoped",
            ),
        ]
    )
    out = propose_brd_outline.func(question="Approve the outline?")
    assert "ĐÃ DUYỆT" in out
    saved = json.loads((tmp_path / "brd_outline.json").read_text(encoding="utf-8"))
    assert len(saved) == 2
    assert saved[0]["section_id"] == "introduction/purpose"


def test_card_for_propose_brd_outline_renders_fill_and_skip_counts():
    val = {
        "action_requests": [
            {
                "name": "propose_brd_outline",
                "args": {
                    "question": "Approve?",
                    "items": [
                        {"section_id": "a", "status": "fill"},
                        {"section_id": "b", "status": "skip"},
                        {"section_id": "c", "status": "fill"},
                    ],
                },
            }
        ]
    }
    card, step, state_delta = _card_for(val, "")
    assert card["type"] == "brd_outline_approval"
    assert card["fill_count"] == 2
    assert card["skip_count"] == 1
    assert step == "awaiting_brd_outline"
    assert len(state_delta["brd_outline_draft"]) == 3


# --------------------------------------------------------------------------- #
# generate_brd_docx
# --------------------------------------------------------------------------- #
def test_generate_brd_docx_without_an_approved_outline_is_a_plain_message(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    out = generate_brd_docx.func()
    assert "propose_brd_outline" in out


def test_generate_brd_docx_renders_fill_sections_and_skips_missing_drafts(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    (tmp_path / "brd_outline.json").write_text(
        json.dumps(
            [
                {"section_id": "introduction/purpose", "status": "fill"},
                {"section_id": "introduction/scope", "status": "fill"},  # no draft content -> skipped
            ]
        ),
        encoding="utf-8",
    )
    sections_dir = tmp_path / "brd_sections"
    sections_dir.mkdir()
    (sections_dir / "introduction__purpose.json").write_text(
        json.dumps(
            {
                "section_id": "introduction/purpose",
                "content": [Block(type="p", text="Muc tieu tai lieu nay.").model_dump()],
            }
        ),
        encoding="utf-8",
    )
    out = generate_brd_docx.func()
    assert "out.brd.docx" in out
    assert (tmp_path / "out.brd.docx").exists()
    doc, sections = bd.index_document(tmp_path / "out.brd.docx")
    by_id = {s.section_id: s for s in sections}
    purpose = by_id["introduction/purpose"]
    own_texts = "\n".join(
        b.text for b in bd.blocks(doc)[purpose.own_start : purpose.own_end + 1] if hasattr(b, "text")
    )
    assert "Muc tieu tai lieu nay." in own_texts
    assert "chưa có draft_section_content" in out  # scope was skipped, reported


# --------------------------------------------------------------------------- #
# edit_brd_section + preview_ops / diff card
# --------------------------------------------------------------------------- #
def _seeded_out_brd(tmp_path):
    doc = _make_doc()
    doc.save(tmp_path / "out.brd.docx")
    _, sections = bd.index_document(tmp_path / "out.brd.docx")
    return {s.section_id: s for s in sections}


def test_edit_brd_section_without_out_brd_docx_is_a_plain_message(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    out = edit_brd_section.func(
        ops=[BrdOp(op="append_body", section="introduction", content=[Block(text="x")])]
    )
    assert "generate_brd_docx" in out or "import_brd_docx" in out


def test_edit_brd_section_applies_a_replace_body_op(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    by_id = _seeded_out_brd(tmp_path)
    purpose = by_id["introduction/purpose"]
    out = edit_brd_section.func(
        ops=[
            BrdOp(
                op="replace_body",
                section="introduction/purpose",
                expect=purpose.own_checksum,
                content=[Block(type="p", text="Noi dung moi.")],
            )
        ]
    )
    assert "Đã áp dụng" in out
    _, sections_after = bd.index_document(tmp_path / "out.brd.docx")
    after = {s.section_id: s for s in sections_after}["introduction/purpose"]
    assert after.own_checksum != purpose.own_checksum
    assert (tmp_path / "brd_revisions").exists()


def test_edit_brd_section_rejects_a_stale_checksum_without_touching_the_file(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    _seeded_out_brd(tmp_path)
    before_bytes = (tmp_path / "out.brd.docx").read_bytes()
    out = edit_brd_section.func(
        ops=[
            BrdOp(
                op="replace_body",
                section="introduction/purpose",
                expect="deadbeef",
                content=[Block(type="p", text="should not land")],
            )
        ]
    )
    assert "chưa ghi gì" in out or "lỗi" in out
    assert (tmp_path / "out.brd.docx").read_bytes() == before_bytes


def test_edit_brd_section_rejects_more_than_50_ops(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    _seeded_out_brd(tmp_path)
    ops = [
        BrdOp(op="append_body", section="introduction/purpose", content=[Block(text=str(i))])
        for i in range(51)
    ]
    out = edit_brd_section.func(ops=ops)
    assert "51" in out
    assert "50" in out


def test_preview_ops_computes_before_after_without_touching_disk(tmp_path):
    by_id = _seeded_out_brd(tmp_path)
    purpose = by_id["introduction/purpose"]
    path = tmp_path / "out.brd.docx"
    before_bytes = path.read_bytes()
    preview = bd.preview_ops(
        path,
        [
            {
                "op": "replace_body",
                "section": "introduction/purpose",
                "expect": purpose.own_checksum,
                "content": [{"type": "p", "text": "Noi dung xem truoc."}],
            }
        ],
    )
    assert path.read_bytes() == before_bytes  # preview never writes
    assert len(preview["sections"]) == 1
    sec = preview["sections"][0]
    assert sec["section_id"] == "introduction/purpose"
    assert "Noi dung xem truoc." in sec["after"]
    assert "Noi dung xem truoc." not in sec["before"]


def test_card_for_edit_brd_section_includes_a_line_diff(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    by_id = _seeded_out_brd(tmp_path)
    purpose = by_id["introduction/purpose"]
    val = {
        "action_requests": [
            {
                "name": "edit_brd_section",
                "args": {
                    "ops": [
                        {
                            "op": "replace_body",
                            "section": "introduction/purpose",
                            "expect": purpose.own_checksum,
                            "content": [{"type": "p", "text": "Noi dung the card."}],
                        }
                    ]
                },
            }
        ]
    }
    card, step, _state_delta = _card_for(val, "")
    assert card["type"] == "brd_edit_approval"
    assert step == "awaiting_brd_edit"
    assert card["op_count"] == 1
    assert len(card["sections"]) == 1
    diff_texts = {d["text"] for d in card["sections"][0]["diff"]}
    assert "Noi dung the card." in diff_texts
