"""Persistent quality logging for diagram generation runs.

Writes to backend/logs/:
  diagram-agent.log        — Rotating text log (10MB × 5 backups)
  quality.jsonl            — Append-only JSONL, one event per line (easy tail/grep)
  runs/<ts>_<id>.json      — Per-run quality summary JSON

Usage in async code:
    from .quality_logger import QualityRun, set_current_run, get_current_run

    run = QualityRun(run_id=run_id, style=style, description=desc)
    token = set_current_run(run)
    try:
        ...
    finally:
        run.run_end()
        set_current_run(None)

Tools call get_current_run() and log against the active run — silently a no-op
if no run is active (e.g. during evals or unit tests).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backends import _BACKEND_ROOT

LOGS_DIR = _BACKEND_ROOT / "logs"
RUNS_DIR = LOGS_DIR / "runs"

_qjsonl_lock = threading.Lock()
_log = logging.getLogger("diagram.quality")


def _ensure_log_dirs() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def setup_file_logging() -> None:
    """Attach a rotating file handler to the root logger.

    Call once at server startup (after logging.basicConfig has already
    configured the stream handler).
    """
    _ensure_log_dirs()
    log_file = LOGS_DIR / "diagram-agent.log"
    fh = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB per file
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)-24s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    fh.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(fh)
    _log.info("File logging active → %s", log_file)


def _append_event(event: dict) -> None:
    """Append one JSONL line to quality.jsonl. Never raises."""
    try:
        with _qjsonl_lock:
            with (LOGS_DIR / "quality.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, default=str) + "\n")
    except Exception:
        pass


@dataclass
class QualityRun:
    run_id: str
    style: str
    description: str
    _started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    _renders: list[dict] = field(default_factory=list)
    _critique: dict | None = field(default=None)
    _layout_audit: str = field(default="")
    _final_verdict: str = field(default="")
    _drawer_iterations: int = field(default=0)
    _mcp_used: bool = field(default=False)

    # -------------------------------------------------------------------
    # Tool-facing logging methods
    # -------------------------------------------------------------------

    def render_attempt(self, attempt: int, success: bool, error: str | None = None) -> None:
        self._drawer_iterations = max(self._drawer_iterations, attempt)
        entry: dict = {"attempt": attempt, "success": success}
        if error:
            entry["error"] = error[:300]
        self._renders.append(entry)
        if success:
            _log.info("[%s] render #%d  OK", self.run_id[:8], attempt)
            _append_event({"run_id": self.run_id, "event": "render_ok", "attempt": attempt})
        else:
            _log.error("[%s] render #%d  FAILED: %s", self.run_id[:8], attempt, (error or "")[:200])
            _append_event({"run_id": self.run_id, "event": "render_fail", "attempt": attempt, "error": error})

    def inspect_called(self, audit_text: str) -> None:
        self._layout_audit = audit_text or ""
        if audit_text:
            _log.info("[%s] layout_audit: %s", self.run_id[:8], audit_text[:300])
        _append_event({
            "run_id": self.run_id,
            "event": "inspect",
            "audit": audit_text[:500] if audit_text else "",
        })

    def critique_submitted(self, findings: list[Any], verdict: str) -> None:
        severities: dict[str, int] = {}
        categories: list[str] = []
        for f in findings:
            if isinstance(f, dict):
                sev = f.get("severity", "")
                cat = f.get("category", "")
            else:
                sev = getattr(f, "severity", "")
                cat = getattr(f, "category", "")
            if sev:
                severities[sev] = severities.get(sev, 0) + 1
            if cat and cat not in categories:
                categories.append(cat)

        self._critique = {
            "total_findings": len(findings),
            "verdict": verdict.strip()[:30],
            "severities": severities,
            "categories": categories,
        }
        is_revise = "REVISE" in verdict.upper()
        log_fn = _log.warning if is_revise else _log.info
        log_fn(
            "[%s] critique  verdict=%s  findings=%d  severities=%s  categories=%s",
            self.run_id[:8],
            "REVISE" if is_revise else "PASS",
            len(findings),
            severities,
            categories,
        )
        _append_event({
            "run_id": self.run_id,
            "event": "critique",
            "verdict": "REVISE" if is_revise else "PASS",
            "total_findings": len(findings),
            "severities": severities,
            "categories": categories,
        })

    def mcp_not_used(self, path: str = "export_drawio") -> None:
        """Log that a code path skipped MCP and used the local converter instead."""
        _log.warning(
            "[%s] MCP drawio NOT used in %s — using local converter "
            "(mcp_client.py is defined but never called in the pipeline)",
            self.run_id[:8], path,
        )
        _append_event({
            "run_id": self.run_id,
            "event": "mcp_not_used",
            "path": path,
            "note": "mcp_client.py exists but is not integrated into the pipeline",
        })

    def mark_mcp_used(self, tool_names: list[str]) -> None:
        self._mcp_used = True
        _log.info("[%s] MCP tools used: %s", self.run_id[:8], tool_names)
        _append_event({"run_id": self.run_id, "event": "mcp_used", "tools": tool_names})

    def run_end(self, final_verdict: str = "") -> None:
        self._final_verdict = final_verdict
        ended = datetime.now(timezone.utc).isoformat()
        summary = {
            "run_id": self.run_id,
            "started_at": self._started_at,
            "ended_at": ended,
            "style": self.style,
            "description": self.description[:200],
            "drawer_iterations": self._drawer_iterations,
            "renders": self._renders,
            "critique": self._critique,
            "layout_audit": self._layout_audit[:500] if self._layout_audit else "",
            "mcp_used": self._mcp_used,
            "final_verdict": self._final_verdict or "unknown",
        }
        try:
            ts = self._started_at[:19].replace("T", "_").replace(":", "-")
            run_file = RUNS_DIR / f"{ts}_{self.run_id[:8]}.json"
            run_file.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
            _log.info("[%s] quality summary → %s", self.run_id[:8], run_file.name)
        except Exception as exc:
            _log.warning("[%s] could not write run summary: %s", self.run_id[:8], exc)

        verdict_tag = (
            "PASS" if "PASS" in final_verdict.upper()
            else "REVISE" if "REVISE" in final_verdict.upper()
            else "DONE"
        )
        _log.info(
            "[%s] run ended  verdict=%s  renders=%d  mcp_used=%s",
            self.run_id[:8], verdict_tag, len(self._renders), self._mcp_used,
        )
        _append_event({
            "run_id": self.run_id,
            "event": "run_end",
            "verdict": verdict_tag,
            "total_renders": len(self._renders),
            "mcp_used": self._mcp_used,
        })


# ---------------------------------------------------------------------------
# ContextVar — propagates through asyncio tasks so subagent tool calls
# automatically see the active run without requiring explicit passing.
# ---------------------------------------------------------------------------

_current_run: ContextVar[QualityRun | None] = ContextVar("current_quality_run", default=None)


def get_current_run() -> QualityRun | None:
    return _current_run.get()


def set_current_run(run: QualityRun | None) -> Any:
    """Set the active run; returns a token for reset (optional)."""
    return _current_run.set(run)
