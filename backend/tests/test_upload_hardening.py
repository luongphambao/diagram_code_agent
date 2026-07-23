"""Tests for upload hardening (improvement plan §0.4): content-type sniffing
and the streamed size cap in routers/upload.py.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from document_parsers.content_sniff import sniff_mismatch
from routers.upload import _stream_to_disk


# --- content_sniff -------------------------------------------------------


def test_sniff_accepts_real_pdf_header():
    assert sniff_mismatch(".pdf", b"%PDF-1.7\n%...rest") is None


def test_sniff_rejects_fake_pdf():
    assert sniff_mismatch(".pdf", b"MZ\x90\x00this is an exe") is not None


def test_sniff_accepts_real_docx_zip_header():
    assert sniff_mismatch(".docx", b"PK\x03\x04\x14\x00...") is None


def test_sniff_rejects_renamed_exe_as_docx():
    assert sniff_mismatch(".docx", b"MZ\x90\x00\x03\x00\x00\x00") is not None


def test_sniff_accepts_real_png():
    assert sniff_mismatch(".png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR") is None


def test_sniff_rejects_text_labeled_as_png():
    assert sniff_mismatch(".png", b"this is just plain text, not a png") is not None


def test_sniff_accepts_real_webp():
    head = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"VP8 "
    assert sniff_mismatch(".webp", head) is None


def test_sniff_rejects_fake_webp():
    assert sniff_mismatch(".webp", b"not a webp at all, just text") is not None


def test_sniff_accepts_plain_markdown():
    assert sniff_mismatch(".md", "# Hello\n\nThis is **markdown**.".encode()) is None


def test_sniff_rejects_binary_content_labeled_as_text():
    binary = bytes(range(256))  # includes NUL and many control bytes
    assert sniff_mismatch(".txt", binary) is not None


def test_sniff_unknown_extension_is_not_flagged_here():
    # Extension allowlisting happens earlier in the upload endpoint (via
    # SUPPORTED_EXT); this function only flags a mismatch for extensions it
    # knows how to fingerprint.
    assert sniff_mismatch(".exe", b"anything") is None


def test_sniff_accepts_real_xlsx_zip_header():
    # xlsx is OOXML — same zip container as docx; same coarse magic-byte check.
    assert sniff_mismatch(".xlsx", b"PK\x03\x04\x14\x00...") is None


def test_sniff_rejects_renamed_exe_as_xlsx():
    assert sniff_mismatch(".xlsx", b"MZ\x90\x00\x03\x00\x00\x00") is not None


def test_sniff_accepts_plain_csv():
    assert sniff_mismatch(".csv", b"name,role,md\nAlice,BE,5\n") is None


def test_sniff_rejects_binary_content_labeled_as_csv():
    binary = bytes(range(256))
    assert sniff_mismatch(".csv", binary) is not None


# --- streamed size cap -----------------------------------------------------


class _FakeUploadFile:
    """Duck-typed stand-in for fastapi.UploadFile — yields fixed-size chunks
    from an in-memory buffer via async .read(), same as the real thing."""

    def __init__(self, data: bytes, chunk_size: int) -> None:
        self._data = data
        self._chunk_size = chunk_size
        self._pos = 0

    async def read(self, n: int) -> bytes:
        chunk = self._data[self._pos : self._pos + min(n, self._chunk_size)]
        self._pos += len(chunk)
        return chunk


def test_stream_to_disk_writes_full_file_under_cap(tmp_path, monkeypatch):
    monkeypatch.setattr("routers.upload.MAX_UPLOAD_BYTES", 1024)
    data = b"x" * 500
    dest = tmp_path / "out.bin"
    fake = _FakeUploadFile(data, chunk_size=64)
    asyncio.run(_stream_to_disk(fake, dest))
    assert dest.read_bytes() == data


def test_stream_to_disk_rejects_oversized_file_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setattr("routers.upload.MAX_UPLOAD_BYTES", 100)
    data = b"x" * 500
    dest = tmp_path / "out.bin"
    fake = _FakeUploadFile(data, chunk_size=64)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_stream_to_disk(fake, dest))
    assert exc_info.value.status_code == 413
    assert not dest.exists()  # partial file must not be left behind


# --- tabular attachment staging (improvement plan §C-S2) -------------------


def test_attached_tabular_files_returns_raw_path_not_flattened_text(tmp_path, monkeypatch):
    import json

    from routers.upload import _attached_tabular_files

    monkeypatch.setattr("routers.upload.UPLOADS_DIR", tmp_path)
    raw = tmp_path / "abc123_budget.csv"
    raw.write_text("dept,budget\nEng,1000\n", encoding="utf-8")
    (tmp_path / "abc123.tabular.json").write_text(
        json.dumps({"raw_path": raw.name, "filename": "budget.csv", "kind": "csv"}),
        encoding="utf-8",
    )

    out = _attached_tabular_files(["abc123"])
    assert out == [("budget.csv", raw)]
    # the raw bytes are untouched — no flattening happened
    assert raw.read_text(encoding="utf-8") == "dept,budget\nEng,1000\n"


def test_attached_tabular_files_skips_missing_or_absent(tmp_path, monkeypatch):
    from routers.upload import _attached_tabular_files

    monkeypatch.setattr("routers.upload.UPLOADS_DIR", tmp_path)
    assert _attached_tabular_files(["nope"]) == []
    assert _attached_tabular_files([]) == []
