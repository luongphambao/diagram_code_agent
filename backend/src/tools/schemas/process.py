"""BPMN swimlane process schema — the declarative input to the native BPMN
builder (prettygraph/native/bpmn.py + topology.py's process branch).
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from .coercion import CoercingModel

# Matches prettygraph.native.bpmn's stencil-suffix vocabulary.
_EVENT_TYPES = {
    "start": ("none", "message", "timer"),
    "intermediate": ("message", "timer", "link"),
    "end": ("none", "terminate", "error", "cancel"),
}
_GATEWAY_TYPES = ("exclusive", "parallel", "inclusive", "event")


class ProcessStep(CoercingModel):
    id: str = Field(description="unique snake_case id")
    kind: Literal[
        "start",
        "intermediate",
        "end",
        "gateway",
        "task",
        "user_task",
        "service_task",
        "manual_task",
        "script_task",
        "business_rule_task",
        "sub_process",
    ] = Field(description="BPMN flow-object kind — maps 1:1 to a prettygraph.native.bpmn creator")
    type: str = Field(
        "",
        description=(
            "subtype for start/intermediate/end/gateway kinds: "
            "start: none|message|timer; intermediate: message|timer|link; "
            "end: none|terminate|error|cancel; gateway: exclusive|parallel|inclusive|event. "
            "Ignored for task/sub_process kinds."
        ),
    )
    lane: int = Field(0, description="0-based row index into ProcessBlueprint.lanes")
    col: int = Field(0, description="0-based column index (phase order)")
    label: str = Field("", description="label rendered on/under the shape")


class ProcessFlow(CoercingModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from", description="source step id")
    to: str = Field(description="target step id")
    label: str = Field("", description="flow label, e.g. a condition or message name")
    kind: Literal["sequence", "message"] = Field(
        "sequence",
        description="sequence (solid, within-pool control flow) or "
        "message (dashed, cross-pool/cross-lane communication)",
    )


class ProcessBlueprint(CoercingModel):
    """A BPMN 2.0 Tier-1 swimlane process: pool -> lanes (rows) x phases (columns)."""

    label: str = Field("", description="pool title")
    lanes: list[str] = Field(default_factory=list, description="lane (role/swimlane) labels, top to bottom")
    phases: list[str] = Field(default_factory=list, description="optional milestone/phase column headers")
    steps: list[ProcessStep] = Field(default_factory=list)
    flows: list[ProcessFlow] = Field(default_factory=list)
