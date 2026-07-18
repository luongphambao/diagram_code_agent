"""Diagram-type preset registry — ported from drawio-ai-kit/src/types.mjs.

Each preset captures the topology/routing DEFAULTS for a family of diagrams
(orientation, edge-corner style, lane strategy, grouping convention). These
set edge-routing defaults, not layout restrictions — real systems compose
presets, same as the kit (rules/diagram-types.md).

``layout_intent`` on the render_spec is the single vocabulary: the 4
original values (left_to_right_pipeline, top_down_stack, layered, grid) map
onto the pipeline/hierarchy/layered presets below so there is one source of
truth for edge-corner defaults; the 5 new values added in this port
(hub_spoke, hierarchy, mesh, sequence, hybrid) key directly into the
registry by name.
"""

from __future__ import annotations

DIAGRAM_TYPES: dict[str, dict] = {
    "pipeline": {
        "label": "Layered pipeline (data/request flow)",
        "orientation": "LR", "edge_corner": "rounded",
        "lane_strategy": "corridor", "grouping": "columns-by-tier",
    },
    "hierarchy": {
        "label": "Hierarchy / org tree (Landing Zone)",
        "orientation": "TB", "edge_corner": "sharp",
        "lane_strategy": "shared-bus", "grouping": "nested-ou",
    },
    "network": {
        "label": "VPC network topology (Multi-AZ)",
        "orientation": "LR", "edge_corner": "rounded",
        "lane_strategy": "corridor", "grouping": "nested-region-az-subnet",
    },
    "hub_spoke": {
        "label": "Hub-and-spoke / event bus",
        "orientation": "radial", "edge_corner": "rounded",
        "lane_strategy": "hub-center", "grouping": "center-hub",
    },
    "hybrid": {
        "label": "Hybrid / DR (on-prem <-> cloud)",
        "orientation": "LR", "edge_corner": "rounded",
        "lane_strategy": "site-link", "grouping": "two-sites",
    },
    "mesh": {
        "label": "Multi-account connectivity / service mesh",
        "orientation": "free", "edge_corner": "rounded",
        "lane_strategy": "association", "grouping": "peer-accounts",
    },
    "sequence": {
        "label": "Sequence / numbered request walkthrough",
        "orientation": "steps", "edge_corner": "rounded",
        "lane_strategy": "numbered-steps", "grouping": "components",
    },
    "bpmn": {
        "label": "BPMN swimlane process (roles x phases)",
        "orientation": "LR", "edge_corner": "rounded",
        "lane_strategy": "swimlane", "grouping": "pool-lane-phase",
    },
}

# The 4 pre-existing layout_intent values, mapped onto a DIAGRAM_TYPES key so
# both vocabularies share one edge-corner/orientation source of truth.
_INTENT_ALIASES = {
    "left_to_right_pipeline": "pipeline",
    "top_down_stack": "hierarchy",
    "layered": "pipeline",
    "grid": "pipeline",
}

# The 5 new layout_intent values added in this port key straight into the
# registry (name matches a DIAGRAM_TYPES key already).
NEW_INTENTS = frozenset({"hub_spoke", "hierarchy", "mesh", "sequence", "hybrid"})


def type_preset(intent: str) -> dict:
    """Resolve a layout_intent string to its DIAGRAM_TYPES preset (default:
    pipeline — the house style's dense LR flow)."""
    key = _INTENT_ALIASES.get(intent, intent)
    return DIAGRAM_TYPES.get(key, DIAGRAM_TYPES["pipeline"])


def edge_rounded(intent: str, role: str = "") -> bool:
    """Whether an edge of ``role`` should render with rounded corners.

    tree/fanout roles are ALWAYS sharp regardless of preset (a branching
    edge reads clearer with a hard corner at the split point) — mirrors the
    kit's edgeRounded(). Every other role follows the preset's edge_corner.
    """
    if role in ("tree", "fanout"):
        return False
    return type_preset(intent)["edge_corner"] == "rounded"
