"""Pydantic schemas for the analysis/HITL tools — split out of the former
``tools/analysis_tools.py`` monolith. Re-exports the full public surface so
callers can do ``from tools.schemas import Blueprint`` (or import a specific
submodule directly).
"""

from __future__ import annotations

from .coercion import CoercingModel, _mimo_coerce_before, _wants_structural
from .brief import DiagramBrief
from .tech_stack import (
    CostRange,
    DataAssumptions,
    ProposeTechStackArgs,
    ScalingPhase,
    SolutionAssumptions,
    TeamAssumptions,
    TechAlternative,
    TechChoice,
    TechCriteria,
    TechRisk,
    UserScaleAssumptions,
)
from .blueprint import (
    BPCluster,
    BPEdge,
    BPNode,
    Blueprint,
    LegendEntry,
    NFRMapping,
    PillarCoverage,
    WAFPillar,
)

__all__ = [
    "CoercingModel",
    "_mimo_coerce_before",
    "_wants_structural",
    "DiagramBrief",
    "CostRange",
    "DataAssumptions",
    "ProposeTechStackArgs",
    "ScalingPhase",
    "SolutionAssumptions",
    "TeamAssumptions",
    "TechAlternative",
    "TechChoice",
    "TechCriteria",
    "TechRisk",
    "UserScaleAssumptions",
    "BPCluster",
    "BPEdge",
    "BPNode",
    "Blueprint",
    "LegendEntry",
    "NFRMapping",
    "PillarCoverage",
    "WAFPillar",
]
