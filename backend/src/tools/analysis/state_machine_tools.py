"""State Machine internals — structural lint, the Pydantic-model-to-
render_spec projection, and the transition-table export (improvement plan
MVP-3 phase 4, typed-diagram foundation).

Library functions, not an LLM-facing tool — the LLM authors a state machine
code-first (see `prettygraph/state_machine_dsl.py`), executed via
`tools/rendering_tools.py::render_typed_diagram`, which validates the
script's output against `StateMachineSpec` and then calls
`_build_state_machine_render_spec` + (via `_render_native_from_spec`'s
registry dispatch) `lint_state_machine` — same shape as sequence/erd, just
for states/transitions.
"""

from __future__ import annotations

import csv
import io

from domain.validation.diagram_lint import LintReport, register_linter
from ..schemas.state_machine import StateMachineSpec


def _build_state_machine_render_spec(spec: StateMachineSpec) -> dict:
    """Flatten a StateMachineSpec into the plain-dict render_spec
    `prettygraph.native.state_machine.build_state_machine_tree` consumes."""
    return {
        "kind": "state_machine",
        "title": spec.title,
        "states": [{"id": s.id, "label": s.label, "kind": s.kind, "group": s.group} for s in spec.states],
        "transitions": [
            {
                "from": t.from_,
                "to": t.to,
                "event": t.event,
                "guard": t.guard,
                "action": t.action,
                "actor": t.actor,
            }
            for t in spec.transitions
        ],
    }


def lint_state_machine(spec: dict) -> LintReport:
    """Structural lint for a state_machine render_spec — proposal §5's
    highest-value validation list: unreachable states, states that can never
    reach a final state, a final state with an outgoing transition, duplicate
    event+guard pairs on the same source, transitions missing an actor, and
    an exitless cycle."""
    report = LintReport()
    states = spec.get("states", [])
    sid_set = {s.get("id") for s in states if s.get("id")}
    for dup in sorted({s["id"] for s in states if [x.get("id") for x in states].count(s.get("id")) > 1}):
        report.error("duplicate_state", f"State id '{dup}' declared more than once.", dup)

    transitions = spec.get("transitions", [])
    graph: dict[str, set[str]] = {sid: set() for sid in sid_set}
    reverse: dict[str, set[str]] = {sid: set() for sid in sid_set}
    for t in transitions:
        src, tgt = t.get("from"), t.get("to")
        ref = f"{src}->{tgt}"
        if src not in sid_set:
            report.error("unknown_state", f"Transition {ref}: from '{src}' is not a declared state.", ref)
        if tgt not in sid_set:
            report.error("unknown_state", f"Transition {ref}: to '{tgt}' is not a declared state.", ref)
        if src in graph and tgt in graph:
            graph[src].add(tgt)
            reverse[tgt].add(src)
        if not (t.get("actor") or "").strip():
            report.warning("missing_actor", f"Transition {ref} (event={t.get('event') or ''!r}) has no actor.", ref)

    initial_ids = {s["id"] for s in states if s.get("kind") == "initial" and s.get("id")}
    final_ids = {s["id"] for s in states if s.get("kind") == "final" and s.get("id")}
    if not initial_ids:
        report.error("no_initial_state", "No state declared with kind='initial'.")
    if not final_ids:
        report.info("no_final_state", "No state declared with kind='final'.")

    if initial_ids:
        reached: set[str] = set()
        stack = list(initial_ids)
        while stack:
            node = stack.pop()
            if node in reached:
                continue
            reached.add(node)
            stack.extend(graph.get(node, ()) - reached)
        for sid in sid_set - reached:
            report.error("unreachable_state", f"State '{sid}' is not reachable from any initial state.", sid)

    if final_ids:
        can_reach_final: set[str] = set()
        stack = list(final_ids)
        while stack:
            node = stack.pop()
            if node in can_reach_final:
                continue
            can_reach_final.add(node)
            stack.extend(reverse.get(node, ()) - can_reach_final)
        for sid in sid_set - can_reach_final:
            report.warning("dead_end_state", f"State '{sid}' can never reach a final state.", sid)

    for s in states:
        sid = s.get("id")
        if s.get("kind") == "final" and graph.get(sid):
            report.error(
                "terminal_with_outgoing",
                f"Final state '{sid}' has an outgoing transition — a final state must have none.",
                sid,
            )

    seen_event_guard: dict[tuple, list[str]] = {}
    for t in transitions:
        key = (t.get("from"), t.get("event"), t.get("guard"))
        seen_event_guard.setdefault(key, []).append(t.get("to"))
    for (src, event, guard), targets in seen_event_guard.items():
        if len(targets) > 1:
            report.error(
                "ambiguous_transition",
                f"State '{src}': event={event!r} guard={guard!r} leads to {len(targets)} different states "
                f"({', '.join(targets)}) — ambiguous.",
                src,
            )

    # Exitless cycle: a strongly-connected component (size > 1, or a
    # single-node self-loop) with no edge leaving it to any other node.
    def _sccs() -> list[set[str]]:
        index_counter = [0]
        stack_s: list[str] = []
        lowlink: dict[str, int] = {}
        index: dict[str, int] = {}
        on_stack: dict[str, bool] = {}
        result: list[set[str]] = []

        def strongconnect(v: str) -> None:
            index[v] = index_counter[0]
            lowlink[v] = index_counter[0]
            index_counter[0] += 1
            stack_s.append(v)
            on_stack[v] = True
            for w in graph.get(v, ()):
                if w not in index:
                    strongconnect(w)
                    lowlink[v] = min(lowlink[v], lowlink[w])
                elif on_stack.get(w):
                    lowlink[v] = min(lowlink[v], index[w])
            if lowlink[v] == index[v]:
                comp = set()
                while True:
                    w = stack_s.pop()
                    on_stack[w] = False
                    comp.add(w)
                    if w == v:
                        break
                result.append(comp)

        for node in graph:
            if node not in index:
                strongconnect(node)
        return result

    for comp in _sccs():
        is_cycle = len(comp) > 1 or (len(comp) == 1 and next(iter(comp)) in graph.get(next(iter(comp)), ()))
        if not is_cycle:
            continue
        exits = any(dst not in comp for node in comp for dst in graph.get(node, ()))
        if not exits:
            report.warning("exitless_loop", f"States {sorted(comp)} form a cycle with no exit transition.")

    return report


def transition_table_csv(spec: dict) -> str:
    """Deterministic transition-table export (proposal §5's table) — CSV
    text, not LLM-authored: current_state, event, guard, actor, next_state."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["current_state", "event", "guard", "actor", "next_state"])
    labels = {s.get("id"): s.get("label") or s.get("id") for s in spec.get("states", [])}
    for t in spec.get("transitions", []):
        writer.writerow(
            [
                labels.get(t.get("from"), t.get("from")),
                t.get("event") or "",
                t.get("guard") or "",
                t.get("actor") or "",
                labels.get(t.get("to"), t.get("to")),
            ]
        )
    return buf.getvalue()


register_linter("state_machine", lint_state_machine)


__all__ = ["lint_state_machine", "_build_state_machine_render_spec", "transition_table_csv"]
