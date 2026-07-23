"""DiagramBrief — requirements-derived diagram brief schema."""

from __future__ import annotations

from pydantic import Field

from .coercion import CoercingModel
from .diagram_spec import DiagramKind


class DiagramBrief(CoercingModel):
    """Requirements-derived diagram brief used before tech stack and blueprint."""

    diagram_kind: DiagramKind = Field(
        "architecture",
        description=(
            "Which diagram family this request needs — architecture (default) | bpmn "
            "(business process/workflow) | sequence (runtime interaction walkthrough — "
            "lifelines, messages, alt/opt/loop) | erd (database schema) | state_machine "
            "(status/lifecycle transitions) | c4 (formal C4 notation). Set this from the "
            "requirement's own shape, not from what's easiest to draw: 'user logs in via "
            "magic link, FE calls BE calls Supabase' -> sequence; 'CREATE TABLE ...' or "
            "'design the schema' -> erd; 'order goes pending -> paid -> shipped' -> "
            "state_machine. A diagram_kind_override.json in the workspace (set by an "
            "explicit frontend type selection) always takes precedence over this field — "
            "check for one before defaulting to architecture."
        ),
    )
    objective: str = Field(description="one concise sentence describing what the diagram must communicate")
    application_type: str = Field(
        "",
        description="application type from architecture analysis, e.g. web_application|api_service|data_analytics",
    )
    scale_level: str = Field(
        "", description="scale signal from architecture analysis: small|medium|large|enterprise"
    )
    security_level: str = Field(
        "", description="security signal from architecture analysis: basic|standard|high|critical"
    )
    provider_preference: str = Field("", description="cloud/provider signal, e.g. aws|azure|gcp|oci|onprem")
    analysis_signals: list[str] = Field(
        default_factory=list,
        description="short copied signals from architecture_analysis.json: capabilities, constraints, selected pattern hints",
    )
    stakeholders: list[str] = Field(
        default_factory=list,
        description="intended readers/reviewers, e.g. cloud/devops, security, developers, management",
    )
    functional_requirements: list[str] = Field(
        default_factory=list,
        description="architecture capabilities that must appear or be represented in the diagram",
    )
    non_functional_requirements: list[str] = Field(
        default_factory=list,
        description="quality constraints such as scalability, availability, security, governance, maintainability",
    )
    layout_constraints: list[str] = Field(
        default_factory=list,
        description="visual/layout constraints and simplification choices for the diagram",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="explicit assumptions made when the prompt/docs do not fully specify details",
    )
