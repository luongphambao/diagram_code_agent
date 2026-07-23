"""DiagramSpec — the discriminated union that stops new diagram families from
growing the `Blueprint` god object (improvement plan: typed-diagram foundation).

`Blueprint` already carries architecture nodes/clusters/edges *and* an optional
`process: ProcessBlueprint` field that reroutes rendering to the native BPMN
builder — the exact anti-pattern this module ends. Every NEW diagram family
(sequence, erd, state_machine, c4, ...) gets its own top-level member here
instead of another optional field bolted onto Blueprint.

This union is additive: `Blueprint`/`ProcessBlueprint` and the existing
`propose_blueprint(blueprint: Blueprint)` gate tool are UNCHANGED and keep
working exactly as before. `ArchitectureSpec`/`ProcessSpec` are thin adapters
(kind-tagged subclasses) so the full diagram type space is representable in
one place without disturbing the legacy call sites.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field

from .blueprint import Blueprint
from .coercion import CoercingModel
from .process import ProcessBlueprint
from .sequence import SequenceSpec

# The full diagram type space. New members are added here as each phase lands
# its schema (sequence: MVP-3 phase 2, erd: phase 3, state_machine: phase 4);
# deployment/code_map stay unimplemented placeholders per the proposal's
# "not yet prioritized" list until their own phase.
DiagramKind = Literal[
    "architecture",
    "bpmn",
    "sequence",
    "erd",
    "state_machine",
    "c4",
    "deployment",
    "code_map",
]


class ArchitectureSpec(Blueprint):
    """`Blueprint` tagged with the union discriminator. Identical fields/behavior —
    existing callers that construct a plain `Blueprint` are unaffected; this
    subclass exists only so `DiagramSpec` can discriminate on `kind`."""

    kind: Literal["architecture"] = "architecture"


class ProcessSpec(ProcessBlueprint):
    """`ProcessBlueprint` tagged with the union discriminator (BPMN swimlane
    process). Mirrors how `Blueprint.process` already reroutes to the native
    BPMN builder — this is the same data, addressable as its own top-level kind."""

    kind: Literal["bpmn"] = "bpmn"


# Extended by later phases: ERDSpec, StateMachineSpec, ... join this union as
# their own schemas land (MVP-3 phases 3-4).
DiagramSpec = Annotated[
    Union[ArchitectureSpec, ProcessSpec, SequenceSpec], Field(discriminator="kind")
]


class DiagramPlan(CoercingModel):
    """Top-level typed-diagram envelope (improvement plan §8's `DiagramPlan`).

    Not a required call shape for existing tools — `propose_blueprint` keeps
    taking a bare `Blueprint`. New per-kind gate tools (`propose_sequence`,
    `propose_erd`, `propose_state_machine`, ...) use this envelope so every
    typed diagram carries the same title/objective/audience metadata alongside
    its kind-specific `spec`.
    """

    kind: DiagramKind = Field("architecture", description="which diagram family this is")
    title: str = Field("", description="short diagram title")
    objective: str = Field("", description="one sentence: what this diagram must communicate")
    audience: str = Field("", description="intended readers, e.g. BA, backend, QA, DBA, architect")
    source_type: str = Field(
        "", description="requirement|sql_ddl|orm_model|openapi|repo_code|iac — what the spec was derived from"
    )
    presentation_style: str = Field("diagram", description="slide|diagram")
    spec: DiagramSpec


__all__ = [
    "DiagramKind",
    "ArchitectureSpec",
    "ProcessSpec",
    "DiagramSpec",
    "DiagramPlan",
]
