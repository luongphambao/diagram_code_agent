"""Cross-artifact consistency validator — the "minimum viable CSM" gate.

The pipeline writes its artifacts to the workspace as separate JSON files
(`diagram_brief.json`, `blueprint.json`, `wbs.json`, ...). Each stage is good on
its own, but nothing checks that they still agree after a change request: a
requirement may go uncovered, a blueprint edge may dangle, a WBS may carry zero
effort, a deck may claim something the model never decided.

This module reads those existing files and reports contradictions as structured
`SolutionFinding`s, mirroring the diagram critic's `DiagramFinding` ladder in
`findings.py` (severity/confidence, a hard cap, a deterministic verdict). It owns
NO new data model — it is a read-only adapter over the artifacts that already
exist, so it can run as a release gate before any export without touching the
generation pipeline.

The two soft-match helpers are intentionally copied (not imported) from
`reporting._req_soft_match_report` / `_as_list` so this validator stays free of
the heavy reporting/render stack and remains trivially unit-testable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# --- severity / dimension ladder (mirrors findings.py) ----------------------

Severity = Literal["low", "medium", "high", "critical"]
Confidence = Literal["low", "medium", "high"]
Dimension = Literal[
    "traceability",   # an entity has no valid link to its source/target
    "consistency",    # two artifacts disagree (drift)
    "correctness",    # an internal reference is broken (dangling edge, bad cluster)
    "coverage",       # a requirement is not addressed by any component/task
    "completeness",   # an expected piece is missing (no decisions, no effort)
]

_SEVERITY_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# A finding at or above this severity blocks a client-facing export. Lower ones
# surface as warnings. (Promoted gradually — see validate_solution(block=...).)
BLOCKING_SEVERITY = "high"

# Keep the report glanceable. A wall of nits reads as noise.
MAX_FINDINGS = 12
MAX_TITLE_LENGTH = 120


class SolutionFinding(BaseModel):
    """One concrete cross-artifact contradiction, anchored to entity IDs."""

    severity: Severity
    confidence: Confidence = "high"
    dimension: Dimension
    artifact_type: str = Field(
        description="which artifact the defect lives in: blueprint|wbs|requirement|deck|report",
    )
    entity_ids: list[str] = Field(
        default_factory=list,
        description="stable IDs the finding touches, e.g. ['REQ-3', 'COMP-api_gateway']",
    )
    title: str = Field(description="names the defect in ~4-10 words")
    detail: str = Field(description="what disagrees and WHERE — name the entities")
    recommendation: Optional[str] = Field(default=None, description="the one concrete fix")
    requires_human_decision: bool = Field(
        default=False,
        description="True when resolving it is a trade-off (scope/cost/risk), not an auto-fix",
    )
    status: Literal["open", "waived", "resolved"] = "open"

    @field_validator("title")
    @classmethod
    def _clip_title(cls, v: str) -> str:
        compact = " ".join((v or "").split())
        if len(compact) > MAX_TITLE_LENGTH:
            return f"{compact[: MAX_TITLE_LENGTH - 3].rstrip()}..."
        return compact or "Solution finding"


# --- tiny helpers (copied from reporting.py to stay dependency-light) --------

def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _soft_match(text: str, candidates: list[str]) -> list[str]:
    """Substring match of a requirement against candidate names (case-insensitive).

    Mirrors reporting._req_soft_match_report so traceability and validation agree
    on what "covered" means.
    """
    norm = (text or "").lower().replace("-", " ").replace("_", " ")
    out: list[str] = []
    for name in candidates:
        terms = [t for t in name.lower().replace("/", " ").replace("-", " ").split() if len(t) > 3]
        if terms and any(t in norm for t in terms):
            out.append(name)
    return out


def _edge_endpoints(edge: dict[str, Any]) -> tuple[str, str]:
    return str(edge.get("from") or edge.get("from_") or ""), str(edge.get("to") or "")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


# --- the rules ---------------------------------------------------------------

def evaluate_solution(
    brief: dict[str, Any],
    blueprint: dict[str, Any],
    wbs: dict[str, Any],
) -> list[SolutionFinding]:
    """Run all cross-artifact rules over already-loaded artifact dicts.

    Pure function (no I/O) so it is trivially unit-testable. `validate_solution`
    is the workspace-reading wrapper around it.
    """
    findings: list[SolutionFinding] = []

    nodes = [n for n in _as_list(blueprint.get("nodes")) if isinstance(n, dict)]
    clusters = [c for c in _as_list(blueprint.get("clusters")) if isinstance(c, dict)]
    edges = [e for e in _as_list(blueprint.get("edges")) if isinstance(e, dict)]
    node_ids = {str(n.get("id")) for n in nodes if n.get("id")}
    cluster_ids = {str(c.get("id")) for c in clusters if c.get("id")}
    component_names = [str(n.get("label") or n.get("id") or "") for n in nodes]
    cluster_names = [str(c.get("label") or c.get("id") or "") for c in clusters]
    decisions = [str(d) for d in _as_list(blueprint.get("key_decisions"))]
    nfr_mechanisms = [
        str(m.get("mechanism") or "")
        for m in _as_list(blueprint.get("nfr_mapping"))
        if isinstance(m, dict)
    ]
    coverage_candidates = component_names + cluster_names + decisions + nfr_mechanisms

    # Rule 1 — dangling blueprint edges (correctness, high).
    for e in edges:
        src, dst = _edge_endpoints(e)
        missing = [p for p in (src, dst) if p and p not in node_ids]
        if missing:
            findings.append(SolutionFinding(
                severity="high", dimension="correctness", artifact_type="blueprint",
                entity_ids=[f"COMP-{m}" for m in missing],
                title="Edge references a missing component",
                detail=f"Edge {src or '?'}→{dst or '?'} points at node id(s) "
                       f"{missing} that are not in the blueprint's node list.",
                recommendation="Add the missing node or fix the edge endpoint id.",
            ))

    # Rule 2 — node assigned to a non-existent cluster (correctness, medium).
    for n in nodes:
        cl = str(n.get("cluster") or "")
        if cl and cluster_ids and cl not in cluster_ids:
            findings.append(SolutionFinding(
                severity="medium", dimension="correctness", artifact_type="blueprint",
                entity_ids=[f"COMP-{n.get('id')}", f"CLUSTER-{cl}"],
                title="Component points at a missing cluster",
                detail=f"Node '{n.get('id')}' has cluster='{cl}' which is not a "
                       f"declared cluster id.",
                recommendation="Add the cluster or reassign the node.",
            ))

    # Rule 3 — requirement with no addressing component/cluster/decision (coverage).
    reqs: list[tuple[str, str]] = []
    for kind, key in (("functional", "functional_requirements"),
                      ("non-functional", "non_functional_requirements")):
        for item in _as_list(brief.get(key))[:25]:
            reqs.append((kind, str(item)))
    for kind, text in reqs:
        if not text.strip():
            continue
        if not _soft_match(text, coverage_candidates):
            findings.append(SolutionFinding(
                severity="medium", dimension="coverage", artifact_type="requirement",
                entity_ids=[], requires_human_decision=True,
                title=f"Unmapped {kind} requirement",
                detail=f"Requirement \"{text[:90]}\" is not addressed by any blueprint "
                       f"component, cluster, decision or NFR mechanism.",
                recommendation="Map it to a component/work item, or explicitly defer it.",
            ))

    # Rule 4 — WBS leaf items that trace to nothing in brief or blueprint (traceability).
    wbs_items = [it for it in _as_list(wbs.get("items")) if isinstance(it, dict)]
    trace_targets = component_names + cluster_names + [t for _, t in reqs]
    for it in wbs_items:
        name = str(it.get("name") or it.get("deliverable") or "")
        if not name:
            continue
        if trace_targets and not _soft_match(name, trace_targets):
            ref = str(it.get("id") or it.get("ref_code") or it.get("code") or name[:24])
            findings.append(SolutionFinding(
                severity="low", confidence="medium", dimension="traceability",
                artifact_type="wbs", entity_ids=[f"WBS-{ref}"],
                title="WBS task traces to no requirement or component",
                detail=f"Task '{name}' does not soft-match any requirement or blueprint "
                       f"component; it may be internal-only work or scope creep.",
                recommendation="Link it to a REQ/COMP, or record a rationale for internal work.",
            ))

    # Rule 5 — WBS exists but carries zero effort (completeness, high).
    if wbs_items:
        total_md = ((wbs.get("effort_totals") or {}).get("total_mandays")) or 0
        try:
            total_md = float(total_md)
        except (TypeError, ValueError):
            total_md = 0.0
        if total_md <= 0:
            findings.append(SolutionFinding(
                severity="high", dimension="completeness", artifact_type="wbs",
                entity_ids=[], title="WBS has tasks but zero total effort",
                detail="effort_totals.total_mandays is 0 while items exist — the rollup "
                       "did not run or every task is unestimated.",
                recommendation="Run compute_wbs_rollup and ensure tasks carry man-days.",
            ))

    # Rule 6 — blueprint has components but no recorded decisions (completeness).
    if nodes and not decisions:
        findings.append(SolutionFinding(
            severity="medium", dimension="completeness", artifact_type="blueprint",
            entity_ids=[], title="Architecture has no recorded key decisions",
            detail="The approved blueprint lists components but no key_decisions, so the "
                   "deck/report can't answer \"why this?\".",
            recommendation="Add 3-6 explicit design decisions before client-facing export.",
        ))

    return findings


# --- verdict + rendering (mirrors findings.format_critique) ------------------

def _rank_key(f: SolutionFinding) -> tuple[int, int]:
    return (_SEVERITY_ORDER[f.severity], 1 if f.requires_human_decision else 0)


def is_blocking(f: SolutionFinding) -> bool:
    return _SEVERITY_ORDER[f.severity] >= _SEVERITY_ORDER[BLOCKING_SEVERITY]


def coverage_ratio(findings: list[SolutionFinding], total_requirements: int) -> float:
    """Traceability coverage = 1 - (unmapped requirements / total)."""
    if total_requirements <= 0:
        return 1.0
    unmapped = sum(1 for f in findings if f.dimension == "coverage")
    return round(max(0.0, 1.0 - unmapped / total_requirements), 3)


def format_validation(findings: list[SolutionFinding], *, block: bool = False) -> str:
    """Render a deterministic, machine-greppable summary.

    First line is `VALIDATION: PASS|WARN|BLOCK` so a gate can branch without JSON.
    """
    kept = sorted(findings, key=_rank_key, reverse=True)[:MAX_FINDINGS]
    blockers = [f for f in kept if is_blocking(f)]
    if not kept:
        return "VALIDATION: PASS (no cross-artifact contradictions found)"
    state = "BLOCK" if (block and blockers) else "WARN"
    header = (
        f"VALIDATION: {state} ({len(blockers)} blocking, {len(kept) - len(blockers)} advisory)"
    )
    lines = [header]
    for f in kept:
        flag = " [needs human decision]" if f.requires_human_decision else ""
        ids = f" {f.entity_ids}" if f.entity_ids else ""
        line = f"- [{f.severity}/{f.dimension}]{flag} {f.title}:{ids} {f.detail}"
        if f.recommendation:
            line += f" — fix: {f.recommendation}"
        lines.append(line)
    return "\n".join(lines)


def validate_solution(
    workspace: Optional[Path] = None,
    *,
    block: bool = False,
) -> tuple[list[SolutionFinding], str]:
    """Read the workspace artifacts and run all cross-artifact rules.

    Returns (findings, rendered_summary). `block=True` turns high-severity
    findings into a BLOCK verdict in the summary (use at the release gate once
    the rules have proven stable).
    """
    if workspace is None:
        from backends import WORKSPACE  # local import keeps this module importable standalone
        workspace = WORKSPACE
    workspace = Path(workspace)
    brief = _read_json(workspace / "diagram_brief.json", {}) or {}
    blueprint = _read_json(workspace / "blueprint.json", {}) or {}
    wbs = _read_json(workspace / "wbs.json", {}) or {}
    findings = evaluate_solution(brief, blueprint, wbs)
    return findings, format_validation(findings, block=block)
