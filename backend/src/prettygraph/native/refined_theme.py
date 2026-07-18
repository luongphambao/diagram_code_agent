"""Design tokens for the "refined" typographic preset (playbook look).

Single source of truth for the refined style — the flat, document-grade look
from General_Drawio_Optimization_Playbook.md, upgraded to the client-deliverable
standard: neutral near-white zones with restrained accent tabs (≤3 hues: navy
for the main flow, slate for ops/governance, green for outcomes), white cards
with a 38px full-color vendor icon + bold heading + short body lines, semantic
edge classes (secondary flows visually recessive), legend footer, 1920x1080
canvas. The full-color icons carry the color story; zone chrome stays quiet.

Deliberately PLAIN HEX (no light-dark() wrappers, unlike theme.py): the
reference recipe paints an explicit white background cell, so dark-mode
adaptivity is meaningless here and plain hex keeps the file portable to
non-draw.io renderers. Refined output is a light-canvas document by design.
"""

from __future__ import annotations

FONT = "Helvetica"

# Type scale per playbook §10.1 (px).
TYPE_SCALE = {
    "title": 30,
    "subtitle": 14,
    "backbone": 11,
    "tab": 11,
    "card": 10.5,
    "note": 9.5,
    "pill": 8.5,
    "legend": 10,
    "edge": 10,
}

# Ink colours (playbook §11: body text dark neutral, never pure black).
INK = {
    "title": "#101828",
    "body": "#101828",
    "muted": "#475467",
    "slate": "#536174",
}

# Zone hue registry: name -> (tab_fill, zone_stroke, zone_tint).
# CLIENT-DELIVERABLE PALETTE: zones are neutral near-white with quiet gray
# strokes — the saturated value lives ONLY in the tab chip, and active accents
# are capped at 3 hues (navy = main flow, slate = ops/governance, green =
# outcome) so the full-color vendor icons are the diagram's color story
# instead of competing pastel zone fills. Legacy hue KEYS are kept so specs
# and the hue-pick logic keep working — they now map onto the reduced accents.
ZONE_HUES: dict[str, tuple[str, str, str]] = {
    "blue": ("#1D4ED8", "#E4E7EC", "#FAFBFC"),
    "teal": ("#1D4ED8", "#E4E7EC", "#FAFBFC"),
    "purple": ("#1D4ED8", "#E4E7EC", "#FAFBFC"),
    "orange": ("#1D4ED8", "#E4E7EC", "#FAFBFC"),
    "green": ("#15803D", "#E4E7EC", "#F7FBF8"),
    "slate": ("#536174", "#E4E7EC", "#FCFCFD"),
}
# Default hue assignment order for main-flow zones (entry->core->state->storage->outcome).
HUE_ORDER = ["blue", "teal", "purple", "orange", "green", "slate"]

# Card-on-neutral stroke: uniform quiet gray — elevation comes from the white
# card on the near-white zone, not per-hue tinted borders.
CARD_STROKES: dict[str, str] = {
    "blue": "#D0D5DD",
    "teal": "#D0D5DD",
    "purple": "#D0D5DD",
    "orange": "#D0D5DD",
    "green": "#D0D5DD",
    "slate": "#D0D5DD",
}

# Refined edge classes: name -> (color, stroke_width, dashed).
# Primary request/data path is navy and prominent; execution is slate solid;
# out-of-band flows (monitoring/control/future) are THIN DASHED NEUTRALS so
# they read as annotation, not architecture.
EDGE_CLASSES: dict[str, tuple[str, float, bool]] = {
    "data": ("#1D4ED8", 1.7, False),
    "execution": ("#536174", 1.5, False),
    "outcome": ("#15803D", 1.4, False),
    "monitoring": ("#98A2B3", 1.1, True),
    "control": ("#536174", 1.1, True),
    "future": ("#C2C9D2", 1.0, True),
}
# Human legend labels for the classes worth legending (outcome/future edges are
# self-evident sink arrows in the reference and stay off the legend).
EDGE_LEGEND_LABELS = {
    "data": "Request / data flow",
    "execution": "Core execution",
    "monitoring": "Monitoring / telemetry",
    "control": "Control / access",
}
# Legacy FLOW_COLORS keys (constants.py) -> refined class, so existing specs
# with edge.flow keep working under the refined preset.
FLOW_ALIAS = {
    "serving": "execution",
    "registry": "data",
    "security": "control",
}

# Visual boundary rects (never parents): kind -> (fill, stroke, dashPattern, tab_fill).
# Boundaries stay inside the 3-accent budget: slate chrome + the green VPC
# dashed convention (shared with the outcome accent).
BOUNDARY: dict[str, tuple[str | None, str, str | None, str]] = {
    "cloud": ("#FCFCFD", "#98A2B3", None, "#536174"),
    "vpc": (None, "#15803D", "7 5", "#15803D"),
    "az": (None, "#98A2B3", "5 4", "#536174"),
    "onprem": (None, "#666666", "7 5", "#666666"),
}

# Chrome neutrals (backbone strip / footer band).
CHROME = {
    "strip_fill": "#F8FAFC",
    "strip_stroke": "#E4E7EC",
    "card_fill": "#FFFFFF",
    "bg": "#FFFFFF",
}

# Geometry constants (playbook §9: grid 10, spacing near multiples of 10).
GEO = {
    "page_w": 1920,
    "page_h": 1080,
    "margin": 40,
    "tab_overlap": 15,   # tab pill sits at zone.y - 15 (folder-tab metaphor)
    "tab_h": 30,
    "arc_zone": 8,       # cards + zones + boundaries
    "arc_pill": 12,      # tabs / scope pills / chips
    "zone_stroke_w": 1.3,
    "boundary_stroke_w": 1.4,
    "card_stroke_w": 1,
    "card_spacing": 10,
    "zone_pad": 14,      # inner padding between zone border and cards
    "zone_gap": 44,      # gap between adjacent zones (room for cross-zone edge labels)
    "card_gap": 14,      # vertical gap between stacked cards
    "body_line_max": 35, # chars per body line (playbook §12.4)
    "body_lines_max": 4,
    "footer_lane": 40,   # routing lane reserved above the footer band
}


def as_json() -> dict:
    """Serializable token dump (playbook §19) — written next to refined renders
    as design_tokens.json for traceability. Python stays the source of truth."""
    return {
        "font": FONT,
        "type_scale": TYPE_SCALE,
        "ink": INK,
        "zone_hues": {k: {"tab": v[0], "stroke": v[1], "tint": v[2]}
                      for k, v in ZONE_HUES.items()},
        "edge_classes": {k: {"color": v[0], "width": v[1], "dashed": v[2]}
                         for k, v in EDGE_CLASSES.items()},
        "boundary": {k: {"fill": v[0], "stroke": v[1], "dash": v[2], "tab": v[3]}
                     for k, v in BOUNDARY.items()},
        "geometry": GEO,
    }
