"""True UML Sequence Diagram native renderer — improvement plan MVP-3 phase 2,
the pilot proving the typed-diagram foundation (registry.py) on the hardest
native geometry so far: y-ordered lifelines, activation bars and combined
fragments, none of which the flexbox-style `layout_engine.py` measure/place
model fits (that engine sizes containers from their CONTENT; a sequence
diagram's geometry is driven by a fixed timeline axis instead).

Composes directly on a `Diagram` — the same model `refined.py` uses to bypass
`render_tree()` — rather than going through `layout_engine.py`'s node-kind
dispatch. Message lines are emitted as real mxCell edges with `source`/
`target` set to the participant lifeline ids (so semantic-preservation
recall and draw.io's own reconnect-in-editor UX both work), but with
`exitY`/`entryY` computed as fractions of each lifeline's own height so every
message renders as an exactly horizontal line at its `order`'s row — the
deterministic A*/nudge router (`router.py`) is intentionally NOT used here;
it optimizes for obstacle-avoiding orthogonal routing between boxes, not for
holding a fixed timeline row, so calling it would fight this diagram family's
one hard layout constraint instead of serving it.

Draw.io ships `umlLifeline`/`umlActor`/`umlFrame` as native shape classes (not
catalog stencils needing a lookup — see the proposal §3's own "Xuất trực tiếp
shape `umlLifeline` vào draw.io"), so this module needs no drawio_catalog
dependency at all, unlike bpmn.py.
"""

from __future__ import annotations

from .builder import Diagram, Z_CHROME, Z_CONTAINER, Z_EDGE, Z_NODE, _esc
from .theme import THEME

MARGIN_X = 60
LANE_WIDTH = 180
LIFELINE_TOP = 70
HEADER_H = 40
ACTOR_W = 30
ACTOR_H = 50
ROW_PITCH = 60
FIRST_ROW_GAP = 50  # gap between the lifeline header and the first message row
BOTTOM_PAD = 40
FRAGMENT_PAD_X = 30
FRAGMENT_PAD_Y_TOP = 25
FRAGMENT_PAD_Y_BOTTOM = 15
ACTIVATION_W = 10
ACTIVATION_PAD = 10
SELF_MSG_LOOP_W = 50

_LIFELINE_STYLE = (
    "shape=umlLifeline;perimeter=lifelinePerimeter;whiteSpace=wrap;html=1;"
    "container=1;collapsible=0;recursiveResize=0;outlineConnect=0;"
    f"fillColor={THEME.base};strokeColor={THEME.base_stroke};fontColor={THEME.font_color};"
)
_ACTOR_STYLE = (
    "shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;"
    f"outlineConnect=0;fillColor={THEME.base};strokeColor={THEME.base_stroke};"
    f"fontColor={THEME.font_color};"
)
_FRAME_STYLE = (
    "shape=umlFrame;whiteSpace=wrap;html=1;pointerEvents=0;"
    f"fillColor=none;strokeColor={THEME.base_stroke};fontColor={THEME.font_color};"
    "align=left;verticalAlign=top;fontSize=10;"
)
_ACTIVATION_STYLE = (
    f"rounded=0;whiteSpace=wrap;html=1;fillColor={THEME.base};"
    f"strokeColor={THEME.base_stroke};"
)

_MESSAGE_STYLE_BY_KIND: dict[str, str] = {
    "sync": "html=1;endArrow=block;endFill=1;dashed=0;",
    "async": "html=1;endArrow=open;endFill=0;dashed=0;",
    "return": "html=1;endArrow=open;endFill=0;dashed=1;",
    "create": "html=1;endArrow=block;endFill=1;dashed=0;",
    "destroy": "html=1;endArrow=block;endFill=1;dashed=0;",
}


def _lane_x(index: int) -> float:
    return MARGIN_X + index * LANE_WIDTH + LANE_WIDTH / 2


def _order_rows(spec: dict) -> tuple[list[int], dict[int, float]]:
    """Sorted unique message orders -> the y each maps to. Robust to gaps
    (lint_sequence flags them, but the renderer never crashes on one)."""
    orders = sorted({int(m.get("order", 0)) for m in spec.get("messages", [])})
    if not orders:
        orders = [1]
    y0 = LIFELINE_TOP + HEADER_H + FIRST_ROW_GAP
    order_to_y = {o: y0 + i * ROW_PITCH for i, o in enumerate(orders)}
    return orders, order_to_y


def _emit_message_edge(d: Diagram, eid: str, src: str, tgt: str, label: str, style_extra: str) -> None:
    """A real mxCell edge (source/target = participant lifeline ids, so
    semantic-preservation recall + draw.io reconnect both work) with
    exitY/entryY set so it renders as an exactly horizontal line — see the
    module docstring for why the deterministic router is bypassed here.
    """
    src_r, tgt_r = d.R[src], d.R[tgt]
    # Every lifeline shares the same y0/height (built uniformly below), so the
    # SAME fraction on both sides always yields the same absolute y — this is
    # what keeps the line perfectly horizontal without any waypoint math.
    frac_src = 0.0 if src_r["h"] == 0 else (d.R[eid + "_y"]["y"] - src_r["y"]) / src_r["h"]
    frac_tgt = 0.0 if tgt_r["h"] == 0 else (d.R[eid + "_y"]["y"] - tgt_r["y"]) / tgt_r["h"]
    exit_x = 1 if tgt_r["x"] >= src_r["x"] else 0
    entry_x = 0 if tgt_r["x"] >= src_r["x"] else 1
    style = (
        f"edgeStyle=none;rounded=0;fontSize=10;fontColor={THEME.edge_font_color};"
        f"strokeColor={THEME.edge_stroke};strokeWidth={THEME.edge_stroke_width};"
        f"exitX={exit_x};exitY={frac_src:.4f};exitDx=0;exitDy=0;"
        f"entryX={entry_x};entryY={frac_tgt:.4f};entryDx=0;entryDy=0;"
        f"labelBackgroundColor={THEME.edge_label_bg};" + style_extra
    )
    wp_xml = ""
    if src == tgt:
        # Self-message: bulge right in a small U so the loop is visible instead
        # of collapsing onto the lifeline itself.
        y = d.R[eid + "_y"]["y"]
        x = src_r["x"] + src_r["w"] / 2 + SELF_MSG_LOOP_W
        wp_xml = f'<Array as="points"><mxPoint x="{x:.0f}" y="{y:.0f}"/></Array>'
    d._emit_cell(
        eid,
        f'<mxCell id="{eid}" value="{_esc(label)}" style="{style}" edge="1" parent="1" '
        f'source="{src}" target="{tgt}"><mxGeometry relative="1" as="geometry">'
        f"{wp_xml}</mxGeometry></mxCell>",
        Z_EDGE,
    )
    del d.R[eid + "_y"]  # scratch entry only used to compute the fraction above


def build_sequence_tree(spec: dict, *, flat: bool = False, plan: dict | None = None) -> tuple[Diagram, dict]:
    """Build a native UML sequence diagram from a sequence render_spec
    (tools/analysis/sequence_tools.py's projection of SequenceSpec).

    Same (Diagram, root) contract as `topology.build_tree` — registered into
    `prettygraph.native.registry` under kind "sequence" so `build_tree` and
    `_render_native_from_spec` divert here for `spec["kind"] == "sequence"`
    without touching the architecture/BPMN dispatch at all.
    """
    participants = [p for p in spec.get("participants", []) if p.get("id")]
    messages = [m for m in spec.get("messages", []) if m.get("from") and m.get("to")]
    fragments = list(spec.get("fragments", []))
    activations = list(spec.get("activations", []))

    orders, order_to_y = _order_rows(spec)
    bottom_y = max(order_to_y.values()) + BOTTOM_PAD if order_to_y else LIFELINE_TOP + HEADER_H + 200
    n = max(len(participants), 1)
    page_w = 2 * MARGIN_X + n * LANE_WIDTH
    page_h = round(bottom_y + 40)

    d = Diagram("sequence", contract="bake", flat=flat, page=(round(page_w), page_h))

    lane_x: dict[str, float] = {}
    for i, p in enumerate(participants):
        pid = p["id"]
        x = _lane_x(i)
        lane_x[pid] = x
        label = p.get("label") or pid
        if p.get("kind") == "actor":
            # draw.io computes exitY/entryY anchor points against the CELL'S
            # REAL emitted geometry, not any bookkeeping we do on the Python
            # side — so `pid` itself must be a real full-height cell (like
            # every other participant), or _emit_message_edge's fraction
            # lands nowhere near the intended row. Split into two cells: an
            # invisible full-height rect (`pid`) that messages actually
            # attach to, and a decorative visible glyph (`pid_glyph`) drawn
            # on top of it at the natural stick-figure size.
            d._put(
                pid,
                "1",
                x - ACTOR_W / 2,
                LIFELINE_TOP,
                ACTOR_W,
                bottom_y - LIFELINE_TOP,
                "html=1;fillColor=none;strokeColor=none;",
                "",
                z=Z_CONTAINER,
            )
            d.R[pid]["ob"] = True
            d._put(
                f"{pid}_glyph", "1", x - ACTOR_W / 2, LIFELINE_TOP, ACTOR_W, ACTOR_H, _ACTOR_STYLE, label, z=Z_NODE
            )
            # umlActor has no built-in lifeline tail — draw the dashed vertical
            # line by hand from below the glyph down to the timeline's bottom.
            line_style = f"html=1;dashed=1;endArrow=none;startArrow=none;strokeColor={THEME.base_stroke};"
            d._emit_cell(
                f"{pid}_line",
                f'<mxCell id="{pid}_line" style="{line_style}" edge="1" parent="1">'
                f'<mxGeometry relative="1" as="geometry">'
                f'<mxPoint x="{x:.0f}" y="{LIFELINE_TOP + ACTOR_H:.0f}" as="sourcePoint"/>'
                f'<mxPoint x="{x:.0f}" y="{bottom_y:.0f}" as="targetPoint"/>'
                f"</mxGeometry></mxCell>",
                Z_CONTAINER,
            )
        else:
            d._put(
                pid,
                "1",
                x - LANE_WIDTH / 2 + 10,
                LIFELINE_TOP,
                LANE_WIDTH - 20,
                bottom_y - LIFELINE_TOP,
                _LIFELINE_STYLE,
                label,
                z=Z_CONTAINER,
            )
            d.R[pid]["ob"] = True

    # Combined fragments (drawn first so their Z_CONTAINER frame sits behind
    # activations/messages, matching how a real sequence diagram reads).
    involved_x: dict[tuple[int, int], list[float]] = {}
    for m in messages:
        order = int(m.get("order", 0))
        for pid in (m.get("from"), m.get("to")):
            x = lane_x.get(pid)
            if x is None:
                continue
            for frag in fragments:
                lo, hi = int(frag.get("start_order", 0)), int(frag.get("end_order", 0))
                if lo <= order <= hi:
                    key = (lo, hi)
                    involved_x.setdefault(key, []).append(x)
    for i, frag in enumerate(fragments):
        lo, hi = int(frag.get("start_order", 0)), int(frag.get("end_order", 0))
        xs = involved_x.get((lo, hi)) or list(lane_x.values())
        if not xs:
            continue
        x0 = min(xs) - FRAGMENT_PAD_X
        x1 = max(xs) + FRAGMENT_PAD_X
        y0 = order_to_y.get(lo, LIFELINE_TOP + HEADER_H) - FRAGMENT_PAD_Y_TOP
        y1 = order_to_y.get(hi, bottom_y) + FRAGMENT_PAD_Y_BOTTOM
        kind = str(frag.get("kind") or "alt")
        condition = frag.get("condition") or ""
        label = f"{kind} [{condition}]" if condition else kind
        fid = f"frag_{i}"
        d._put(fid, "1", x0, y0, x1 - x0, max(y1 - y0, 40), _FRAME_STYLE, label, z=Z_CONTAINER)
        d.R[fid]["ob"] = False

    # Activation bars.
    for i, act in enumerate(activations):
        pid = act.get("participant")
        x = lane_x.get(pid)
        if x is None:
            continue
        lo, hi = int(act.get("start_order", 0)), int(act.get("end_order", 0))
        y0 = order_to_y.get(lo, LIFELINE_TOP + HEADER_H) - ACTIVATION_PAD
        y1 = order_to_y.get(hi, y0 + 20) + ACTIVATION_PAD
        aid = f"act_{i}"
        d._put(
            aid,
            "1",
            x - ACTIVATION_W / 2,
            y0,
            ACTIVATION_W,
            max(y1 - y0, 20),
            _ACTIVATION_STYLE,
            "",
            z=Z_NODE,
        )
        d.R[aid]["ob"] = True

    # Messages — one horizontal row per declared order.
    for m in messages:
        order = int(m.get("order", 0))
        src, tgt = m.get("from"), m.get("to")
        if src not in lane_x or tgt not in lane_x:
            continue
        y = order_to_y.get(order, LIFELINE_TOP + HEADER_H + FIRST_ROW_GAP)
        kind = str(m.get("kind") or "sync")
        label = m.get("label") or ""
        if kind == "create":
            label = f"«create» {label}" if label else "«create»"
        eid = f"msg_{order}"
        # Scratch rect solely to hand the target y through to
        # _emit_message_edge (deleted again inside it) — keeps that helper's
        # signature free of a 6th positional arg for one internal value.
        d.R[eid + "_y"] = {"y": y}
        _emit_message_edge(d, eid, src, tgt, label, _MESSAGE_STYLE_BY_KIND.get(kind, _MESSAGE_STYLE_BY_KIND["sync"]))
        if kind == "destroy":
            d.text(f"{eid}_x", [lane_x[tgt] - 8, y - 10], 20, "X", fs=14)

    title = spec.get("title") or ""
    if title:
        d.text("__title", [0, 20], round(page_w), title, fs=14)
        d._cell_z[d._cell_index["__title"]] = Z_CHROME

    return d, {"kind": "sequence", "participants": [p["id"] for p in participants]}


def sequence_semantic_ids(spec: dict) -> tuple[list, list]:
    """(expected_ids, expected_edges) for check_semantic_preservation: every
    participant id must survive, plus every declared (from, to) message pair."""
    ids = [p["id"] for p in spec.get("participants", []) if p.get("id")]
    edges = [
        (m.get("from"), m.get("to"))
        for m in spec.get("messages", [])
        if m.get("from") and m.get("to")
    ]
    return ids, edges


def _register() -> None:
    from . import registry

    registry.register(
        registry.RendererEntry(
            kind="sequence",
            backend="native",
            tree_builder=build_sequence_tree,
            style_preset_label="sequence",
            semantic_ids_fn=sequence_semantic_ids,
            lint_kind="sequence",
        )
    )


_register()


__all__ = ["build_sequence_tree", "sequence_semantic_ids"]
