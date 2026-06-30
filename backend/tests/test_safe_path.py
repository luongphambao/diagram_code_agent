"""Tests for safe_path.py — path traversal and filename sanitisation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from safe_path import safe_filename, safe_workspace_path


# ---------------------------------------------------------------------------
# safe_filename
# ---------------------------------------------------------------------------

class TestSafeFilename:
    def test_plain_filename_unchanged(self):
        assert safe_filename("report.pdf") == "report.pdf"

    def test_strips_posix_directory(self):
        assert safe_filename("../../etc/passwd") == "passwd"

    def test_strips_windows_directory(self):
        assert safe_filename(r"C:\Windows\System32\cmd.exe") == "cmd.exe"

    def test_mixed_separators(self):
        assert safe_filename("foo/../../bar\\evil.txt") == "evil.txt"

    def test_null_byte_replaced(self):
        result = safe_filename("file\x00name.txt")
        assert "\x00" not in result

    def test_none_returns_upload(self):
        assert safe_filename(None) == "upload"

    def test_empty_string_returns_upload(self):
        assert safe_filename("") == "upload"

    def test_only_dots_returns_upload(self):
        assert safe_filename("...") == "upload"

    def test_truncates_long_name(self):
        long = "a" * 300 + ".txt"
        result = safe_filename(long)
        assert len(result) <= 200

    def test_dangerous_chars_replaced(self):
        result = safe_filename("file<>:|?.txt")
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result

    def test_windows_reserved_name_prefixed(self):
        result = safe_filename("CON.txt")
        assert result != "CON.txt"
        assert "con" not in result.lower().split(".")[0] or result.startswith("file_")


# ---------------------------------------------------------------------------
# safe_workspace_path
# ---------------------------------------------------------------------------

class TestSafeWorkspacePath:
    def test_normal_filename_resolves(self, tmp_path):
        result = safe_workspace_path(tmp_path, "output.png")
        assert result == (tmp_path / "output.png").resolve()

    def test_dotdot_stripped_by_safe_filename(self, tmp_path):
        # "../../etc/passwd" → safe_filename → "passwd" → inside tmp_path
        result = safe_workspace_path(tmp_path, "../../etc/passwd")
        assert result.name == "passwd"
        assert str(result).startswith(str(tmp_path.resolve()))

    def test_nested_path_stripped(self, tmp_path):
        result = safe_workspace_path(tmp_path, "subdir/secret.json")
        # safe_filename strips the directory; only "secret.json" should remain
        assert result.name == "secret.json"
        assert str(result).startswith(str(tmp_path.resolve()))

    def test_symlink_outside_base_raises(self, tmp_path):
        # Create a symlink inside tmp_path that points outside it.
        target = tmp_path.parent / "outside.txt"
        target.write_text("secret")
        link = tmp_path / "link.txt"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")
        # The link itself resolves outside tmp_path — expect ValueError.
        with pytest.raises(ValueError, match="Path escape"):
            safe_workspace_path(tmp_path, "link.txt")

    def test_returns_path_object(self, tmp_path):
        result = safe_workspace_path(tmp_path, "manifest.json")
        assert isinstance(result, Path)
