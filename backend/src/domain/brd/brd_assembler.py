"""brd_assembler — gather workspace context for BRD content authoring
(docs/plans/2026-07-29-brd-agent.md §E1).

Deliberately reuses assemble_report_data() + _enrich_report_from_csm() — the
SAME context the PDF report and PPTX proposal already build from — instead of
giving BRD content a second, divergent way of reading the same artifacts. This
does import a private helper from domain.reporting.ppt_reporting; that's the
plan's explicit design choice (docs/plans/2026-07-29-brd-agent.md §E1), not an
accident — there is no public equivalent, and duplicating its CSM-backfill
logic here would be the real drift risk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from domain.reporting.ppt_reporting import _enrich_report_from_csm
from domain.reporting.reporting import assemble_report_data

# The company BRD template's real top-level sections (see BRD/01. BRD_Template_2.docx).
# Kept here — not derived from the template at import time — because
# inspect_brd_template() is what actually reads the live template; this list is
# only used to resolve short aliases a model might type.
DEFAULT_BRD_SECTIONS = [
    "purpose",
    "intended-audience",
    "intended-use",
    "scope",
    "abbreviations-and-acronyms",
    "document-conventions",
    "user-needs",
    "assumptions-and-dependencies",
    "functional-requirements-list",
    "external-interface-requirements",
    "system-features",
    "non-functional-requirements",
    "analysis-models",
    "issues-list",
]

SECTION_ALIASES = {
    "intro": "purpose",
    "requirements": "functional-requirements-list",
    "nfr": "non-functional-requirements",
    "interfaces": "external-interface-requirements",
}


def normalize_brd_sections(sections: Optional[list[str]]) -> tuple[list[str], list[str]]:
    """(resolved, unrecognized) — mirrors reporting.normalize_sections()'s contract."""
    if not sections:
        return list(DEFAULT_BRD_SECTIONS), []
    resolved: list[str] = []
    unrecognized: list[str] = []
    for s in sections:
        key = SECTION_ALIASES.get(s, s)
        if key in DEFAULT_BRD_SECTIONS:
            resolved.append(key)
        else:
            unrecognized.append(s)
    seen: set[str] = set()
    deduped = [s for s in resolved if not (s in seen or seen.add(s))]
    return (deduped or list(DEFAULT_BRD_SECTIONS)), unrecognized


_EMPTY_REPORT_FALLBACK: dict[str, Any] = {
    "analysis": {},
    "brief": {},
    "tech_items": [],
    "tech_assumptions": None,
    "tech_scaling_roadmap": [],
    "blueprint": {},
    "components_by_cluster": {},
    "traceability": [],
    "coverage_pct": 0,
    "coverage_summary": "No requirements",
    "well_architected": [],
    "risks": [],
    "executive_points": [],
    "business_value": "",
    "technical_value": "",
    "evidence_steps": [],
    "artifacts": {},
    "fallback_sources": [],
    "node_count": 0,
    "edge_count": 0,
    "cluster_count": 0,
}


def assemble_brd_context(
    workspace: Path, *, title: str = "", subtitle: str = "", brand: str = ""
) -> dict[str, Any]:
    """Best-effort: unlike the PDF report, a BRD can legitimately be authored
    before any diagram exists (e.g. importing a client's own .docx to edit) —
    assemble_report_data() raises FileNotFoundError without out.png/out.body.png,
    so that case falls back to an empty-but-well-shaped report dict instead of
    blocking BRD authoring entirely."""
    try:
        report = assemble_report_data(workspace, title=title, subtitle=subtitle, brand=brand)
    except FileNotFoundError:
        report = {
            "title": title or "BRD",
            "subtitle": subtitle,
            "brand": brand,
            "document_type": "Business Requirements Document",
            **_EMPTY_REPORT_FALLBACK,
        }
    _enrich_report_from_csm(report, workspace)
    return report
