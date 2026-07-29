"""Tests for domain/brd/brd_assembler.py (docs/plans/2026-07-29-brd-agent.md §E1)."""

from __future__ import annotations

import json

import brd_assembler as ba


def test_normalize_brd_sections_defaults_and_aliases():
    resolved, unrecognized = ba.normalize_brd_sections(None)
    assert resolved == ba.DEFAULT_BRD_SECTIONS
    assert unrecognized == []

    resolved, unrecognized = ba.normalize_brd_sections(["intro", "nfr", "bogus"])
    assert resolved == ["purpose", "non-functional-requirements"]
    assert unrecognized == ["bogus"]


def test_normalize_brd_sections_dedupes_and_falls_back_when_all_unrecognized():
    resolved, unrecognized = ba.normalize_brd_sections(["intro", "intro"])
    assert resolved == ["purpose"]
    resolved, unrecognized = ba.normalize_brd_sections(["totally-bogus"])
    assert resolved == ba.DEFAULT_BRD_SECTIONS
    assert unrecognized == ["totally-bogus"]


def test_assemble_brd_context_falls_back_without_a_diagram(tmp_path):
    ctx = ba.assemble_brd_context(tmp_path, title="Du an X")
    assert ctx["title"] == "Du an X"
    assert ctx["document_type"] == "Business Requirements Document"
    assert ctx["brief"] == {}
    assert ctx["traceability"] == []
    # _enrich_report_from_csm must still run (no CSM present -> no crash, no-op)
    assert "capex_rows" in ctx or ctx.get("capex_rows") in (None, [])


def test_assemble_brd_context_reads_real_artifacts_when_a_diagram_exists(tmp_path):
    (tmp_path / "out.png").write_bytes(b"not a real png but that's fine")
    (tmp_path / "diagram_brief.json").write_text(
        json.dumps({"objective": "Ban ve online", "functional_requirements": ["Dang nhap", "Thanh toan"]}),
        encoding="utf-8",
    )
    (tmp_path / "blueprint.json").write_text(json.dumps({"slide_title": "He thong ban ve"}), encoding="utf-8")

    ctx = ba.assemble_brd_context(tmp_path)
    assert ctx["title"] == "He thong ban ve"
    assert ctx["brief"]["objective"] == "Ban ve online"
    assert ctx["node_count"] == 0
