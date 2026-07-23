"""State Machine Diagram native renderer — improvement plan MVP-3 phase 4.

Unlike Sequence/ERD (phases 2-3), a state machine's transitions are a real
graph, not a fixed timeline or a small set of FK pointers — so this module
uses the DETERMINISTIC A*/nudge router (`d.link()`, same as BPMN's flows)
instead of hand-computed exit/entry fractions. States are still placed by a
simple BFS-layer layout (from the initial state(s), tolerant of cycles) since
`layout_engine.py`'s flexbox measure/place model has no notion of "layer by
graph distance from a root" — the same reasoning `erd.py`'s FK-layering gave
for not reusing that engine.
"""

from __future__ import annotations

from .builder import Diagram, Z_CHROME, Z_NODE
from .theme import THEME

MARGIN_X = 80
MARGIN_Y = 80
LAYER_GAP_X = 140
STATE_GAP_Y = 60
NORMAL_W, NORMAL_H = 140, 50
CIRCLE_D = 24
DIAMOND_W, DIAMOND_H = 60, 60
BAR_W, BAR_H = 10, 50

_NORMAL_STYLE = f"rounded=1;whiteSpace=wrap;html=1;fillColor={THEME.base};strokeColor={THEME.base_stroke};"
_INITIAL_STYLE = "ellipse;whiteSpace=wrap;html=1;fillColor=#000000;strokeColor=#000000;"
_FINAL_OUTER_STYLE = f"ellipse;whiteSpace=wrap;html=1;fillColor=none;strokeColor={THEME.base_stroke};"
_FINAL_INNER_STYLE = "ellipse;whiteSpace=wrap;html=1;fillColor=#000000;strokeColor=#000000;"
_CHOICE_STYLE = f"rhombus;whiteSpace=wrap;html=1;fillColor={THEME.base};strokeColor={THEME.base_stroke};"
_FORK_STYLE = "rounded=0;whiteSpace=wrap;html=1;fillColor=#000000;strokeColor=#000000;"
_HISTORY_STYLE = f"ellipse;whiteSpace=wrap;html=1;fillColor={THEME.base};strokeColor={THEME.base_stroke};fontStyle=1;"


def _layer_states(states: list[dict], transitions: list[dict]) -> dict[str, int]:
    """BFS-ish layer per state id: an initial state is layer 0; every other
    state's layer is the longest path from an initial state along the
    transition graph with back-edges removed (a retry/rework loop — e.g.
    `disputed -> received` looping back upstream — is a real, valid pattern
    in a status machine, not something lint_state_machine's exitless_loop
    check rejects). Without excluding back-edges, relaxing along a real cycle
    for `len(ids)+1` passes inflates every state on the cycle's layer by
    roughly `cycle_length` per pass instead of converging, blowing up the
    canvas width; DFS-classifying edges first keeps the ranking a DAG so the
    relaxation loop actually reaches a fixed point (lint_state_machine is
    still what's responsible for flagging unreachable/cyclic states)."""
    ids = [s["id"] for s in states if s.get("id")]
    layer = {i: 0 for i in ids}
    initial_ids = {s["id"] for s in states if s.get("kind") == "initial"}
    edges_all = [
        (t.get("from"), t.get("to"))
        for t in transitions
        if t.get("from") in layer and t.get("to") in layer
    ]
    adjacency: dict[str, list[str]] = {i: [] for i in ids}
    for src, dst in edges_all:
        adjacency[src].append(dst)

    back_edges: set[tuple[str, str]] = set()
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {i: WHITE for i in ids}

    def _dfs(u: str) -> None:
        color[u] = GRAY
        for v in adjacency.get(u, []):
            state = color.get(v, WHITE)
            if state == WHITE:
                _dfs(v)
            elif state == GRAY:
                back_edges.add((u, v))
        color[u] = BLACK

    for root in list(initial_ids) + ids:
        if color.get(root) == WHITE:
            _dfs(root)

    edges = [(src, dst) for src, dst in edges_all if (src, dst) not in back_edges]
    for _ in range(len(ids) + 1):
        changed = False
        for src, dst in edges:
            candidate = layer[src] + 1
            if candidate > layer[dst]:
                layer[dst] = candidate
                changed = True
        if not changed:
            break
    return layer


def _emit_state(d: Diagram, state: dict, x: float, y: float) -> None:
    sid = state["id"]
    label = state.get("label") or sid
    kind = state.get("kind") or "normal"
    if kind == "initial":
        d._put(sid, "1", x, y, CIRCLE_D, CIRCLE_D, _INITIAL_STYLE, "", z=Z_NODE)
        d.text(f"{sid}_lbl", [x - 20, y + CIRCLE_D + 2], CIRCLE_D + 40, label, fs=10)
    elif kind == "final":
        d._put(sid, "1", x, y, CIRCLE_D, CIRCLE_D, _FINAL_OUTER_STYLE, "", z=Z_NODE)
        d.R[sid]["ob"] = True
        pad = 5
        d._put(f"{sid}_dot", "1", x + pad, y + pad, CIRCLE_D - 2 * pad, CIRCLE_D - 2 * pad, _FINAL_INNER_STYLE, "", z=Z_NODE)
        d.text(f"{sid}_lbl", [x - 20, y + CIRCLE_D + 2], CIRCLE_D + 40, label, fs=10)
    elif kind == "choice":
        d._put(sid, "1", x, y, DIAMOND_W, DIAMOND_H, _CHOICE_STYLE, label, z=Z_NODE)
    elif kind == "fork":
        d._put(sid, "1", x, y, BAR_W, BAR_H, _FORK_STYLE, "", z=Z_NODE)
    elif kind == "history":
        d._put(sid, "1", x, y, CIRCLE_D, CIRCLE_D, _HISTORY_STYLE, "H", z=Z_NODE)
    else:
        d._put(sid, "1", x, y, NORMAL_W, NORMAL_H, _NORMAL_STYLE, label, z=Z_NODE)
    d.R[sid]["ob"] = True


_STATE_SIZE = {
    "initial": (CIRCLE_D, CIRCLE_D),
    "final": (CIRCLE_D, CIRCLE_D + 14),  # + label strip
    "choice": (DIAMOND_W, DIAMOND_H),
    "fork": (BAR_W, BAR_H),
    "history": (CIRCLE_D, CIRCLE_D),
    "normal": (NORMAL_W, NORMAL_H),
}


def build_state_machine_tree(spec: dict, *, flat: bool = False, plan: dict | None = None) -> tuple[Diagram, dict]:
    """Build a native state machine diagram from a state_machine render_spec
    (tools/analysis/state_machine_tools.py's projection of StateMachineSpec).
    Same (Diagram, root) contract as topology.build_tree."""
    states = [s for s in spec.get("states", []) if s.get("id")]
    transitions = [t for t in spec.get("transitions", []) if t.get("from") and t.get("to")]
    layer_of = _layer_states(states, transitions)

    layers: dict[int, list[dict]] = {}
    for s in states:
        layers.setdefault(layer_of.get(s["id"], 0), []).append(s)

    n_layers = max(layers.keys(), default=0) + 1
    page_w = 2 * MARGIN_X + n_layers * (NORMAL_W + LAYER_GAP_X)
    d = Diagram("state_machine", contract="bake", flat=flat, page=(round(page_w), 800))

    page_h = MARGIN_Y
    for layer_idx in sorted(layers):
        x = MARGIN_X + layer_idx * (NORMAL_W + LAYER_GAP_X)
        y = MARGIN_Y
        for s in layers[layer_idx]:
            _, h = _STATE_SIZE.get(s.get("kind") or "normal", _STATE_SIZE["normal"])
            _emit_state(d, s, x, y)
            y += h + STATE_GAP_Y
        page_h = max(page_h, y)
    d.page[0] = round(page_w)
    d.page[1] = round(page_h + MARGIN_Y)

    state_ids = {s["id"] for s in states}
    for t in transitions:
        src, tgt = t.get("from"), t.get("to")
        if src not in state_ids or tgt not in state_ids:
            continue
        event = t.get("event") or ""
        guard = t.get("guard") or ""
        action = t.get("action") or ""
        label = event
        if guard:
            label += f" [{guard}]"
        if action:
            label += f" / {action}"
        d.link(src, tgt, label)

    title = spec.get("title") or ""
    if title:
        d.text("__title", [0, 20], round(page_w), title, fs=14)
        d._cell_z[d._cell_index["__title"]] = Z_CHROME

    return d, {"kind": "state_machine", "states": [s["id"] for s in states]}


def state_machine_semantic_ids(spec: dict) -> tuple[list, list]:
    """(expected_ids, expected_edges) for check_semantic_preservation: every
    state id must survive, plus every declared (from, to) transition pair."""
    ids = [s["id"] for s in spec.get("states", []) if s.get("id")]
    edges = [
        (t.get("from"), t.get("to")) for t in spec.get("transitions", []) if t.get("from") and t.get("to")
    ]
    return ids, edges


def _register() -> None:
    from . import registry

    registry.register(
        registry.RendererEntry(
            kind="state_machine",
            backend="native",
            tree_builder=build_state_machine_tree,
            style_preset_label="state_machine",
            semantic_ids_fn=state_machine_semantic_ids,
            lint_kind="state_machine",
        )
    )


_register()


__all__ = ["build_state_machine_tree", "state_machine_semantic_ids"]
