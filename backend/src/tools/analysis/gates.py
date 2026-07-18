"""Cross-artifact / CSM gate tools: solution + diagram lint notes, change-impact queries.

``_solution_gate_note`` and ``_diagram_gate_note`` are called from
``blueprint_tools.py`` and ``reporting_gates.py`` (and from
``tools/rendering_tools.py`` for the diagram lint) at pipeline gates.
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from backends import current_workspace
from memory.stores.csm import SolutionModel
from memory.stores.csm_adapter import build_solution_model, SOLUTION_MODEL_NAME, SOLUTION_MODEL_PREV_NAME
from memory.stores.csm_diff import diff_solution_models
from domain.validation.solution_validator import format_validation, validate_solution
from domain.reporting.traceability import write_trace_links
from ..stage_markers import _read_json_file


def _epistemic_note(model, *, cap: int = 8) -> str:
    """Render the CSM's epistemic split (docx §4.2) as a compact block with entity IDs.

    Shows what is known vs. what still needs a human: confirmed facts, pending
    assumptions (flagged for customer confirmation), open decisions, and hard
    constraints. Each item is prefixed with its stable CSM id so the user can act on
    it at a gate via HITL v2 — `approve_with_assumptions` (confirm specific ASM-* ids)
    or `request_evidence` — and the confirmed/accepted state flows back into the CSM.
    """
    try:
        summ = model.epistemic_summary()
    except Exception:
        return ""

    def _ids(items, text_key):
        return [f'{it.get("id", "?")}: {it[text_key]}' for it in items]

    pending = summ.get("assumptions_needing_confirmation", [])
    must   = [a for a in pending if a.get("tier") == "must_confirm"]
    should = [a for a in pending if a.get("tier") == "should_confirm"]
    nice   = [a for a in pending if a.get("tier") == "nice_to_confirm"]

    asm_sections: list[tuple[str, list]] = []
    if must:
        asm_sections.append(("Assumptions — MUST CONFIRM (financial/deadline/compliance/SLA)", must))
    if should:
        asm_sections.append(("Assumptions — should confirm", should))
    if nice:
        asm_sections.append(("Assumptions — nice to confirm", nice))

    sections: list[tuple[str, list]] = [
        ("Known facts", _ids(summ["known_facts"], "statement")),
    ]
    for tier_title, tier_items in asm_sections:
        sections.append((tier_title + " — confirm via approve_with_assumptions",
                         _ids(tier_items, "statement")))
    sections += [
        ("Open decisions", _ids(summ["open_decisions"], "title")),
        ("Constraints",
         [f'{c.get("id", "?")}: {c["statement"]} [{c["kind"]}]' for c in summ["constraints"]]),
    ]
    lines: list[str] = []
    for title, items in sections:
        if not items:
            continue
        lines.append(f"{title}:")
        lines.extend(f"  - {it}" for it in items[:cap])
        if len(items) > cap:
            lines.append(f"  - … (+{len(items) - cap} more)")
    if not lines:
        return ""
    return "\n\nEPISTEMIC SUMMARY (confirm assumptions / request evidence at the gate):\n" + "\n".join(lines)


def _solution_gate_note(stage: str = "export", *, block: bool = False) -> str:
    """Run the cross-artifact validator + refresh trace_links.json at a pipeline gate.

    Called after a stage (`blueprint`/`wbs`, advisory) and before an export
    (`block=True`, the release gate). The validator's findings are merged into the
    persisted `findings_log.json` so a defect keeps a stable id and a `waived`/`resolved`
    status survives re-runs; findings a human already settled are dropped here, so a
    waived defect can never re-block an export (docx §4.3, §7.1). The summary's first
    line is `VALIDATION: PASS|AUTO-REPAIR|HUMAN-DECISION|WARN|BLOCK` for the three gate
    outcomes (pass / auto-repair / human-decision), plus an epistemic summary.
    """
    try:
        model = build_solution_model(current_workspace())   # materialize/refresh the CSM projection
        write_trace_links(current_workspace())
        findings, _ = validate_solution(current_workspace(), block=block)
    except Exception:
        return ""
    # Merge compliance-pack findings (required controls missing/ungrounded, §4 P2).
    # No-op unless a pack was selected via apply_compliance_pack.
    try:
        from compliance import compliance_findings
        findings = list(findings) + compliance_findings(model)
    except Exception:
        pass
    # Persist the lifecycle and drop findings a human already waived/resolved, so the
    # gate reflects open work only. Best-effort: a store hiccup must not break the gate.
    try:
        from memory.stores.finding_store import active_findings, upsert_findings
        upsert_findings(findings, revision=model.revision)
        findings = active_findings(findings)
    except Exception:
        pass
    summary = format_validation(findings, block=block)
    csm_note = (
        f"\n\nSOLUTION MODEL — revision {model.revision}: "
        f"{len(model.requirements)} req, {len(model.components)} component, "
        f"{len(model.work_items)} task, {len(model.trace_links)} trace link(s) "
        "(solution_model.json)."
    )
    csm_note += _epistemic_note(model)
    if not findings:
        return csm_note
    note = csm_note + f"\n\nCROSS-ARTIFACT CHECK [{stage}] — " + summary
    if block and summary.startswith("VALIDATION: BLOCK"):
        note += (
            "\n\nRELEASE GATE: blocking contradiction(s) remain — do NOT send this to the "
            "client. Either fix the artifact and re-run, or, if it is an accepted trade-off, "
            "call waive_finding(finding_id, reason) / resolve_finding(finding_id, fix_applied) "
            "to record the decision and clear the block."
        )
    return note


def _diagram_gate_note(*, block: bool = False) -> str:
    """Lint out.drawio → SolutionFindings → persist lifecycle → 3-outcome summary.

    Mirrors _solution_gate_note() but scoped to the rendered diagram artifact.
    Findings go into findings_log.json so waive_finding/resolve_finding apply
    to diagram defects just like blueprint/WBS defects (docx §4.7).
    """
    from domain.validation.validate_drawio import validate_file, findings_from_validation
    from memory.stores.finding_store import active_findings, upsert_findings
    from domain.validation.solution_validator import format_validation

    drawio_path = current_workspace() / "out.drawio"
    if not drawio_path.exists():
        return ""
    import json as _json
    stats = {}
    try:
        stats_path = current_workspace() / "out.native_stats.json"
        stats = _json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else {}
    except Exception:
        pass
    try:
        result = validate_file(str(drawio_path), stats=stats)
        # Spec-level Well-Architected advice (refined/non-AWS diagrams — the XML
        # never carries mxgraph.aws4.* stencils for audit_architecture()'s own
        # gate to key on). Merge into the same advice bucket so it gets the
        # standard low-severity/no-action treatment via findings_from_validation.
        well_arch = stats.get("well_arch_advice") or []
        if well_arch:
            result = dict(result, advice=list(result.get("advice") or []) + list(well_arch))
        findings = findings_from_validation(result)
    except Exception:
        return ""
    # V2 §16 production scorecard — reuses the persisted native stats (semantic
    # preservation + routing residuals) from the last export.
    scorecard_note = ""
    try:
        from domain.validation.validate_drawio import production_scorecard
        sc = production_scorecard(result, stats)
        verdict = ("PASS" if sc["pass"]
                   else "BELOW GATE (need >=85, semantic & relationship = 100%)")
        bd = sc.get("breakdown", {})
        scorecard_note = (f"\n\nPRODUCTION SCORECARD: {sc['total']}/100 — {verdict} "
                          f"(semantic {int(sc['node_recall'] * 100)}%, "
                          f"relationship {int(sc['edge_recall'] * 100)}%, "
                          f"composition {bd.get('composition', '?')}/10, "
                          f"iconography {bd.get('iconography', '?')}/10).")
    except Exception:
        pass
    try:
        revision = "0"
        try:
            from memory.stores.csm_adapter import build_solution_model
            m = build_solution_model(current_workspace())
            revision = str(m.revision)
        except Exception:
            pass
        upsert_findings(findings, revision=revision)
        findings = active_findings(findings)
    except Exception:
        pass
    if not findings:
        return ("\n\nDIAGRAM LINT: PASS — no structural errors, warnings, or style advice."
                + scorecard_note)
    summary = format_validation(findings, block=block)
    note = f"\n\nDIAGRAM LINT [{('blocking' if block else 'advisory')}] — {summary}"
    if block and summary.startswith("VALIDATION: BLOCK"):
        note += (
            "\n\nRELEASE GATE: diagram has blocking defect(s). Fix and re-export, or call "
            "waive_finding(finding_id, reason) / resolve_finding(finding_id, fix_applied) "
            "to record the decision and clear the block."
        )
    return note + scorecard_note


def _impact_ids(dumps: list[dict], cap: int = 8) -> str:
    ids = [str(d.get("id") or "?") for d in dumps]
    head = ", ".join(ids[:cap])
    return head + (f" … (+{len(ids) - cap} more)" if len(ids) > cap else "")


@tool(parse_docstring=True)
def query_change_impact() -> str:
    """Compare the current CSM revision to the previous snapshot and report what changed.

    Reads solution_model.json (current) and solution_model.prev.json (previous, written
    automatically when a revision bumps), diffs them by stable CSM id, and returns a
    compact report: a greppable summary line, then added/removed/changed entities per
    type and trace-link deltas. Call this after the user revises a requirement (and the
    solution model has been refreshed) to see the blast radius of the change. Returns
    CHANGE_IMPACT: NONE when there is no previous snapshot or nothing changed.
    """
    cur_raw = _read_json_file(current_workspace() / SOLUTION_MODEL_NAME, None)
    prev_raw = _read_json_file(current_workspace() / SOLUTION_MODEL_PREV_NAME, None)
    if cur_raw is None:
        return "CHANGE_IMPACT: NONE — no solution model yet (run the pipeline first)."
    if prev_raw is None:
        return "CHANGE_IMPACT: NONE — no previous snapshot yet (model has not changed since first build)."
    try:
        new = SolutionModel.model_validate(cur_raw)
        old = SolutionModel.model_validate(prev_raw)
    except Exception as exc:  # noqa: BLE001
        return f"CHANGE_IMPACT: ERROR — could not parse solution model: {exc}"

    d = diff_solution_models(old, new)
    s = d["summary"]
    total_added = s["entities_added"]
    total_removed = s["entities_removed"]
    total_changed = s["entities_changed"]
    head = (f"CHANGE_IMPACT: REV {d['revision']['from']}→{d['revision']['to']} | "
            f"+{total_added} -{total_removed} ~{total_changed} entities")
    if not (total_added or total_removed or total_changed
            or s["links_added"] or s["links_removed"]):
        return f"CHANGE_IMPACT: NONE — REV {d['revision']['from']}→{d['revision']['to']}, no entity or link changes."

    return "\n".join([head] + _render_model_diff_body(d))


def _render_model_diff_body(d: dict) -> list[str]:
    """Render the per-entity-type + trace-link delta lines of a `diff_solution_models`
    result. Shared by query_change_impact (vs prev snapshot) and compare_revisions
    (vs an approved revision)."""
    lines: list[str] = []
    for label in (
        "requirements", "constraints", "assumptions", "decisions",
        "components", "risks", "work_items",
    ):
        part = d[label]
        if not (part["added"] or part["removed"] or part["changed"]):
            continue
        lines.append(f"{label}: +{len(part['added'])} -{len(part['removed'])} ~{len(part['changed'])}")
        if part["added"]:
            lines.append(f"  added:   {_impact_ids(part['added'])}")
        if part["removed"]:
            lines.append(f"  removed: {_impact_ids(part['removed'])}")
        if part["changed"]:
            lines.append(f"  changed: {_impact_ids(part['changed'])}")
    links = d["trace_links"]
    if links["added"] or links["removed"]:
        lines.append(f"trace_links: +{len(links['added'])} -{len(links['removed'])}")
    return lines


@tool(parse_docstring=True)
def compare_revisions(approved_revision: int = 0) -> str:
    """Compare the current solution model to a previously APPROVED revision (docx §8.6).

    Enterprise audit/collaboration view: diff the live CSM against the immutable snapshot
    a stakeholder signed off on (approved/REV-<n>.json, written when a gate is approved),
    so a reviewer can see exactly what changed since approval — added/removed/changed
    entities per type plus trace-link deltas. With no argument it compares against the
    most recent approved revision. Returns COMPARE: NONE when there is no approved
    snapshot or nothing changed.

    Args:
        approved_revision: The approved revision number to compare against; 0 = latest.
    """
    approved_dir = current_workspace() / "approved"
    if not approved_dir.exists():
        return "COMPARE: NONE — no approved revision yet (approve a gate first)."
    snaps = sorted(approved_dir.glob("REV-*.json"),
                   key=lambda p: int(p.stem.split("-")[1]) if p.stem.split("-")[1].isdigit() else 0)
    if not snaps:
        return "COMPARE: NONE — no approved revision snapshots found."
    if approved_revision:
        target = approved_dir / f"REV-{approved_revision}.json"
        if not target.exists():
            avail = ", ".join(p.stem for p in snaps)
            return f"COMPARE: NONE — approved REV-{approved_revision} not found. Available: {avail}."
    else:
        target = snaps[-1]
    cur_raw = _read_json_file(current_workspace() / SOLUTION_MODEL_NAME, None)
    old_raw = _read_json_file(target, None)
    if cur_raw is None or old_raw is None:
        return "COMPARE: NONE — missing current or approved model."
    try:
        new = SolutionModel.model_validate(cur_raw)
        old = SolutionModel.model_validate(old_raw)
    except Exception as exc:  # noqa: BLE001
        return f"COMPARE: ERROR — could not parse a model: {exc}"
    d = diff_solution_models(old, new)
    s = d["summary"]
    total = s["entities_added"] + s["entities_removed"] + s["entities_changed"]
    head = (f"COMPARE: approved {target.stem} → current REV {d['revision']['to']} | "
            f"+{s['entities_added']} -{s['entities_removed']} ~{s['entities_changed']} entities")
    if not (total or s["links_added"] or s["links_removed"]):
        return f"COMPARE: NONE — current model is unchanged from approved {target.stem}."
    return "\n".join([head] + _render_model_diff_body(d))
