"""Design tokens ported verbatim from drawio-ai-kit/src/theme.mjs.

A small, cohesive set of PALE, theme-aware ``light-dark(light,dark)`` tints; AWS
icons carry the strong category colour, frames/bands stay pale. The native layout
engine reads these so every diagram inherits the house style by default.
"""

from __future__ import annotations

_STAGES = [
    "light-dark(#eaf3ec,#16241b)",  # green  (ingest)
    "light-dark(#fff3e9,#2a1d12)",  # orange (process)
    "light-dark(#fff8e6,#2a2410)",  # amber  (store)
    "light-dark(#f3eef8,#241b2e)",  # purple (serve)
    "light-dark(#e9eef4,#19222e)",  # blue-grey
]
_STAGE_STROKE = ["#82B366", "#D79B00", "#D6B656", "#9673A6", "#6C8EBF"]


class _Theme:
    stages = _STAGES
    stage_stroke_list = _STAGE_STROKE
    base = "light-dark(#ffffff,#0f1620)"
    base_stroke = "#5A6B7B"
    endpoint = "light-dark(#eaf3ff,#10202e)"
    endpoint_stroke = "#6C8EBF"
    band = "light-dark(#eef1f5,#1b2430)"
    band_stroke = "#8593A3"
    subnet_public = "light-dark(#eef5e6,#1a2410)"
    subnet_public_stroke = "#7AA116"
    subnet_private = "light-dark(#e6f4f4,#0f2424)"
    subnet_private_stroke = "#00A4A6"
    region_stroke = "#147EBA"
    vpc_stroke = "#8C4FFF"
    account_stroke = "#C2487A"
    az_stroke = "#2F9491"
    note = "light-dark(#fbe7d4,#3a2a16)"
    note_stroke = "#D79B00"
    onprem = "light-dark(#eef1f5,#181f29)"
    onprem_stroke = "#666666"
    # topology boundary strokes (Workstream 1 — real Cloud/VPC/Subnet/AZ nesting).
    # VPC is GREEN per the production reference, distinct from the violet vpc_stroke
    # used by AWS group stencils; AZ frames render dashed teal.
    zone_cloud_stroke = "#232F3E"
    zone_vpc_stroke = "#1BA641"
    zone_az_stroke = "#00A4A6"
    font_color = "light-dark(#1B2733,#CFE0F0)"
    # edge tokens
    edge_stroke = "light-dark(#2D6A9F,#5B9BD5)"
    edge_stroke_width = 2
    edge_font_color = "light-dark(#1B2733,#CFE0F0)"
    edge_label_bg = "light-dark(#FFFFFF,#0B0F14)"
    # fonts / gaps
    font_title = 14
    font_label = 11
    font_small = 10
    gap_layer = 50
    gap_item = 16


THEME = _Theme()


def stage_fill(i: int) -> str:
    return _STAGES[i % len(_STAGES)]


def stage_stroke(i: int) -> str:
    return _STAGE_STROKE[i % len(_STAGE_STROKE)]
