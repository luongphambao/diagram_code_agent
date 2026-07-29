"""BRD follow-up detection + ordering (docs/plans/2026-07-29-brd-agent.md §B5).

_is_pdf_followup matches bare "document"/"doc"/"report" — a BRD ask phrased
with those same words ("sửa lại tài liệu BRD", "update the BRD document")
would be mis-detected as a PDF/report follow-up unless _is_brd_followup is
checked (and wins the routing branch in routers/chat.py) first.
"""

from __future__ import annotations

from session.followups import _brd_preserve, _is_brd_followup, _is_pdf_followup


def test_is_brd_followup_detects_english_and_vietnamese_phrasing():
    assert _is_brd_followup("please update the BRD document")
    assert _is_brd_followup("sửa lại tài liệu BRD, thêm mục về mã hoá at-rest")
    assert _is_brd_followup("tao tai lieu brd cho du an nay")
    assert _is_brd_followup("cần một business requirements document")


def test_is_brd_followup_does_not_false_positive_on_unrelated_text():
    assert not _is_brd_followup("render the diagram again please")
    assert not _is_brd_followup("export the wbs excel file")


def test_brd_ask_collides_with_pdf_followup_keywords():
    """The exact collision the ordering fix exists for: "document"/"report" are
    also _is_pdf_followup trigger words."""
    text = "update the BRD document, add a section on security"
    assert _is_brd_followup(text)
    assert _is_pdf_followup(text)  # both match — routers/chat.py must prefer BRD


def test_brd_preserve_true_only_for_a_downstream_brd_ask_without_a_fresh_attachment():
    text = "sửa lại tài liệu BRD, thêm mục về mã hoá at-rest"
    assert _brd_preserve(text, solution_exists=True, attached=False)
    assert not _brd_preserve(text, solution_exists=False, attached=False)
    assert not _brd_preserve(text, solution_exists=True, attached=True)
    assert not _brd_preserve("render a diagram", solution_exists=True, attached=False)
