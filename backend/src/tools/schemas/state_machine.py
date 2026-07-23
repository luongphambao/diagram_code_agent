"""State Machine Diagram — improvement plan MVP-3 phase 4.

Same reconciled shape as Sequence/ERD (phases 2-3): a validated Pydantic spec
is the canonical artifact; the LLM authors it code-first via
`prettygraph/state_machine_dsl.py` executed through `render_typed_diagram`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from .coercion import CoercingModel

StateKind = Literal["initial", "normal", "final", "choice", "fork", "history"]


class StateNode(CoercingModel):
    id: str = Field(description="unique snake_case id")
    label: str = Field(description="human-readable state name")
    kind: StateKind = Field("normal", description="initial|normal|final|choice|fork|history")
    group: str = Field("", description="optional composite-state group id this state nests inside")


class StateTransition(CoercingModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from", description="source state id")
    to: str = Field(description="target state id")
    event: str = Field("", description="event that triggers this transition")
    guard: str = Field("", description="condition that must hold, e.g. 'permission: demo.confirm'")
    action: str = Field("", description="side effect performed on this transition")
    actor: str = Field("", description="who/what causes this transition, e.g. admin|supplier|system")


class StateMachineSpec(CoercingModel):
    kind: Literal["state_machine"] = "state_machine"
    title: str = Field("", description="diagram title")
    states: list[StateNode] = Field(default_factory=list)
    transitions: list[StateTransition] = Field(default_factory=list)


__all__ = ["StateKind", "StateNode", "StateTransition", "StateMachineSpec"]
