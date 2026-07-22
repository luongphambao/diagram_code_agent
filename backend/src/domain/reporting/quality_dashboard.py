"""Quality dashboard (docx §quality-dashboard) — aggregate health metrics for a workspace.

Reads the persisted stores (findings_log, decision_log, evidence_log, solution_model)
and computes a single `QualitySnapshot`: finding breakdowns, decision throughput,
evidence coverage, assumption confirmation, risk mitigations, a 0-100 quality
score with a letter grade, and deck-specific metrics (Phase 3).

No external deps — reads JSON files only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

SNAPSHOT_NAME = "quality_snapshot.json"


@dataclass
class DeckMetrics:
    """Deck-specific quality signals derived from deck_plan.json / deck_qa_result.json /
    deck_visual_audit.json.  All fields are None when the deck artefact is absent."""

    storyboard_revision: int = 0
    slide_count: int = 0
    trace_coverage_pct: float = 0.0  # slides with source_refs / total
    structure_score: Optional[int] = None
    structure_grade: Optional[str] = None
    open_findings: int = 0
    open_findings_by_dim: dict = field(default_factory=dict)
    visual_audit_high: int = 0
    visual_audit_medium: int = 0
    visual_passed: Optional[bool] = None


class QualitySnapshot(BaseModel):
    workspace: str = ""
    solution_revision: int = 0

    # --- findings -------------------------------------------------------
    total_findings: int = 0
    findings_open: int = 0
    findings_waived: int = 0
    findings_resolved: int = 0
    findings_by_dimension: dict[str, int] = Field(default_factory=dict)
    findings_by_severity: dict[str, int] = Field(default_factory=dict)

    # --- decisions (human HITL actions) ---------------------------------
    total_decisions: int = 0
    decisions_by_gate: dict[str, int] = Field(default_factory=dict)
    decisions_by_action: dict[str, int] = Field(default_factory=dict)

    # --- evidence -------------------------------------------------------
    total_evidence: int = 0
    evidence_by_confidence: dict[str, int] = Field(default_factory=dict)
    total_requirements: int = 0
    requirements_with_evidence: int = 0
    evidence_coverage_pct: float = 0.0

    # --- assumptions ----------------------------------------------------
    total_assumptions: int = 0
    assumptions_confirmed: int = 0
    assumptions_pending: int = 0
    assumptions_rejected: int = 0
    assumptions_by_tier: dict[str, int] = Field(default_factory=dict)
    assumption_confirmation_pct: float = 0.0

    # --- risks ----------------------------------------------------------
    total_risks: int = 0
    risks_by_probability: dict[str, int] = Field(default_factory=dict)
    risks_mitigated: int = 0
    risk_mitigation_pct: float = 0.0

    # --- cost / spend-to-quality (§4.10 observability) ------------------
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    model_calls: int = 0
    tokens_by_stage: dict[str, int] = Field(default_factory=dict)
    calls_by_stage: dict[str, int] = Field(default_factory=dict)

    # --- quality score --------------------------------------------------
    quality_score: float = 0.0
    quality_grade: str = "?"
    score_breakdown: dict[str, float] = Field(default_factory=dict)

    # --- deck (Phase 3) — not serialised as a sub-model to keep JSON flat ---
    deck_storyboard_revision: int = 0
    deck_slide_count: int = 0
    deck_trace_coverage_pct: float = 0.0
    deck_structure_score: Optional[int] = None
    deck_structure_grade: Optional[str] = None
    deck_open_findings: int = 0
    deck_open_findings_by_dim: dict[str, int] = Field(default_factory=dict)
    deck_visual_high: int = 0
    deck_visual_medium: int = 0
    deck_visual_passed: Optional[bool] = None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception:
        return None


def _pct(num: int, denom: int) -> float:
    return round(100.0 * num / denom, 1) if denom else 0.0


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 45:
        return "D"
    return "F"


def _compute_score(snap: QualitySnapshot) -> tuple[float, dict[str, float]]:
    """0-100 quality score.

    Base: 70. Penalties for open findings by severity.
    Bonuses for evidence coverage, assumption confirmation rate,
    risk mitigation, and no pending human decisions.
    Score is clamped to [0, 100].
    """
    breakdown: dict[str, float] = {"base": 70.0}

    # Findings penalty — open only (waived/resolved are settled)
    high = sum(
        1
        for dim_counts in [snap.findings_by_severity]
        for sev, cnt in dim_counts.items()
        if sev == "high"
        for _ in range(cnt)
    )
    medium = sum(cnt for sev, cnt in snap.findings_by_severity.items() if sev == "medium")
    low = sum(cnt for sev, cnt in snap.findings_by_severity.items() if sev in ("low", "info"))
    # Recount from raw severity counts of OPEN findings (findings_by_severity
    # already only covers open findings via build_quality_snapshot filter)
    penalty_findings = -(high * 5 + medium * 3 + low * 1)
    breakdown["findings_penalty"] = penalty_findings

    # Evidence coverage bonus
    ev_bonus = 0.0
    if snap.evidence_coverage_pct >= 80:
        ev_bonus = 10.0
    elif snap.evidence_coverage_pct >= 50:
        ev_bonus = 5.0
    breakdown["evidence_bonus"] = ev_bonus

    # Assumption confirmation bonus
    conf_bonus = 0.0
    if snap.assumption_confirmation_pct >= 80:
        conf_bonus = 10.0
    elif snap.assumption_confirmation_pct >= 50:
        conf_bonus = 5.0
    breakdown["assumption_confirmation_bonus"] = conf_bonus

    # Risk mitigation bonus
    risk_bonus = 0.0
    if snap.total_risks > 0 and snap.risk_mitigation_pct >= 80:
        risk_bonus = 5.0
    elif snap.total_risks > 0 and snap.risk_mitigation_pct >= 50:
        risk_bonus = 2.0
    breakdown["risk_mitigation_bonus"] = risk_bonus

    # No open must_confirm assumptions unaddressed
    must_pending = snap.assumptions_by_tier.get("must_confirm", 0)
    must_bonus = 0.0 if must_pending else 5.0
    breakdown["must_confirm_resolved_bonus"] = must_bonus

    total = 70.0 + penalty_findings + ev_bonus + conf_bonus + risk_bonus + must_bonus
    total = max(0.0, min(100.0, total))
    return round(total, 1), breakdown


def build_quality_snapshot(workspace: Path) -> QualitySnapshot:
    """Read all persisted stores and assemble a QualitySnapshot. No LLM, no I/O."""
    ws = Path(workspace)
    snap = QualitySnapshot(workspace=str(ws))

    # --- solution model -------------------------------------------------
    sm_raw = _read_json(ws / "solution_model.json")
    if sm_raw:
        snap.solution_revision = sm_raw.get("revision", 0)
        reqs = sm_raw.get("requirements", [])
        assumptions_raw = sm_raw.get("assumptions", [])
        risks_raw = sm_raw.get("risks", [])
        evidence_raw = sm_raw.get("evidence", [])

        snap.total_requirements = len(reqs)
        snap.total_assumptions = len(assumptions_raw)

        # evidence_ids on requirements
        evd_ids_per_req: list[set[str]] = []
        for r in reqs:
            # Evidence links via trace_links; for now count evidence entities that
            # mention this req in supports_entity_ids
            evd_ids_per_req.append(set())
        evd_id_to_supports: dict[str, list[str]] = {
            e["id"]: e.get("supports_entity_ids", [])
            for e in evidence_raw
            if isinstance(e, dict) and e.get("id")
        }
        req_ids = {r["id"] for r in reqs if isinstance(r, dict) and r.get("id")}
        covered_req_ids: set[str] = set()
        for evd_id, supports in evd_id_to_supports.items():
            for sid in supports:
                if sid in req_ids:
                    covered_req_ids.add(sid)
        snap.requirements_with_evidence = len(covered_req_ids)
        snap.evidence_coverage_pct = _pct(len(covered_req_ids), snap.total_requirements)

        # assumptions
        for a in assumptions_raw:
            if not isinstance(a, dict):
                continue
            st = a.get("status", "pending")
            if st == "confirmed":
                snap.assumptions_confirmed += 1
            elif st == "rejected":
                snap.assumptions_rejected += 1
            else:
                snap.assumptions_pending += 1
            tier = a.get("confidence_tier", "should_confirm")
            snap.assumptions_by_tier[tier] = snap.assumptions_by_tier.get(tier, 0) + 1
        snap.assumption_confirmation_pct = _pct(snap.assumptions_confirmed, snap.total_assumptions)

        # risks
        snap.total_risks = len(risks_raw)
        for r in risks_raw:
            if not isinstance(r, dict):
                continue
            prob = r.get("probability", "") or ""
            if prob:
                snap.risks_by_probability[prob] = snap.risks_by_probability.get(prob, 0) + 1
            if r.get("mitigation", "").strip():
                snap.risks_mitigated += 1
        snap.risk_mitigation_pct = _pct(snap.risks_mitigated, snap.total_risks)

    # --- findings_log ---------------------------------------------------
    findings_raw = _read_json(ws / "findings_log.json")
    if findings_raw:
        findings = findings_raw.get("findings", []) if isinstance(findings_raw, dict) else findings_raw
        snap.total_findings = len(findings)
        open_sev: dict[str, int] = {}
        open_dim: dict[str, int] = {}
        for f in findings or []:
            if not isinstance(f, dict):
                continue
            status = f.get("status", "open")
            if status == "waived":
                snap.findings_waived += 1
            elif status == "resolved":
                snap.findings_resolved += 1
            else:
                snap.findings_open += 1
                sev = f.get("severity", "medium")
                open_sev[sev] = open_sev.get(sev, 0) + 1
                dim = f.get("dimension", "unknown")
                open_dim[dim] = open_dim.get(dim, 0) + 1
        snap.findings_by_severity = open_sev
        snap.findings_by_dimension = open_dim

    # --- decision_log ---------------------------------------------------
    dec_raw = _read_json(ws / "decision_log.json")
    if dec_raw:
        decisions = dec_raw.get("decisions", []) if isinstance(dec_raw, dict) else dec_raw
        snap.total_decisions = len(decisions)
        for d in decisions or []:
            if not isinstance(d, dict):
                continue
            gate = d.get("gate", "unknown")
            snap.decisions_by_gate[gate] = snap.decisions_by_gate.get(gate, 0) + 1
            action = d.get("action", "unknown")
            snap.decisions_by_action[action] = snap.decisions_by_action.get(action, 0) + 1

    # --- evidence_log ---------------------------------------------------
    ev_raw = _read_json(ws / "evidence_log.json")
    if ev_raw:
        evidence = ev_raw.get("evidence", []) if isinstance(ev_raw, dict) else ev_raw
        snap.total_evidence = len(evidence)
        for e in evidence or []:
            if not isinstance(e, dict):
                continue
            conf = e.get("confidence", "medium")
            snap.evidence_by_confidence[conf] = snap.evidence_by_confidence.get(conf, 0) + 1

    # --- deck_plan (Phase 3) --------------------------------------------
    deck_plan_raw = _read_json(ws / "deck_plan.json")
    if deck_plan_raw:
        slides = deck_plan_raw.get("slides", [])
        snap.deck_storyboard_revision = deck_plan_raw.get("revision", 0)
        snap.deck_slide_count = len(slides)
        grounded = sum(1 for s in slides if s.get("source_refs"))
        snap.deck_trace_coverage_pct = round(100.0 * grounded / len(slides), 1) if slides else 0.0

    deck_qa_raw = _read_json(ws / "deck_qa_result.json")
    if deck_qa_raw:
        snap.deck_structure_score = deck_qa_raw.get("structural_score")
        snap.deck_structure_grade = deck_qa_raw.get("structural_grade")
        qa_findings = deck_qa_raw.get("findings", [])
        open_qa = [f for f in qa_findings if isinstance(f, dict) and f.get("status", "open") == "open"]
        snap.deck_open_findings = len(open_qa)
        for f in open_qa:
            dim = f.get("dimension", "unknown")
            snap.deck_open_findings_by_dim[dim] = snap.deck_open_findings_by_dim.get(dim, 0) + 1

    visual_raw = _read_json(ws / "deck_visual_audit.json")
    if visual_raw:
        snap.deck_visual_high = visual_raw.get("high_count", 0)
        snap.deck_visual_medium = visual_raw.get("medium_count", 0)
        snap.deck_visual_passed = visual_raw.get("passed")

    # --- usage.json (cost per stage, §4.10 spend-to-quality) ------------
    # UsageLoggingMiddleware appends one record per model call: {agent, input_tokens,
    # output_tokens, total_tokens}.  Aggregate into per-stage totals so the team can
    # correlate token spend with the quality score above.
    usage_raw = _read_json(ws / "usage.json")
    if isinstance(usage_raw, list):
        for rec in usage_raw:
            if not isinstance(rec, dict):
                continue
            stage = rec.get("agent", "unknown")
            tot = int(rec.get("total_tokens", 0) or 0)
            snap.total_input_tokens += int(rec.get("input_tokens", 0) or 0)
            snap.total_output_tokens += int(rec.get("output_tokens", 0) or 0)
            snap.total_tokens += tot
            snap.model_calls += 1
            snap.tokens_by_stage[stage] = snap.tokens_by_stage.get(stage, 0) + tot
            snap.calls_by_stage[stage] = snap.calls_by_stage.get(stage, 0) + 1

    # --- score ----------------------------------------------------------
    snap.quality_score, snap.score_breakdown = _compute_score(snap)
    snap.quality_grade = _grade(snap.quality_score)

    return snap


def write_snapshot(snap: QualitySnapshot, workspace: Path) -> None:
    path = Path(workspace) / SNAPSHOT_NAME
    path.write_text(
        json.dumps(snap.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_snapshot(workspace: Path) -> Optional[QualitySnapshot]:
    raw = _read_json(Path(workspace) / SNAPSHOT_NAME)
    if not raw:
        return None
    try:
        return QualitySnapshot.model_validate(raw)
    except Exception:
        return None


def format_snapshot(snap: QualitySnapshot) -> str:
    """Render a compact text summary of the quality snapshot."""
    grade_emoji = {"A": "✅", "B": "🟢", "C": "🟡", "D": "🟠", "F": "🔴"}.get(snap.quality_grade, "")
    lines: list[str] = [
        f"\nQUALITY DASHBOARD — revision {snap.solution_revision} "
        f"| Score {snap.quality_score}/100 [{snap.quality_grade}] {grade_emoji}",
    ]

    # Findings
    if snap.total_findings:
        open_detail = (
            ", ".join(f"{sev}:{cnt}" for sev, cnt in sorted(snap.findings_by_severity.items())) or "none"
        )
        lines.append(
            f"  Findings: {snap.total_findings} total "
            f"({snap.findings_open} open [{open_detail}], "
            f"{snap.findings_waived} waived, {snap.findings_resolved} resolved)"
        )
        if snap.findings_by_dimension:
            dim_str = " | ".join(f"{d}:{c}" for d, c in snap.findings_by_dimension.items())
            lines.append(f"    By dimension: {dim_str}")
    else:
        lines.append("  Findings: none")

    # Assumptions
    if snap.total_assumptions:
        tier_str = " | ".join(f"{t.replace('_confirm', '')}:{c}" for t, c in snap.assumptions_by_tier.items())
        must_pending = snap.assumptions_by_tier.get("must_confirm", 0)
        must_flag = f" ⚠ {must_pending} must-confirm still pending" if must_pending else ""
        lines.append(
            f"  Assumptions: {snap.total_assumptions} total "
            f"({snap.assumptions_confirmed} confirmed, {snap.assumptions_pending} pending)"
            f" [{tier_str}]{must_flag}"
        )

    # Evidence
    lines.append(
        f"  Evidence: {snap.total_evidence} record(s), "
        f"covers {snap.requirements_with_evidence}/{snap.total_requirements} requirements "
        f"({snap.evidence_coverage_pct}%)"
    )

    # Risks
    if snap.total_risks:
        lines.append(
            f"  Risks: {snap.total_risks} total, "
            f"{snap.risks_mitigated} with mitigation ({snap.risk_mitigation_pct}%)"
        )

    # Decisions
    if snap.total_decisions:
        lines.append(f"  HITL decisions: {snap.total_decisions} total")

    # Cost / spend-to-quality (§4.10)
    if snap.total_tokens:
        stage_str = " | ".join(
            f"{stage}:{tok:,}" for stage, tok in sorted(snap.tokens_by_stage.items(), key=lambda kv: -kv[1])
        )
        lines.append(
            f"  Cost: {snap.total_tokens:,} tokens over {snap.model_calls} model call(s) "
            f"(in {snap.total_input_tokens:,} / out {snap.total_output_tokens:,})"
        )
        if stage_str:
            lines.append(f"    By stage: {stage_str}")

    # Score breakdown
    bd = snap.score_breakdown
    bd_str = ", ".join(f"{k}={v:+.0f}" for k, v in bd.items() if k != "base")
    lines.append(f"  Score: base=70 {bd_str} → {snap.quality_score}")

    # Deck (Phase 3)
    if snap.deck_slide_count:
        deck_struct = (
            f", struct {snap.deck_structure_score}/100 [{snap.deck_structure_grade}]"
            if snap.deck_structure_score is not None
            else ""
        )
        lines.append(
            f"  Deck    : rev {snap.deck_storyboard_revision}, "
            f"{snap.deck_slide_count} slides, "
            f"{snap.deck_trace_coverage_pct}% grounded{deck_struct}"
        )
        if snap.deck_open_findings:
            dim_str = " | ".join(f"{d}:{c}" for d, c in snap.deck_open_findings_by_dim.items())
            lines.append(f"    Deck findings open: {snap.deck_open_findings} [{dim_str}]")
        if snap.deck_visual_passed is not None:
            vis_icon = "✅" if snap.deck_visual_passed else "⚠"
            lines.append(
                f"    Visual audit: {vis_icon} HIGH:{snap.deck_visual_high} MED:{snap.deck_visual_medium}"
            )

    return "\n".join(lines)
