"""
Real font metrics for the layout engine.

Drop in at: backend/src/prettygraph/text_metrics.py

WHY: layout_engine.py currently sizes every box with `len(s) * 6.6`, which assumes
all glyphs have equal width. At Helvetica 10.5px an `i` is 2.3px and a `W` is
10.2px - a 4.4x error. draw.io then re-wraps the text with real metrics inside the
box the engine already froze, so 44% of cards in this repo's own examples get
re-wrapped and 21% overflow vertically.

Worse: validate_drawio.py:1198 and refined.py:176 use the SAME wrong constant, so
the quality metric agrees with the bug instead of catching it. Fix all three
together or the metrics will start (correctly) failing good diagrams.

draw.io uses fontFamily=Helvetica by default. Liberation Sans is metric-compatible
with Helvetica/Arial, so measuring with it predicts draw.io's own wrapping.
"""
from __future__ import annotations

import functools
import os

from PIL import ImageFont

# mxConstants.LINE_HEIGHT - do not change, this is what draw.io actually uses
LINE_HEIGHT = 1.2

_FONT_PATHS = {
    False: [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
    True: [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/LiberationSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
}

# Fallback ratios, used only if no TTF is found on the host. Still better than a
# single constant because they are per-weight and calibrated to Helvetica.
_FALLBACK_RATIO = {False: 0.512, True: 0.548}
_HAVE_FONT: bool | None = None


def _resolve(bold: bool) -> str | None:
    for p in _FONT_PATHS[bold]:
        if os.path.exists(p):
            return p
    return None


@functools.lru_cache(maxsize=512)
def _font(size_quad: int, bold: bool):
    """size_quad = round(size * 4); measuring at 4x gives sub-pixel accuracy."""
    path = _resolve(bold)
    if path is None:
        return None
    return ImageFont.truetype(path, size_quad)


def fonts_available() -> bool:
    """True when real metrics are in use. Log this once at startup - silently
    falling back to ratios is how this class of bug survives."""
    global _HAVE_FONT
    if _HAVE_FONT is None:
        _HAVE_FONT = _resolve(False) is not None and _resolve(True) is not None
    return _HAVE_FONT


@functools.lru_cache(maxsize=32768)
def text_width(s: str, size: float, bold: bool = False) -> float:
    """Width of `s` in px at `size` px. Cached - hot path in the layout engine."""
    if not s:
        return 0.0
    f = _font(int(round(size * 4)), bold)
    if f is None:
        return len(s) * size * _FALLBACK_RATIO[bold]
    return f.getlength(s) / 4.0


def fits_width(s: str, max_w: float, size: float, bold: bool = False) -> bool:
    return text_width(s, size, bold) <= max_w


def wrap(s: str, max_w: float, size: float, bold: bool = False) -> list[str]:
    """Greedy word wrap matching draw.io's behaviour. Honours existing newlines.
    A single word wider than max_w is kept on its own line (never dropped)."""
    out: list[str] = []
    for para in str(s).split("\n"):
        cur = ""
        for w in para.split():
            cand = f"{cur} {w}" if cur else w
            if text_width(cand, size, bold) <= max_w or not cur:
                cur = cand
            else:
                out.append(cur)
                cur = w
        out.append(cur)
    return out


def wrapped(s: str, max_w: float, size: float, bold: bool = False) -> str:
    return "\n".join(wrap(s, max_w, size, bold))


def line_count(s: str, max_w: float, size: float, bold: bool = False) -> int:
    return len(wrap(s, max_w, size, bold))


def block_height(s: str, max_w: float, size: float, bold: bool = False) -> float:
    """Rendered height of a wrapped text block, in px."""
    return line_count(s, max_w, size, bold) * size * LINE_HEIGHT


def fits(s: str, box_w: float, box_h: float, size: float, bold: bool = False,
         pad_x: float = 0.0, pad_y: float = 0.0) -> bool:
    """Does `s` fit inside the box after wrapping? Use this as an assertion in
    the layout engine, not as a hope."""
    return block_height(s, box_w - pad_x, size, bold) <= (box_h - pad_y)


def measure_block(lines, max_w: float, sizes, bolds=None) -> tuple[float, float]:
    """Measure a stack of text runs with different sizes (title + sublabels).

    lines : list[str]
    sizes : float or list[float] - px size per line
    bolds : bool or list[bool]

    Returns (natural_width, wrapped_height). natural_width is the width needed to
    keep every line on one line - use it as the box's preferred width, then clamp.
    """
    n = len(lines)
    if isinstance(sizes, (int, float)):
        sizes = [float(sizes)] * n
    if bolds is None:
        bolds = [False] * n
    elif isinstance(bolds, bool):
        bolds = [bolds] * n
    nat = max((text_width(l, s, b) for l, s, b in zip(lines, sizes, bolds)), default=0.0)
    h = sum(block_height(l, max_w, s, b) for l, s, b in zip(lines, sizes, bolds))
    return nat, h


def label_box(label: str, size: float, bold: bool = False,
              pad_x: float = 4.0, pad_y: float = 2.5) -> tuple[float, float]:
    """Bounding box of an edge label including its background padding.
    Replaces `lw = len(label) * 6.6` in router.py, refined.py and
    validate_drawio.py - all three must use this, or the label-overlap metric
    keeps validating the estimate rather than the render."""
    lines = str(label).split("\n")
    w = max((text_width(l, size, bold) for l in lines), default=0.0) + pad_x * 2
    h = len(lines) * size * LINE_HEIGHT + pad_y * 2
    return w, h


def truncate_to(s: str, max_w: float, size: float, bold: bool = False,
                ellipsis: str = "…") -> str:
    """Hard-truncate a single line that must not wrap (table cells, pills)."""
    if text_width(s, size, bold) <= max_w:
        return s
    ew = text_width(ellipsis, size, bold)
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if text_width(s[:mid], size, bold) + ew <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo].rstrip() + ellipsis


# --------------------------------------------------------------------------- self-check
if __name__ == "__main__":
    print(f"real font metrics available: {fonts_available()}")
    print(f"{'string':34s} {'measured':>9s} {'len*6.6':>9s} {'error':>8s}")
    print("-" * 64)
    worst = 0.0
    for s in ["iiiiiiiiii", "WWWWWWWWWW", "Underwriting API (BFF)",
              "ASP.NET Core 8 LTS · REST/JSON", "SQL Server 2022 — System of Record",
              "Illinois", "AlwaysOn AG, synchronous commit across two rooms"]:
        m = text_width(s, 10.5)
        g = len(s) * 6.6
        err = (g - m) / m * 100
        worst = max(worst, abs(err))
        print(f"{s[:34]:34s} {m:8.1f}px {g:8.1f}px {err:+7.0f}%")
    print("-" * 64)
    print(f"worst-case error of the len*6.6 estimate: {worst:.0f}%")
    assert wrap("a b c d e f g h", 30, 10) != ["a b c d e f g h"]
    assert fits("short", 100, 20, 10)
    assert not fits("a very long sentence that cannot possibly fit", 60, 14, 10)
    print("assertions OK")
