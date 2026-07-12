"""analyze_architecture_requirements — deterministic planning-signal extraction."""

from __future__ import annotations

import json

from langchain_core.tools import tool

from architecture_advisor import analyze_requirements
from backends import current_workspace
from reporting import record_report_step
from ..constants import _ARCH_ANALYSIS_FILE


@tool(parse_docstring=True)
def analyze_architecture_requirements(requirements: str, provider_preference: str = "") -> str:
    """Analyze architecture requirements into deterministic planning signals.

    Writes `architecture_analysis.json` so the brief, tech stack, blueprint, and
    critic stay aligned on pattern, scale, security, provider, and scope signals.
    This is NOT a human-approval gate.

    When to use: once, after reading the user prompt and attached requirement docs,
    before `propose_diagram_brief`.

    Args:
        requirements: The combined requirement text (user prompt plus extracted
            content from any uploaded requirement documents).
        provider_preference: Optional cloud preference to bias detection, e.g.
            "aws", "azure", "gcp"; empty means cloud-neutral.
    """
    analysis = analyze_requirements(requirements, provider_preference)
    current_workspace().mkdir(parents=True, exist_ok=True)
    _ARCH_ANALYSIS_FILE.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    record_report_step(
        current_workspace(),
        "analyze_architecture_requirements",
        summary=(
            f"Detected {analysis.get('application_type', 'application')} workload, "
            f"{analysis.get('scale_level', 'unspecified')} scale, "
            f"{analysis.get('security_level', 'unspecified')} security, "
            f"provider={analysis.get('provider_preference') or 'cloud-neutral'}."
        ),
        data=analysis,
    )
    return json.dumps(analysis, indent=2)
