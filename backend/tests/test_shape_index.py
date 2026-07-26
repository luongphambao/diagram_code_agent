"""Regression test for the shape-index packaging bug: ``search_drawio_shapes``
used to silently return an error string on every call because ``INDEX``
pointed at a directory (``domain/diagram/data/``) that never existed — the
real file lived under the now-deleted ``diagram_mcp/data/`` fossil, and the
``FileNotFoundError`` was swallowed by a bare ``except Exception`` in
``tools.icon_tools.search_drawio_shapes`` (docs/gotchas.md)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain.diagram import shapesearch
from tools.icon_tools import search_drawio_shapes


def test_shape_index_file_is_installed():
    assert Path(shapesearch.INDEX).exists(), (
        f"shape index missing at {shapesearch.INDEX} — the tool will silently error"
    )


def test_search_shapes_finds_a_real_hit():
    results = shapesearch.search_shapes("dynamodb", limit=1)
    assert results
    assert "style" in results[0]


def test_search_drawio_shapes_tool_returns_ok_status():
    payload = json.loads(search_drawio_shapes.func("dynamodb"))
    assert payload["status"] == "OK"
    assert payload["results"]


def test_load_index_raises_typed_error_when_missing(monkeypatch):
    monkeypatch.setattr(shapesearch, "INDEX", str(Path("/nonexistent") / "shape-index.json.gz"))
    monkeypatch.setattr(shapesearch, "_shapes_cache", None)
    monkeypatch.setattr(shapesearch, "_tag_map_cache", None)
    with pytest.raises(shapesearch.ShapeIndexMissing):
        shapesearch.search_shapes("dynamodb")


def test_tool_reports_structured_error_when_index_missing(monkeypatch):
    monkeypatch.setattr(shapesearch, "INDEX", str(Path("/nonexistent") / "shape-index.json.gz"))
    monkeypatch.setattr(shapesearch, "_shapes_cache", None)
    monkeypatch.setattr(shapesearch, "_tag_map_cache", None)
    payload = json.loads(search_drawio_shapes.func("dynamodb"))
    assert payload["status"] == "ERROR"
    assert "shape index not found" in payload["reason"]
