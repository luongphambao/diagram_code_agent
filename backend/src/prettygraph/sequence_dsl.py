"""Sequence — a small code-first DSL for authoring UML sequence diagrams.

Staged into the render sandbox as a flat top-level `prettygraph/*.py` module
(see `tools/stage_markers.py::_stage_helpers`), so a generated script does:

    from prettygraph.sequence_dsl import Sequence

    seq = Sequence(title="Magic Link Login")
    seq.actor("user", "User")
    seq.frontend("fe", "Frontend")
    seq.service("be", "Backend")
    seq.database("supa", "Supabase")

    seq.sync("user", "fe", "Login")
    seq.sync("fe", "be", "POST /login")
    with seq.activation("be"):
        seq.sync("be", "supa", "Create link")
        seq.ret("supa", "be", "link created")
        seq.ret("be", "fe", "session")
    seq.async_("fe", "user", "redirect dashboard")

    seq.render("out")

Message `order` is tracked automatically (each message call bumps an internal
counter) and fragment/activation `with` blocks record start/end order from
whichever messages run inside them — the LLM never hand-writes order numbers.

Deliberately ZERO dependencies beyond the stdlib: the sandbox only stages this
package's flat top-level files, not `prettygraph/native/` or anything under
`domain/`/`tools/` (those run the graphviz-era `Pretty` class only — the
native engine has never run standalone inside the render sandbox and pulls in
the drawio icon catalog + validators, which aren't staged there). So
`.render()` does NOT validate/lint/render anything itself — it just writes
the accumulated spec as plain JSON. The `render_typed_diagram` tool
(`tools/rendering_tools.py`, running server-side with full backend access)
reads that JSON back, validates it against `SequenceSpec`, runs
`lint_sequence`, and calls the native renderer — see that tool's docstring.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Iterator


class Sequence:
    """Accumulates participants/messages/fragments/activations; `.render()`
    hands the result off to the server-side validator+renderer."""

    def __init__(self, title: str = "") -> None:
        self.title = title
        self._participants: list[dict] = []
        self._messages: list[dict] = []
        self._fragments: list[dict] = []
        self._activations: list[dict] = []
        self._order = 0

    # ---- participants ---- #
    def participant(self, id: str, label: str = "", *, kind: str = "service") -> "Sequence":
        self._participants.append({"id": id, "label": label or id, "kind": kind})
        return self

    def actor(self, id: str, label: str = "") -> "Sequence":
        return self.participant(id, label, kind="actor")

    def frontend(self, id: str, label: str = "") -> "Sequence":
        return self.participant(id, label, kind="frontend")

    def service(self, id: str, label: str = "") -> "Sequence":
        return self.participant(id, label, kind="service")

    def database(self, id: str, label: str = "") -> "Sequence":
        return self.participant(id, label, kind="database")

    def external(self, id: str, label: str = "") -> "Sequence":
        return self.participant(id, label, kind="external")

    # ---- messages (order auto-increments — never pass it yourself) ---- #
    def _message(self, src: str, dst: str, label: str, kind: str) -> int:
        self._order += 1
        self._messages.append({"order": self._order, "from": src, "to": dst, "label": label, "kind": kind})
        return self._order

    def sync(self, src: str, dst: str, label: str = "") -> int:
        return self._message(src, dst, label, "sync")

    def async_(self, src: str, dst: str, label: str = "") -> int:
        return self._message(src, dst, label, "async")

    def ret(self, src: str, dst: str, label: str = "") -> int:
        """Return message — pass the SAME (src, dst) direction you're
        replying on, e.g. after `sync("fe","be",...)` call
        `ret("be","fe",...)`."""
        return self._message(src, dst, label, "return")

    def create(self, src: str, dst: str, label: str = "") -> int:
        return self._message(src, dst, label, "create")

    def destroy(self, src: str, dst: str, label: str = "") -> int:
        return self._message(src, dst, label, "destroy")

    # ---- fragments: wrap the messages they enclose in a `with` block ---- #
    @contextmanager
    def _fragment(self, kind: str, condition: str = "") -> Iterator["Sequence"]:
        start = self._order + 1
        frag = {"kind": kind, "condition": condition, "start_order": start, "end_order": start}
        self._fragments.append(frag)
        try:
            yield self
        finally:
            frag["end_order"] = max(self._order, frag["start_order"])

    def alt(self, condition: str = ""):
        return self._fragment("alt", condition)

    def opt(self, condition: str = ""):
        return self._fragment("opt", condition)

    def loop(self, condition: str = ""):
        return self._fragment("loop", condition)

    def par(self, condition: str = ""):
        return self._fragment("par", condition)

    def critical(self, condition: str = ""):
        return self._fragment("critical", condition)

    # ---- activation bars: wrap the messages they enclose in a `with` block ---- #
    @contextmanager
    def activation(self, participant: str) -> Iterator["Sequence"]:
        start = self._order + 1
        act = {"participant": participant, "start_order": start, "end_order": start}
        self._activations.append(act)
        try:
            yield self
        finally:
            act["end_order"] = max(self._order, act["start_order"])

    # ---- capture ---- #
    def render(self, name: str = "out") -> None:
        """Write the accumulated spec as `{name}.typed_spec.json`. Call this
        LAST, once — actual validation/lint/rendering happens server-side
        after this script finishes (see `render_typed_diagram`)."""
        spec = {
            "kind": "sequence",
            "title": self.title,
            "participants": self._participants,
            "messages": self._messages,
            "fragments": self._fragments,
            "activations": self._activations,
        }
        with open(f"{name}.typed_spec.json", "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2)
        print(
            f"Sequence spec captured: {len(self._participants)} participants, "
            f"{len(self._messages)} messages, {len(self._fragments)} fragments, "
            f"{len(self._activations)} activations. Validation/lint/render happens "
            "server-side after this script returns."
        )


__all__ = ["Sequence"]
