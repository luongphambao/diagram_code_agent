"""Backward-compatible re-exports — callers use `from prettygraph import Pretty` unchanged."""

from .audit import audit_layout
from .constants import (
    CLUSTER_KINDS,
    EDGE_COLOR,
    FLOW_COLORS,
    NODE_KINDS,
    PAGE_SIZE,
    PRO_ACCENTS,
    SLIDE_SIZE,
)
from .drawio import dot_to_drawio, merge_drawios_vertical
from .graph_builder import Pretty, _Cluster, _Edge, _Node, _esc, _est_text_w, _xml
from .slide import render_slide, vstack_pngs

__all__ = [
    "Pretty",
    "render_slide",
    "audit_layout",
    "dot_to_drawio",
    "merge_drawios_vertical",
    "vstack_pngs",
    "NODE_KINDS",
    "CLUSTER_KINDS",
    "PRO_ACCENTS",
    "FLOW_COLORS",
    "EDGE_COLOR",
    "PAGE_SIZE",
    "SLIDE_SIZE",
    # internals re-exported for any direct callers
    "_Node",
    "_Cluster",
    "_Edge",
    "_esc",
    "_xml",
    "_est_text_w",
]
