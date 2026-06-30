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

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# --- severity / dimension ladder (mirrors findings.py) ----------------------

Severity = Literal["low", "medium", "high", "critical"]
Confidence = Literal["low", "medium", "high"]
Dimension = Literal[
    "traceability",      # an entity has no valid link to its source/target
    "consistency",       # two artifacts disagree (drift)
    "correctness",       # an internal reference is broken (dangling edge, bad cluster)
    "coverage",          # a requirement is not addressed by any component/task
    "completeness",      # an expected piece is missing (no decisions, no effort)
    "security",          # public flow no auth boundary; PII flow unprotected (§4.3)
    "reliability",       # async flow without retry/DLQ/idempotency
    "feasibility",       # schedule not deliverable under resource capacity (§4.4)
    "compliance",        # a required control (from a compliance pack) is missing/ungrounded (§4 P2)
    "diagram_structural",  # drawio error: dangling edge, duplicate id, broken geometry, wrong stencil
    "diagram_layout",      # drawio warning: node overlap, negative coords, missing aspect=fixed
    "diagram_style",       # drawio advice: font sizes, palette, AWS hierarchy, edge routing
]
# How a finding gets resolved (docx §4.3 repair contract). `patch_*` and
# `auto_repair` can be fixed mechanically (an agent/tool owns the fix);
# `human_decision`/`request_evidence` are trade-offs a person must settle;
# `none` is informational only.
RepairStrategy = Literal[
    "auto_repair",
    "patch_blueprint",
    "patch_wbs",
    "patch_deck",
    "request_evidence",
    "human_decision",
    "none",
]
# repair_strategy values an agent/tool can fix without a human trade-off.
AUTO_REPAIR_STRATEGIES: frozenset[str] = frozenset(
    {"auto_repair", "patch_blueprint", "patch_wbs", "patch_deck"}
)

_SEVERITY_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# A finding at or above this severity blocks a client-facing export. Lower ones
# surface as warnings. (Promoted gradually — see validate_solution(block=...).)
BLOCKING_SEVERITY = "high"

# Keep the report glanceable. A wall of nits reads as noise.
MAX_FINDINGS = 12
MAX_TITLE_LENGTH = 120


class SolutionFinding(BaseModel):
    """One concrete cross-artifact contradiction, anchored to entity IDs."""

    finding_id: str = Field(
        default="",
        description="stable id for this defect, computed from (dimension, entity_ids, title) "
        "so the SAME defect keeps the SAME id across validation runs (see finding_store).",
    )
    repair_strategy: RepairStrategy = Field(
        default="none",
        description="how this finding is fixed: patch_blueprint|patch_wbs|patch_deck|auto_repair "
        "(mechanical), request_evidence|human_decision (a person must settle), or none.",
    )
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

    @model_validator(mode="after")
    def _ensure_finding_id(self) -> "SolutionFinding":
        # Fill a stable id from the defect's identity (not its run) so re-validating
        # the same artifacts yields the same id — the key to tracking waive/resolve.
        if not self.finding_id:
            self.finding_id = stable_finding_id(self.dimension, self.entity_ids, self.title)
        return self


def stable_finding_id(dimension: str, entity_ids: list[str], title: str) -> str:
    """A short, deterministic id for a defect, keyed by what it IS, not when it was found.

    Same (dimension, entity set, title) → same id across runs, so `finding_store` can
    carry a `waived`/`resolved` status forward instead of re-raising the defect each run.
    """
    basis = "|".join([
        dimension,
        ",".join(sorted(str(e) for e in (entity_ids or []))),
        " ".join((title or "").split()),
    ])
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:10]
    return f"SF-{digest}"


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


def _corpus(blueprint: dict[str, Any]) -> str:
    """All lowercased human-readable text in the blueprint for semantic substring matching."""
    parts: list[str] = []
    for d in _as_list(blueprint.get("key_decisions")):
        parts.append(str(d).lower())
    for m in _as_list(blueprint.get("nfr_mapping")):
        if isinstance(m, dict):
            parts.append(str(m.get("mechanism") or "").lower())
    for n in _as_list(blueprint.get("nodes")):
        if isinstance(n, dict):
            parts.append(str(n.get("label") or "").lower())
            parts.append(str(n.get("tech") or "").lower())
            parts.append(str(n.get("type") or "").lower())
    for c in _as_list(blueprint.get("clusters")):
        if isinstance(c, dict):
            parts.append(str(c.get("label") or "").lower())
    return " ".join(parts)


def _nfr_text(brief: dict[str, Any]) -> str:
    """Lowercased NFR + constraints text from the brief."""
    parts: list[str] = []
    for r in _as_list(brief.get("non_functional_requirements")):
        parts.append(str(r).lower())
    for c in _as_list(brief.get("constraints")):
        parts.append(str(c).lower())
    return " ".join(parts)


def _has(text: str, keywords: list[str]) -> bool:
    """True if any keyword appears as a substring in text."""
    return any(kw in text for kw in keywords)


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
    *,
    model: Any = None,
) -> list[SolutionFinding]:
    """Run all cross-artifact rules over already-loaded artifact dicts.

    Pure function (no I/O) so it is trivially unit-testable. `validate_solution`
    is the workspace-reading wrapper around it.

    `model` is an optional `SolutionModel`: when given, the SEMANTIC rules (unmapped
    requirement, orphan WBS) anchor their findings to the CSM's STABLE ids instead of
    leaving `entity_ids` empty. `model=None` reproduces the original behavior exactly,
    so positional callers (and the structural rules, which need the blueprint edge
    graph the CSM doesn't store) are unaffected.
    """
    # CSM lookups for stable-id anchoring (empty when model is absent).
    req_id_by_text: dict[str, str] = (
        {r.statement: r.id for r in model.requirements} if model else {}
    )
    wbs_id_by_name: dict[str, str] = (
        {w.name: w.id for w in model.work_items} if model else {}
    )

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
                repair_strategy="patch_blueprint",
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
                repair_strategy="patch_blueprint",
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
            rid = req_id_by_text.get(text) or req_id_by_text.get(text.strip())
            findings.append(SolutionFinding(
                severity="medium", dimension="coverage", artifact_type="requirement",
                repair_strategy="human_decision",
                entity_ids=[rid] if rid else [], requires_human_decision=True,
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
            wid = wbs_id_by_name.get(name) or f"WBS-{ref}"
            findings.append(SolutionFinding(
                severity="low", confidence="medium", dimension="traceability",
                artifact_type="wbs", repair_strategy="human_decision", entity_ids=[wid],
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
                repair_strategy="patch_wbs",
                entity_ids=[], title="WBS has tasks but zero total effort",
                detail="effort_totals.total_mandays is 0 while items exist — the rollup "
                       "did not run or every task is unestimated.",
                recommendation="Run compute_wbs_rollup and ensure tasks carry man-days.",
            ))

    # Rule 6 — blueprint has components but no recorded decisions (completeness).
    if nodes and not decisions:
        findings.append(SolutionFinding(
            severity="medium", dimension="completeness", artifact_type="blueprint",
            repair_strategy="human_decision",
            entity_ids=[], title="Architecture has no recorded key decisions",
            detail="The approved blueprint lists components but no key_decisions, so the "
                   "deck/report can't answer \"why this?\".",
            recommendation="Add 3-6 explicit design decisions before client-facing export.",
        ))

    # --- Semantic lint (§4.7): architecture smell rules ----------------------
    # All three rules gate on an activation condition to minimise false positives.
    # severity=medium < BLOCKING_SEVERITY → advisory by default (won't hard-block export)
    # except where noted. repair_strategy=human_decision → not in AUTO_REPAIR_STRATEGIES.

    corpus = _corpus(blueprint)
    nfr_txt = _nfr_text(brief)

    # Rule 7 — Public ingress flow with no auth boundary (security, medium).
    # Activation: ingress node exists AND has outbound edge AND NFR requires auth/security.
    _PUBLIC_KW = ["internet", "user", "client", "cdn", "waf", "api gateway",
                  "load balancer", "external"]
    _AUTH_KW = ["auth", "oauth", "oidc", "jwt", "identity", "cognito", "iam",
                "api key", "token", "sso", "waf", "keycloak", "authz", "authn"]
    _SECURITY_NFR_KW = ["security", "auth", "access-control", "access control", "identity"]

    public_nodes = [n for n in nodes
                    if _has((n.get("label") or n.get("type") or "").lower(), _PUBLIC_KW)]
    if public_nodes:
        public_ids = {str(n.get("id")) for n in public_nodes}
        has_edge_from_public = any(_edge_endpoints(e)[0] in public_ids for e in edges)
        if has_edge_from_public and _has(nfr_txt, _SECURITY_NFR_KW):
            if not _has(corpus, _AUTH_KW):
                pub_comp_ids = [f"COMP-{n.get('id')}" for n in public_nodes[:3]]
                findings.append(SolutionFinding(
                    severity="medium", confidence="medium", dimension="security",
                    artifact_type="blueprint", repair_strategy="human_decision",
                    entity_ids=pub_comp_ids, requires_human_decision=True,
                    title="Public-facing flow has no auth boundary",
                    detail=(f"Blueprint has {len(public_nodes)} public ingress node(s) with "
                            f"outbound edges and NFR requires auth/security, but no auth "
                            f"mechanism (oauth/jwt/iam/etc.) found in decisions or NFR mapping."),
                    recommendation="Add an auth boundary (JWT validator, IAM policy, API Gateway "
                                   "auth) or record the mechanism in key_decisions.",
                ))

    # Rule 8 — PII/privacy flow with no data-protection mechanism (security).
    # Activation: brief/constraints mention PII or privacy regulation.
    # severity=high when a compliance/residency constraint is present, else medium.
    _PII_KW = ["pii", "personal data", "gdpr", "ccpa", "hipaa", "pci", "residency",
               "customer data", "sensitive", "data protection"]
    _COMPLIANCE_KW = ["compliance", "residency", "gdpr", "ccpa", "hipaa", "pci"]
    _PROTECTION_KW = ["encrypt", "kms", "tls", "at rest", "in transit", "classification",
                      "retention", "masking", "tokeniz", "anonymiz", "vault"]

    if _has(nfr_txt, _PII_KW):
        if not _has(corpus, _PROTECTION_KW):
            sev: Severity = "high" if _has(nfr_txt, _COMPLIANCE_KW) else "medium"
            findings.append(SolutionFinding(
                severity=sev, confidence="medium", dimension="security",
                artifact_type="blueprint", repair_strategy="human_decision",
                entity_ids=[], requires_human_decision=True,
                title="PII flow has no data-protection mechanism",
                detail=("Brief/constraints reference PII or privacy regulation but blueprint "
                        "has no encryption, KMS, TLS, masking, or retention policy in "
                        "decisions or NFR mapping."),
                recommendation=("Add data-at-rest encryption, TLS in-transit, "
                                "masking/tokenisation, or an explicit retention policy to "
                                "key_decisions or nfr_mapping."),
            ))

    # Rule 9 — Async messaging node with no retry/DLQ/idempotency (reliability, medium).
    # Activation: any node whose label/type/tech suggests a message broker, or an AMQP edge.
    _ASYNC_KW = ["queue", "kafka", "sqs", "rabbitmq", "pubsub", "topic", "broker",
                 "event bus", "kinesis", "eventbridge", "sns", "nats"]
    _RESILIENCE_KW = ["retry", "dlq", "dead letter", "idempoten", "backoff",
                      "redrive", "outbox", "at least once"]

    async_nodes = [n for n in nodes
                   if _has((n.get("label") or n.get("type") or n.get("tech") or "").lower(),
                           _ASYNC_KW)]
    has_amqp_edge = any(str(e.get("protocol") or "").upper() == "AMQP" for e in edges)
    if async_nodes or has_amqp_edge:
        if not _has(corpus, _RESILIENCE_KW):
            async_ids = [f"COMP-{n.get('id')}" for n in async_nodes[:3]]
            amqp_note = " and AMQP edge(s)" if has_amqp_edge else ""
            findings.append(SolutionFinding(
                severity="medium", confidence="medium", dimension="reliability",
                artifact_type="blueprint", repair_strategy="human_decision",
                entity_ids=async_ids, requires_human_decision=True,
                title="Async flow has no retry/DLQ/idempotency mechanism",
                detail=(f"Blueprint has {len(async_nodes)} async messaging node(s){amqp_note} "
                        f"but decisions/NFR mapping do not mention retry, DLQ, idempotency, "
                        f"or backoff."),
                recommendation=("Add a dead-letter queue, retry policy, or idempotency key to "
                                "the async consumer's design decision."),
            ))

    # Rule 10 — Sprint resource overload detected by resource leveling (feasibility, high).
    # Reads the pre-computed resource_leveling.overloads written by plan_team_and_resources.
    # high severity → blocks release gate (block=True). Architect must waive or fix.
    # Case: no resource_leveling key (old eval) → rule does NOT fire → no regression.
    overloads = (wbs.get("resource_leveling") or {}).get("overloads") or []
    if overloads:
        worst = max(overloads, key=lambda o: float(o.get("overflow_md") or 0))
        detail_parts = [
            f"Sprint {o['sprint']} {o['role']}: {o['demand_md']:.1f}>{o['capacity_md']:.1f} MD"
            for o in overloads[:3]
        ]
        findings.append(SolutionFinding(
            severity="high", confidence="medium", dimension="feasibility",
            artifact_type="wbs", repair_strategy="human_decision",
            entity_ids=[], requires_human_decision=True,
            title=f"Schedule not deliverable: {len(overloads)} sprint(s) overloaded",
            detail=("; ".join(detail_parts)
                    + f" (worst: sprint {worst['sprint']} {worst['role']} "
                    f"+{float(worst['overflow_md']):.1f} MD over capacity)."),
            recommendation=("Increase FTE, reduce scope per sprint, or extend the timeline "
                            "to distribute load across sprints."),
        ))

    return findings


# --- verdict + rendering (mirrors findings.format_critique) ------------------

def _rank_key(f: SolutionFinding) -> tuple[int, int]:
    return (_SEVERITY_ORDER[f.severity], 1 if requires_human(f) else 0)


def is_blocking(f: SolutionFinding) -> bool:
    return _SEVERITY_ORDER[f.severity] >= _SEVERITY_ORDER[BLOCKING_SEVERITY]


def requires_human(f: SolutionFinding) -> bool:
    """A finding a person must settle (a scope/cost/risk trade-off), not a mechanical fix."""
    return f.requires_human_decision or f.repair_strategy in ("human_decision", "request_evidence")


def is_auto_repair(f: SolutionFinding) -> bool:
    """A finding an agent/tool can fix mechanically (patch the blueprint/wbs/deck)."""
    return f.repair_strategy in AUTO_REPAIR_STRATEGIES


def coverage_ratio(findings: list[SolutionFinding], total_requirements: int) -> float:
    """Traceability coverage = 1 - (unmapped requirements / total)."""
    if total_requirements <= 0:
        return 1.0
    unmapped = sum(1 for f in findings if f.dimension == "coverage")
    return round(max(0.0, 1.0 - unmapped / total_requirements), 3)


def format_validation(findings: list[SolutionFinding], *, block: bool = False) -> str:
    """Render a deterministic, machine-greppable summary.

    First line is `VALIDATION: PASS|AUTO-REPAIR|HUMAN-DECISION|WARN|BLOCK` (docx §7.1: a
    gate has three outcomes — pass, auto-repair, human-decision) so a gate can branch
    without parsing JSON. `block=True` (the release gate) promotes any blocking finding
    to BLOCK; callers should pass only NON-waived findings so a waived defect can't
    re-block an export.
    """
    kept = sorted(findings, key=_rank_key, reverse=True)[:MAX_FINDINGS]
    if not kept:
        return "VALIDATION: PASS (no cross-artifact contradictions found)"
    blockers = [f for f in kept if is_blocking(f)]
    human = [f for f in kept if requires_human(f)]
    auto = [f for f in kept if is_auto_repair(f)]
    if block and blockers:
        state, gloss = "BLOCK", f"{len(blockers)} blocking — resolve or waive before export"
    elif human:
        state, gloss = "HUMAN-DECISION", f"{len(human)} need a human decision (waive_finding/resolve_finding)"
    elif auto:
        state, gloss = "AUTO-REPAIR", f"{len(auto)} mechanically fixable, none blocking"
    else:
        state, gloss = "WARN", f"{len(kept)} advisory"
    lines = [f"VALIDATION: {state} ({gloss})"]
    for f in kept:
        flag = " [needs human decision]" if requires_human(f) else ""
        ids = f" {f.entity_ids}" if f.entity_ids else ""
        line = (f"- [{f.severity}/{f.dimension}] ({f.finding_id} repair={f.repair_strategy})"
                f"{flag} {f.title}:{ids} {f.detail}")
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
        from backends import current_workspace  # local import keeps this module importable standalone
        workspace = current_workspace()
    workspace = Path(workspace)
    brief = _read_json(workspace / "diagram_brief.json", {}) or {}
    blueprint = _read_json(workspace / "blueprint.json", {}) or {}
    wbs = _read_json(workspace / "wbs.json", {}) or {}
    # Build the CSM so semantic findings carry stable ids. Function-local import keeps
    # this module importable standalone and avoids the cycle (csm_adapter imports us).
    try:
        from csm_adapter import build_solution_model
        model = build_solution_model(workspace)
    except Exception:
        model = None
    findings = evaluate_solution(brief, blueprint, wbs, model=model)
    return findings, format_validation(findings, block=block)
