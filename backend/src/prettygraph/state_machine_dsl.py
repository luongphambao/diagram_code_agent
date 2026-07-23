"""StateMachine — a small code-first DSL for authoring state machine diagrams.

Staged into the render sandbox as a flat top-level `prettygraph/*.py` module
(see `tools/stage_markers.py::_stage_helpers`), so a generated script does:

    from prettygraph.state_machine_dsl import StateMachine

    sm = StateMachine(title="Supplier order lifecycle")
    sm.initial("start")
    sm.state("pending", "Pending")
    sm.state("enriched", "Enriched")
    sm.state("supplier_accepted", "Supplier Accepted")
    sm.final("closed", "Closed")

    sm.transition("start", "pending", event="created")
    sm.transition("pending", "enriched", event="enrich_success", guard="data valid", actor="system")
    sm.transition(
        "enriched", "supplier_accepted", event="confirm_demo",
        guard="permission: demo.confirm", actor="supplier",
    )
    sm.transition("supplier_accepted", "closed", event="close", actor="admin")

    sm.render("out")

Deliberately ZERO dependencies beyond the stdlib — same reasoning as
`sequence_dsl.py`/`erd_dsl.py`. `.render()` just writes the accumulated spec
as JSON; validation, structural lint (unreachable states, dead ends, exitless
loops, ...), the transition-table CSV export, and the actual native
rendering all run server-side afterward — see `render_typed_diagram`
(`tools/rendering_tools.py`).
"""

from __future__ import annotations

import json


class StateMachine:
    """Accumulates states/transitions; `.render()` hands the result off to
    the server-side validator+renderer."""

    def __init__(self, title: str = "") -> None:
        self.title = title
        self._states: list[dict] = []
        self._transitions: list[dict] = []

    def state(self, id: str, label: str = "", *, kind: str = "normal", group: str = "") -> "StateMachine":
        self._states.append({"id": id, "label": label or id, "kind": kind, "group": group})
        return self

    def initial(self, id: str, label: str = "") -> "StateMachine":
        return self.state(id, label, kind="initial")

    def final(self, id: str, label: str = "") -> "StateMachine":
        return self.state(id, label, kind="final")

    def choice(self, id: str, label: str = "") -> "StateMachine":
        return self.state(id, label, kind="choice")

    def fork(self, id: str, label: str = "") -> "StateMachine":
        return self.state(id, label, kind="fork")

    def history(self, id: str, label: str = "") -> "StateMachine":
        return self.state(id, label, kind="history")

    def transition(
        self,
        from_: str,
        to: str,
        *,
        event: str = "",
        guard: str = "",
        action: str = "",
        actor: str = "",
    ) -> "StateMachine":
        self._transitions.append(
            {"from": from_, "to": to, "event": event, "guard": guard, "action": action, "actor": actor}
        )
        return self

    def render(self, name: str = "out") -> None:
        """Write the accumulated spec as `{name}.typed_spec.json`. Call this
        LAST, once — actual validation/lint/rendering (and the
        transition_table.csv export) happens server-side after this script
        finishes (see `render_typed_diagram`)."""
        spec = {
            "kind": "state_machine",
            "title": self.title,
            "states": self._states,
            "transitions": self._transitions,
        }
        with open(f"{name}.typed_spec.json", "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2)
        print(
            f"State machine spec captured: {len(self._states)} states, "
            f"{len(self._transitions)} transitions. Validation/lint/render happens "
            "server-side after this script returns."
        )


__all__ = ["StateMachine"]
