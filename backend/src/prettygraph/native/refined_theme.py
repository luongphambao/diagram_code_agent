"""Design tokens for the "refined" typographic preset (playbook look).

Single source of truth for the refined style — the flat, icon-free,
document-grade look from General_Drawio_Optimization_Playbook.md and the
deepstream_aws_architecture_refined.drawio reference: numbered tinted zones
with folder-tab pills, white cards with bold heading + short body lines,
semantic edge classes, legend footer, 1920x1080 canvas.

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
# Formula from the reference: saturated tab + mid-saturation stroke + pale tint,
# all the same hue. Semantic mapping per playbook §11: blue=entry/data-flow,
# teal=core execution, purple=custom logic/state, orange=operations/storage,
# green=outcome/success, slate=neutral/ops-governance.
ZONE_HUES: dict[str, tuple[str, str, str]] = {
    "blue": ("#2563EB", "#B8CDF7", "#F2F7FF"),
    "teal": ("#0F766E", "#9DD7CE", "#F1FBF9"),
    "purple": ("#6D4DB3", "#C7B8EA", "#F7F5FF"),
    "orange": ("#C96A1B", "#E7B27E", "#FFF8F0"),
    "green": ("#2E7D4F", "#A8D3B7", "#F4FBF6"),
    "slate": ("#536174", "#D0D5DD", "#FFFFFF"),
}
# Default hue assignment order for main-flow zones (entry->core->state->storage->outcome).
HUE_ORDER = ["blue", "teal", "purple", "orange", "green", "slate"]

# Card-on-tint stroke: one step stronger than the zone stroke so white cards
# read as elevated without shadows (reference: #9DBAF3 on a #B8CDF7 zone).
CARD_STROKES: dict[str, str] = {
    "blue": "#9DBAF3",
    "teal": "#7BC8BC",
    "purple": "#C7B8EA",
    "orange": "#E7B27E",
    "green": "#A8D3B7",
    "slate": "#D0D5DD",
}

# Refined edge classes: name -> (color, stroke_width, dashed).
# Solid = live data/execution; dashed = out-of-band (monitoring/control).
# strokeWidth encodes prominence: main spine 1.7 -> telemetry 1.3.
EDGE_CLASSES: dict[str, tuple[str, float, bool]] = {
    "data": ("#2563EB", 1.7, False),
    "execution": ("#0F766E", 1.6, False),
    "outcome": ("#2E7D4F", 1.4, False),
    "monitoring": ("#C96A1B", 1.3, True),
    "control": ("#536174", 1.3, True),
    "future": ("#98A2B3", 1.3, True),
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
BOUNDARY: dict[str, tuple[str | None, str, str | None, str]] = {
    "cloud": ("#FCFCFD", "#98A2B3", None, "#C45500"),
    "vpc": (None, "#2E7D4F", "7 5", "#2E7D4F"),
    "az": (None, "#69AFC0", "5 4", "#2F6672"),
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
    "zone_gap": 30,      # gap between adjacent zones
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
