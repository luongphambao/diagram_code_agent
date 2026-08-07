"""Explicit workflow gate state: rejected / retry / waived, on top of file evidence.

Same "small JSON file in the workspace" convention as ``tools/stage_markers.py``
and ``session/artifact_manifest.py`` -- no new persistence mechanism invented.

Why this module exists: ``agent/middleware/phase_filter.py``'s ``_detect_phase``
infers the workflow phase purely from which artifact files exist
(``.exists()``), most-advanced-wins. That can't represent a HUMAN DECISION —
a rejected ``propose_blueprint`` still leaves ``blueprint.json`` on disk (the
draft), so file evidence alone can't tell "drafted" from "approved". This is
the concrete gap the Codex review flagged as MEDIUM-2
(docs/codex/multi-agent-architecture-review-2026-07-30.md).

Design rule (the one thing to preserve in any future edit to this module):
state recorded here may only ever HOLD a phase BACK, never PUSH it forward.
Files remain the sole evidence that an artifact exists; this module is the
sole evidence of what a human decided about it. See
``agent/middleware/phase_filter.py``'s ``_blocked_phases``/``_ready`` for the
consuming side, and ``routers/chat.py``'s gate-outcome block for the writer.

Missing/corrupt state file always resolves to "no opinion" (empty gates/waived
dicts) -- a workspace that never went through ``record_gate_decision`` behaves
exactly as it did before this module existed, and a broken state file can
never narrow ``PhaseToolFilterMiddleware``'s allowed toolset (fail-open, same
property ``_filtered_tools`` already guarantees for every failure mode).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

_STATE_NAME = "workflow_state.json"

PHASES: tuple[str, ...] = ("intake", "blueprint", "draw", "wbs", "ppt", "report", "brd")
# "revise" = a HITL v2 send-back-to-revise action (request_evidence,
# request_alternative) that is NOT a full rejection: the agent should
# re-propose using the same phase's tools, not lose them. Only "rejected"
# ever blocks a phase (see blocked_phases below) -- "revise" is audit-only,
# same as every other recorded status besides the two BLOCKING_GATE_PHASES
# entries.
STATUSES: tuple[str, ...] = ("pending", "approved", "rejected", "revise", "waived")

# gate tool name -> the phase that gate's approval AUTHORIZES. Deliberately NOT
# every entry in GATE_TOOL_NAMES (tools/__init__.py): blocking a phase whose
# _PHASE_TOOLS set lacks the tools needed to revise it would strand the agent
# (e.g. blocking "brd" on an import_brd_docx-only workspace falls to "intake",
# which carries none of _BRD_TOOLS). Only these two gates were verified safe to
# block -- rejecting either always falls back to a phase that still has the
# tool needed to re-propose. See docs/codex plan for the full per-gate trace.
BLOCKING_GATE_PHASES: dict[str, str] = {
    "propose_tech_stack": "blueprint",
    "propose_blueprint": "draw",
}

_MAX_HISTORY = 20


def _state_path(workspace: Path) -> Path:
    return Path(workspace) / _STATE_NAME


def read_state(workspace: Path) -> dict:
    """Load workflow_state.json; a fresh ``{"gates": {}, "waived": {}, "history": []}``
    if absent/corrupt -- the same "no opinion, fall back to file evidence" shape
    a workspace with no state file has always had."""
    default = {"version": 1, "gates": {}, "waived": {}, "history": []}
    try:
        data = json.loads(_state_path(workspace).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default
    if not isinstance(data, dict):
        return default
    gates = data.get("gates")
    waived = data.get("waived")
    history = data.get("history")
    return {
        "version": data.get("version", 1),
        "gates": gates if isinstance(gates, dict) else {},
        "waived": waived if isinstance(waived, dict) else {},
        "history": history if isinstance(history, list) else [],
    }


def _write_state(workspace: Path, state: dict) -> None:
    """Atomic write (tmp + replace) -- unlike artifact_manifest's plain
    write_text, a half-written state file here would be exactly the "partial
    write looks like a decision" failure mode this module exists to prevent."""
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    path = _state_path(workspace)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def record_gate_decision(workspace: Path, gate: str, decision: str, *, note: str = "") -> None:
    """Record a human decision on *gate* ("approve" | "reject" | "revise").

    Called once per resolved gate from routers/chat.py's gate-outcome block --
    the same funnel that already calls record_report_step/record_gate_outcome
    for every entry in GATE_TOOL_NAMES, so this covers all 16 gates in both
    directions from a single call site. Only the two gates in
    BLOCKING_GATE_PHASES ever affect phase detection; every other gate is
    still recorded (status/attempts/history) so the state file stays a
    complete audit trail, just an inert one for those gates today.

    "revise" (a HITL v2 request_evidence/request_alternative action -- the
    user wants more before deciding, not a hard no) is recorded distinctly
    from "reject" precisely so it does NOT satisfy the ``status == "rejected"``
    check in ``blocked_phases`` below: those actions send the agent back to
    re-propose the same gate without stripping the current phase's tools.

    Never raises -- an audit-only write must not break a resume in progress.
    """
    if decision not in ("approve", "reject", "revise"):
        return
    status = {"approve": "approved", "reject": "rejected", "revise": "revise"}[decision]
    try:
        state = read_state(workspace)
        entry = state["gates"].get(gate, {})
        attempts = int(entry.get("attempts", 0)) + 1 if isinstance(entry, dict) else 1
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        state["gates"][gate] = {
            "status": status,
            "attempts": attempts,
            "at": now,
            "note": note or "",
        }
        history = state["history"]
        history.append({"gate": gate, "status": status, "at": now})
        state["history"] = history[-_MAX_HISTORY:]
        _write_state(workspace, state)
    except Exception:  # noqa: BLE001
        return


def record_waiver(workspace: Path, artifact: str, *, note: str = "") -> None:
    """Record that a foundational artifact was explicitly waived (skipped on
    purpose), so its producer tool stops being carried into every downstream
    phase forever (agent/middleware/phase_filter.py's _missing_artifact_tools).
    No caller exists yet in step 1 -- this is schema + read path ahead of a
    future waive_stage tool. Never raises, same rationale as record_gate_decision.
    """
    try:
        state = read_state(workspace)
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        state["waived"][artifact] = {"at": now, "note": note or ""}
        _write_state(workspace, state)
    except Exception:  # noqa: BLE001
        return


def blocked_phases(workspace: Path) -> frozenset[str]:
    """Phases held back by an explicit rejection of their authorizing gate.

    Only gates in BLOCKING_GATE_PHASES can appear here -- a rejection recorded
    for any other gate is audit-only and never blocks anything.
    """
    gates = read_state(workspace).get("gates", {})
    blocked = set()
    for gate, phase in BLOCKING_GATE_PHASES.items():
        entry = gates.get(gate)
        if isinstance(entry, dict) and entry.get("status") == "rejected":
            blocked.add(phase)
    return frozenset(blocked)


def waived_artifacts(workspace: Path) -> frozenset[str]:
    """Artifact filenames explicitly waived (see record_waiver)."""
    waived = read_state(workspace).get("waived", {})
    return frozenset(name for name in waived if isinstance(name, str))


def artifact_ready(workspace: Path, name: str) -> bool:
    """True if *name* is more than an empty/partial write.

    Deliberately narrow: missing or zero-byte -> not ready; a .json file must
    parse -> not ready if truncated/corrupt; anything else (binary artifacts
    like out.png/out.pdf/out.brd.docx) only needs to be non-empty. No magic-byte
    or minimum-size check, and no "is this JSON semantically non-trivial"
    check -- existing tests write trivially-small-but-VALID fixtures
    (tech_stack.json="[]", wbs.json="{}", out.brd.docx=b"x") and assert phase
    still advances; a stricter guard would both break those and, in
    production, risk yanking tools away from the model mid-run over a
    thin-but-real artifact. Semantic completeness is
    domain/validation/solution_validator.py's job, not this hot path's --
    _detect_phase runs on every model call (twice: tool filter + prompt filter).
    """
    path = Path(workspace) / name
    try:
        st = path.stat()
    except OSError:
        return False
    if st.st_size == 0:
        return False
    if not name.endswith(".json"):
        return True
    if st.st_size > 8_000_000:
        # Don't parse a pathological file in a per-model-call hot path; a file
        # this large is not the empty/truncated case this guard targets.
        return True
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return False
    return True
