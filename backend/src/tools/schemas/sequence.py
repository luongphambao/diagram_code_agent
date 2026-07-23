"""True UML Sequence Diagram schema — improvement plan MVP-3 phase 2, the pilot
that proves the typed-diagram foundation (registry.py, diagram_lint.py) on the
hardest native geometry (lifelines, activation bars, ordered fragments).

Distinct from the existing `layout_intent="sequence"` topology preset
(`prettygraph/native/diagram_types.py`), which is a numbered request
walkthrough drawn OVER an architecture diagram's boxes — this is a real UML
lifeline diagram with its own renderer (`prettygraph/native/sequence.py`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from .coercion import CoercingModel

ParticipantKind = Literal["actor", "frontend", "service", "database", "external"]
MessageKind = Literal["sync", "async", "return", "create", "destroy"]
FragmentKind = Literal["alt", "opt", "loop", "par", "critical"]


class SequenceParticipant(CoercingModel):
    id: str = Field(description="unique snake_case id")
    label: str = Field(description="human-readable participant name")
    kind: ParticipantKind = Field("service", description="actor|frontend|service|database|external")


class SequenceMessage(CoercingModel):
    model_config = ConfigDict(populate_by_name=True)
    order: int = Field(description="1-based position in the walkthrough — must be unique")
    from_: str = Field(alias="from", description="source participant id")
    to: str = Field(description="target participant id")
    label: str = Field("", description="method/operation/event name shown on the arrow")
    kind: MessageKind = Field(
        "sync",
        description=(
            "sync (solid line, filled arrowhead) | async (solid line, open arrowhead) | "
            "return (dashed line — MUST pair with an earlier sync/async request between "
            "the same two participants) | create (spawns a new lifeline starting here) | "
            "destroy (ends the target lifeline with an X)"
        ),
    )

    @property
    def endpoints(self) -> tuple[str, str]:
        return self.from_, self.to


class SequenceFragment(CoercingModel):
    kind: FragmentKind = Field(description="alt|opt|loop|par|critical")
    condition: str = Field("", description="guard/label shown in the fragment's tab, e.g. 'stock available'")
    start_order: int = Field(description="message.order of the first message this fragment encloses")
    end_order: int = Field(description="message.order of the last message this fragment encloses")


class SequenceActivation(CoercingModel):
    participant: str = Field(description="participant id this activation bar sits on")
    start_order: int = Field(description="message.order that starts this activation")
    end_order: int = Field(description="message.order that ends this activation")


class SequenceSpec(CoercingModel):
    """A structured UML sequence diagram: participants + ordered messages,
    plus optional fragments (alt/opt/loop/par/critical) and activation bars."""

    kind: Literal["sequence"] = "sequence"
    title: str = Field("", description="diagram title")
    participants: list[SequenceParticipant] = Field(default_factory=list)
    messages: list[SequenceMessage] = Field(default_factory=list)
    fragments: list[SequenceFragment] = Field(default_factory=list)
    activations: list[SequenceActivation] = Field(default_factory=list)


__all__ = [
    "ParticipantKind",
    "MessageKind",
    "FragmentKind",
    "SequenceParticipant",
    "SequenceMessage",
    "SequenceFragment",
    "SequenceActivation",
    "SequenceSpec",
]
