"""Workspace artifact/metrics readers for the chat response payload."""

from __future__ import annotations

import json
from pathlib import Path

from .normalize import _coerce_brief, _normalize_blueprint, _normalize_tech_stack


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception:  # noqa: BLE001
        return None


def _artifacts(workspace) -> dict:
    """Read the diagram artifacts currently in the workspace (if any)."""
    import base64

    out: dict = {}
    png = workspace / "out.png"
    if png.exists():
        out["png_base64"] = base64.b64encode(png.read_bytes()).decode("ascii")
    drawio = workspace / "out.drawio"
    if drawio.exists():
        out["drawio"] = drawio.read_text(encoding="utf-8", errors="replace")
    code = workspace / "diagram.py"
    if code.exists():
        out["code"] = code.read_text(encoding="utf-8", errors="replace")
    pdf = workspace / "out.pdf"
    if pdf.exists():
        out["pdf_base64"] = base64.b64encode(pdf.read_bytes()).decode("ascii")
    pptx = workspace / "out.pptx"
    if pptx.exists():
        out["pptx_base64"] = base64.b64encode(pptx.read_bytes()).decode("ascii")
    xlsx = workspace / "wbs_filled.xlsx"
    if xlsx.exists():
        out["wbs_xlsx_base64"] = base64.b64encode(xlsx.read_bytes()).decode("ascii")
    return out


def _stage_artifacts(workspace) -> dict:
    """Read structured planning artifacts currently in the workspace."""
    out: dict = {}
    analysis = _read_json(workspace / "architecture_analysis.json")
    brief = _read_json(workspace / "diagram_brief.json")
    ts = _read_json(workspace / "tech_stack.json")
    ts_draft = _read_json(workspace / "tech_stack_draft.json")
    bp = _read_json(workspace / "blueprint.json")
    bp_draft = _read_json(workspace / "blueprint_draft.json")
    pending_gate = _read_json(workspace / "pending_gate.json")
    tool_summary = _read_json(workspace / "tool_budget_summary.json")
    wbs = _read_json(workspace / "wbs.json")
    if analysis:
        out["architecture_analysis"] = _coerce_brief(analysis)
    if brief:
        out["diagram_brief"] = _coerce_brief(brief)
    if ts:
        out["tech_stack"] = _normalize_tech_stack(ts)
    elif ts_draft:
        out["tech_stack_draft"] = ts_draft
    if bp:
        out["blueprint"] = _normalize_blueprint(bp)
    elif bp_draft:
        out["blueprint_draft"] = _normalize_blueprint(bp_draft)
    if pending_gate:
        out["pending_gate"] = pending_gate
    if tool_summary:
        out["tool_budget_summary"] = tool_summary
    if wbs:
        totals = wbs.get("effort_totals") or {}
        timeline = wbs.get("timeline") or {}
        out["wbs_summary"] = {
            "total_mandays": totals.get("total_mandays", 0),
            "total_manmonths": totals.get("total_manmonths", 0),
            "effort_by_role": totals.get("effort_by_role", {}),
            "weeks": timeline.get("weeks", 0),
            "months": timeline.get("months", 0),
            "effort_by_module": (wbs.get("effort_by_module") or [])[:12],
        }

    # Governance read-outs for the canvas "Quality" tab (display-only; present only once
    # the agent has run quality_summary / reality_sync / apply_compliance_pack).
    quality = _read_json(workspace / "quality_snapshot.json")
    if quality:
        out["quality"] = quality
    drift = _read_json(workspace / "drift_report.json")
    if drift:
        out["drift"] = drift
    last_meeting = _read_json(workspace / "last_meeting.json")
    if last_meeting:
        out["last_meeting"] = last_meeting
    pack = _read_json(workspace / "compliance_pack.json")
    if pack and pack.get("pack"):
        model = _read_json(workspace / "solution_model.json") or {}
        controls = [
            {
                "id": c.get("id", ""),
                "name": c.get("name", ""),
                "kind": c.get("kind", ""),
                "standard_ref": c.get("standard_ref", ""),
                "status": c.get("status", "required"),
                "grounded": bool(c.get("evidence_ids")),
                "implemented": bool(c.get("implemented_by_ids")),
            }
            for c in (model.get("controls") or [])
        ]
        out["compliance"] = {"pack": pack.get("pack"), "controls": controls}
    return out


def _run_metrics(workspace, logs: list[dict]) -> dict:
    tool_counts: dict[str, int] = {}
    model_calls = 0
    for item in logs:
        if item.get("type") == "llm":
            model_calls += 1
        elif item.get("type") == "tool_start":
            tool = item.get("tool") or "tool"
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
    out = {"model_calls": model_calls, "tool_counts": tool_counts}
    tool_summary = _read_json(workspace / "tool_budget_summary.json")
    if tool_summary:
        out["tool_budget_summary"] = tool_summary
    return out
