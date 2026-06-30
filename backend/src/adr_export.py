"""ADR / decision-log export (docx §8.6, §10.3 "Decision memory").

Renders the recorded decisions into a Markdown Architecture Decision Record pack so an
enterprise engagement ships an auditable "why" alongside the proposal: each CSM
`Decision` entity becomes an ADR (options, choice, rationale, linked evidence/risks/
assumptions), followed by the human approval timeline from `decision_log.json` (who
took which gate action, when, against which revision).

Pure rendering — reads `solution_model.json` + `decision_log.json`, writes
`adr_pack.md`. Imports only `csm` + `decisions` (cycle-free).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from csm import Decision, SolutionModel

ADR_PACK_NAME = "adr_pack.md"


def _read_model(workspace: Path) -> Optional[SolutionModel]:
    path = workspace / "solution_model.json"
    if not path.exists():
        return None
    try:
        return SolutionModel.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return None


def _render_decision(d: Decision, model: SolutionModel) -> list[str]:
    lines = [f"## {d.id} — {d.title or '(untitled decision)'}", ""]
    lines.append(f"- **Status:** {d.status}")
    if d.approver:
        lines.append(f"- **Approver:** {d.approver}")
    if d.options:
        chosen = d.selected_option_id
        lines.append("- **Options considered:**")
        for opt in d.options:
            mark = " ✅ (chosen)" if opt.id == chosen else ""
            trade = f" — {opt.trade_offs}" if opt.trade_offs else ""
            lines.append(f"  - {opt.title}{mark}{trade}")
    if d.rationale:
        lines.append(f"- **Rationale:** {d.rationale}")
    if d.assumption_ids:
        lines.append(f"- **Assumptions:** {', '.join(d.assumption_ids)}")
    if d.evidence_ids:
        lines.append(f"- **Evidence:** {', '.join(d.evidence_ids)}")
    if d.risk_ids:
        lines.append(f"- **Risks introduced:** {', '.join(d.risk_ids)}")
    lines.append("")
    return lines


def render_adr_pack(workspace: Path) -> tuple[str, int]:
    """Render the ADR pack Markdown; returns (markdown, n_decisions_rendered)."""
    from decisions import read_decisions

    model = _read_model(workspace)
    decisions = model.decisions if model else []
    human_records = read_decisions(workspace)

    out: list[str] = ["# Architecture Decision Records", ""]
    if model:
        out.append(f"Solution revision: REV-{model.revision}")
        out.append("")

    if decisions:
        for d in decisions:
            out.extend(_render_decision(d, model))
    else:
        out.append("_No architecture decisions captured in the solution model yet._")
        out.append("")

    # Approval timeline from the human decision log.
    if human_records:
        out.append("## Approval timeline (HITL decision log)")
        out.append("")
        out.append("| When | Gate | Action | Approver | Rev | Note |")
        out.append("|------|------|--------|----------|-----|------|")
        for r in human_records:
            note = (r.comment or "").replace("|", "\\|").replace("\n", " ")
            out.append(
                f"| {r.timestamp or '-'} | {r.gate or '-'} | {r.action} | "
                f"{r.approver or '-'} | {r.revision or '-'} | {note} |"
            )
        out.append("")

    return "\n".join(out), len(decisions)


def write_adr_pack(workspace: Optional[Path] = None) -> tuple[Path, int]:
    """Write `adr_pack.md` into the workspace; returns (path, n_decisions)."""
    if workspace is None:
        from backends import current_workspace
        workspace = current_workspace()
    workspace = Path(workspace)
    md, n = render_adr_pack(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / ADR_PACK_NAME
    path.write_text(md, encoding="utf-8")
    return path, n
