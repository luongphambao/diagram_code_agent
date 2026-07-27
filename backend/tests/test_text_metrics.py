"""Tests for prettygraph.text_metrics — the shared real-font-width module that
replaces the `len(s) * 6.6`-style estimates scattered across layout_engine.py,
refined.py, router.py, validate_drawio.py and drawio_ingest.py.
"""

from __future__ import annotations

import pytest

from prettygraph import text_metrics as tm


@pytest.mark.skipif(not tm.has_real_metrics(), reason="no TTF resolvable on this host")
def test_char_width_is_not_uniform():
    """The old estimate assumed every character is the same width. Real
    Helvetica-compatible metrics must not: 'i' is much narrower than 'W'."""
    size = 10.5
    w_i = tm.text_width("i", size)
    w_w = tm.text_width("W", size)
    assert w_w > w_i * 2.5


@pytest.mark.skipif(not tm.has_real_metrics(), reason="no TTF resolvable on this host")
def test_same_length_strings_differ_in_width():
    """'Illinois' and 'WWWWWWWW' are both 8 characters — the flat len()*6.6
    estimate scores them identically, real metrics must not."""
    size = 10.5
    narrow = tm.text_width("Illinois", size)
    wide = tm.text_width("WWWWWWWW", size)
    old_estimate = 8 * 6.6
    assert wide > narrow * 2.0
    # The old constant sits nowhere near either real value except by accident.
    assert abs(narrow - old_estimate) / old_estimate > 0.2 or abs(wide - old_estimate) / old_estimate > 0.2


def test_text_width_empty_string():
    assert tm.text_width("", 10.5) == 0.0


def test_wrap_respects_existing_newlines():
    lines = tm.wrap("first line\nsecond line", max_w=1000, size=10.5)
    assert lines == ["first line", "second line"]


def test_wrap_breaks_long_line():
    long_text = "one two three four five six seven eight nine ten"
    lines = tm.wrap(long_text, max_w=60, size=10.5)
    assert len(lines) > 1
    # every produced line must actually fit (greedy wrap invariant)
    for line in lines:
        assert tm.text_width(line, 10.5) <= 60 + 1e-6 or " " not in line


def test_wrap_max_lines_caps_output():
    long_text = "one two three four five six seven eight nine ten eleven twelve"
    lines = tm.wrap(long_text, max_w=40, size=10.5, max_lines=2)
    assert len(lines) <= 2


def test_block_height_scales_with_line_count():
    size = 10.5
    one_line = tm.block_height("short", max_w=1000, size=size)
    many_lines = tm.block_height("one two three four five six seven eight", max_w=40, size=size)
    assert many_lines > one_line
    assert one_line == pytest.approx(size * tm.LINE_HEIGHT)


def test_fits_true_when_box_is_generous():
    assert tm.fits("short label", box_w=500, box_h=200, size=10.5)


def test_fits_false_when_box_is_tiny():
    assert not tm.fits("a much longer label that will not fit", box_w=40, box_h=20, size=10.5)


def test_would_rewrap_detects_undersized_declaration():
    long_text = "one two three four five six seven eight nine ten"
    # Engine declared only 1 line for a box that (at this width) needs several.
    assert tm.would_rewrap(long_text, declared_lines=1, max_w=60, size=10.5)


def test_would_rewrap_false_when_declaration_matches_reality():
    text = "short"
    real_lines = len(tm.wrap(text, max_w=200, size=10.5))
    assert not tm.would_rewrap(text, declared_lines=real_lines, max_w=200, size=10.5)


def test_fallback_ratio_used_without_font(monkeypatch):
    """When no TTF is resolvable, text_width must still return a positive,
    deterministic estimate rather than raising."""
    monkeypatch.setattr(tm, "_font_path", lambda bold: None)
    tm._font.cache_clear()
    tm.text_width.cache_clear()
    w = tm.text_width("Illinois", 10.5)
    assert w > 0
    assert w == pytest.approx(len("Illinois") * 10.5 * tm._FALLBACK_RATIO[False])
