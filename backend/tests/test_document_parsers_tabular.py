"""Tabular upload parsing (improvement plan §C-S2): .xlsx/.csv must produce a
short PREVIEW only — never the full dataset flattened to prose. The raw file
is what run_python actually reads (see test_upload_hardening.py's
_attached_tabular_files tests and routers/chat.py)."""

from __future__ import annotations

from document_parsers.parsers import CSV_EXT, SUPPORTED_EXT, TABULAR_EXT, XLSX_EXT, parse_file


def test_tabular_extensions_are_supported():
    assert ".xlsx" in SUPPORTED_EXT
    assert ".csv" in SUPPORTED_EXT
    assert TABULAR_EXT == XLSX_EXT | CSV_EXT


def test_parse_csv_produces_preview_not_full_flatten(tmp_path):
    rows = ["dept,budget,headcount"] + [f"D{i},{i * 100},{i}" for i in range(50)]
    path = tmp_path / "budget.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    doc = parse_file(path)

    assert doc.ok
    assert doc.kind == "tabular"
    assert "dept" in doc.text and "budget" in doc.text and "headcount" in doc.text
    assert "**Rows:** 50" in doc.text
    # preview only — must NOT contain all 50 data rows verbatim
    assert doc.text.count("\n") < 30


def test_parse_xlsx_produces_preview(tmp_path):
    openpyxl = __import__("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["dept", "budget"])
    for i in range(30):
        ws.append([f"D{i}", i * 10])
    path = tmp_path / "budget.xlsx"
    wb.save(path)

    doc = parse_file(path)

    assert doc.ok
    assert doc.kind == "tabular"
    assert "dept" in doc.text and "budget" in doc.text
    assert "**Rows:** 30" in doc.text


def test_parse_empty_csv_is_not_ok(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    doc = parse_file(path)

    assert doc.kind == "tabular"
    assert not doc.ok
