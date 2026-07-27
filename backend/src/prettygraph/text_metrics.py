"""Real font metrics for the layout/validation pipeline.

Every geometry pass in `prettygraph` and the validator that checks its output
used to guess text width with a flat `len(s) * 6.6` (or similar) constant —
Helvetica/Arial glyphs are not fixed-width, so `"Illinois"` and `"WWWWWWWW"`
(same 8 characters) are ~30px vs ~82px in reality: a 4.4x error. Any card
sized off that guess either wraps in draw.io when the engine assumed one
line, or leaves dead whitespace when it assumed the widest possible glyph.

This module is the SINGLE source of truth for text width/wrap/height across
the codebase — `layout_engine.py`, `refined.py`, `router.py`,
`domain/validation/validate_drawio.py`, and `drawio_ingest.py` all import
from here instead of keeping their own `len(s) * k` estimate. That matters
because the router/validator previously used the exact same wrong constant
as the engine that drew the boxes ("mirrors validate_drawio's edge-label
estimate"), so the metrics that were supposed to catch the bug just agreed
with it instead.

draw.io renders with `fontFamily=Helvetica` by default; Liberation Sans is
metric-compatible with Helvetica/Arial (same glyph widths), so measuring
against it is equivalent to measuring what draw.io will actually lay out.
`slide.py` already loads PIL fonts for its own hero-band text — this module
generalizes that lookup so both call sites (and everything else) share one
font-resolution order instead of drifting.
"""

from __future__ import annotations

import functools
import os

LINE_HEIGHT = 1.2  # mxConstants.LINE_HEIGHT — draw.io's own line-height factor; do not change.

# Fallback char-width RATIO (relative to font size) used only when no TTF is
# resolvable on the host (bare containers, some CI images). This is the same
# ballpark the old `len(s) * 6.6` constants implied at size ~10.5 (6.6/10.5
# ≈ 0.63), kept as a safety net so behavior degrades gracefully rather than
# crashing — never the default path on any dev/CI box with fonts installed.
_FALLBACK_RATIO = {False: 0.56, True: 0.60}

# Search order matches slide.py's existing convention (DejaVu first, then
# Liberation) plus both common Debian package layouts for Liberation Sans.
_CANDIDATES: dict[bool, tuple[str, ...]] = {
    False: (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ),
    True: (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ),
}


@functools.lru_cache(maxsize=8)
def _font_path(bold: bool) -> str | None:
    for path in _CANDIDATES[bold]:
        if os.path.exists(path):
            return path
    return None


@functools.lru_cache(maxsize=256)
def _font(size_q: int, bold: bool):
    """Load a PIL font at quantized size `size_q` (size * 4, for sub-pixel
    accuracy on the getlength() call below). Returns None if PIL or a usable
    TTF isn't available — callers fall back to the ratio estimate."""
    path = _font_path(bold)
    if not path:
        return None
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    try:
        return ImageFont.truetype(path, size_q)
    except OSError:
        return None


def has_real_metrics() -> bool:
    """True when a real TTF is resolvable (i.e. text_width measures actual
    glyphs, not the fallback ratio). Tests use this to skip precision
    assertions on hosts without fonts installed."""
    return _font_path(False) is not None


@functools.lru_cache(maxsize=20000)
def text_width(s: str, size: float, bold: bool = False) -> float:
    """Pixel width of `s` rendered at `size` (draw.io px), matching the
    Helvetica/Arial metrics draw.io itself uses. Falls back to a flat
    per-character ratio if no font is resolvable on this host."""
    s = str(s or "")
    if not s:
        return 0.0
    font = _font(max(1, round(size * 4)), bold)
    if font is None:
        return len(s) * size * _FALLBACK_RATIO[bold]
    return font.getlength(s) / 4.0


def wrap(s: str, max_w: float, size: float, bold: bool = False, max_lines: int | None = None) -> list[str]:
    """Greedy word-wrap matching draw.io's own wrapping: a word is pushed to
    the next line once the trial line would exceed `max_w`. Respects
    existing newlines in `s`. If `max_lines` is given, stops appending once
    reached (the caller is responsible for showing this is a truncation)."""
    out: list[str] = []
    for para in str(s or "").split("\n"):
        cur = ""
        for word in para.split():
            cand = f"{cur} {word}".strip()
            if text_width(cand, size, bold) <= max_w or not cur:
                cur = cand
            else:
                out.append(cur)
                cur = word
                if max_lines is not None and len(out) >= max_lines:
                    cur = ""
                    break
        if cur:
            out.append(cur)
        if max_lines is not None and len(out) >= max_lines:
            break
    return out or [""]


def block_height(s: str, max_w: float, size: float, bold: bool = False) -> float:
    """Total rendered height of `s` wrapped to `max_w` at `size`."""
    return len(wrap(s, max_w, size, bold)) * size * LINE_HEIGHT


def fits(
    s: str,
    box_w: float,
    box_h: float,
    size: float,
    bold: bool = False,
    pad_x: float = 0,
    pad_y: float = 0,
) -> bool:
    """True if `s` wrapped to the available width fits within the box height,
    after padding is subtracted."""
    return block_height(s, max(1.0, box_w - pad_x), size, bold) <= box_h - pad_y


def would_rewrap(s: str, declared_lines: int, max_w: float, size: float, bold: bool = False) -> bool:
    """True if real wrapping needs MORE lines than the engine declared/sized
    for (i.e. draw.io will silently re-wrap this box at render time)."""
    return len(wrap(s, max_w, size, bold)) > max(1, declared_lines)
