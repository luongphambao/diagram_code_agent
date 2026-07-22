"""DiagramBrief — requirements-derived diagram brief schema."""

from __future__ import annotations

from pydantic import Field

from .coercion import CoercingModel


class DiagramBrief(CoercingModel):
    """Requirements-derived diagram brief used before tech stack and blueprint."""

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
