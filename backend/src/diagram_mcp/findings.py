"""Structured findings for the diagram **critic** subagent.

A critic looks at the rendered PNG (+ the layout audit) and the approved
blueprint, then files a small set of concrete, observable defects. This module
owns the `DiagramFinding` schema, the caps/validators that keep findings terse,
and the helpers that turn a batch of findings into a short verdict the main
agent can act on.

Design mirrors open-swe's `reviewer_findings.py`: a structured record with a
severity/confidence ladder, a hard cap, title/suggestion clipping, and a
deterministic verdict derived from the findings (so the critic can't hand-wave
"looks good" past a real defect).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Severity = Literal["low", "medium", "high", "critical"]
Confidence = Literal["low", "medium", "high"]
Category = Literal["layout", "completeness", "correctness", "readability", "style", "pillar_gap"]

# Ordering for ranking/pruning (higher = more serious).
_SEVERITY_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_CONFIDENCE_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}

# A finding at or above this severity, when it is in-blueprint scope, forces a
# revise verdict (the diagram goes back to the drawer).
BLOCKING_SEVERITY = "medium"

# Keep only the strongest few. A wall of nits reads as noise and the drawer
# can't act on it. (open-swe caps reviewer output the same way.)
MAX_FINDINGS = 5

# Suggestions must be glanceable, not a rewrite of the diagram.
MAX_SUGGESTION_LINES = 4
MAX_TITLE_LENGTH = 120


class DiagramFinding(BaseModel):
    """One concrete, observable defect in the rendered diagram."""

    severity: Severity = Field(
        description="critical=render fails / topology wrong; high=a major "
        "component or edge from the blueprint is missing/wrong; "
        "medium=layout hurts readability (crossing/long edges, cramped strip); "
        "low=small misalignment with limited impact",
    )
    confidence: Confidence = Field(
        description="how sure you are this is a real defect you can see, not a guess",
    )
    category: Category = Field(
        description="layout|completeness|correctness|readability|style",
    )
    title: str = Field(
        description="names the defect in ~4-10 words; do not copy the detail",
    )
    detail: str = Field(
        description="what is wrong and WHERE — name the node/edge/cluster you see "
        "(or that is missing). Concrete and anchored to the PNG/blueprint.",
    )
    fix_suggestion: Optional[str] = Field(
        default=None, description="the one concrete fix, ≤4 lines, or omit"
    )
    in_blueprint: bool = Field(
        default=True,
        description="False if this is OUTSIDE the approved blueprint's scope "
        "(surfaced for awareness, does NOT block finalize)",
    )

    @field_validator("title")
    @classmethod
    def _clip_title(cls, v: str) -> str:
        compact = " ".join((v or "").split())
        if not compact:
            return "Diagram finding"
        if len(compact) > MAX_TITLE_LENGTH:
            return f"{compact[: MAX_TITLE_LENGTH - 3].rstrip()}..."
        return compact

    @field_validator("fix_suggestion")
    @classmethod
    def _clip_suggestion(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        # Drop overly long suggestions — the detail still carries the message.
        if v.count("\n") + 1 > MAX_SUGGESTION_LINES:
            return None
        return v.strip()


# Resolve the Literal forward refs now (we use `from __future__ import annotations`)
# so any schema problem surfaces at import time, not at first validation.
DiagramFinding.model_rebuild()


def _rank_key(f: DiagramFinding) -> tuple[int, int, int]:
    """Sort blocking, then by severity, then confidence — strongest first."""
    return (
        1 if (f.in_blueprint and is_blocking(f)) else 0,
        _SEVERITY_ORDER[f.severity],
        _CONFIDENCE_ORDER[f.confidence],
    )


def is_blocking(f: DiagramFinding) -> bool:
    """A finding blocks finalize when it is at/above BLOCKING_SEVERITY."""
    return _SEVERITY_ORDER[f.severity] >= _SEVERITY_ORDER[BLOCKING_SEVERITY]


def prune(findings: list[DiagramFinding]) -> list[DiagramFinding]:
    """Rank and keep only the strongest MAX_FINDINGS."""
    return sorted(findings, key=_rank_key, reverse=True)[:MAX_FINDINGS]


def verdict_for(findings: list[DiagramFinding]) -> str:
    """`"revise"` if any in-blueprint finding is blocking, else `"pass"`."""
    if any(f.in_blueprint and is_blocking(f) for f in findings):
        return "revise"
    return "pass"


def format_critique(findings: list[DiagramFinding]) -> str:
    """Render a short, deterministic verdict + finding list for the main agent.

    The first line is machine-greppable (`VERDICT: PASS|REVISE`) so the staged
    flow can branch on it without parsing JSON.
    """
    kept = prune(findings)
    verdict = verdict_for(kept)
    blocking = [f for f in kept if f.in_blueprint and is_blocking(f)]
    out_of_scope = [f for f in kept if not f.in_blueprint]
    in_scope = [f for f in kept if f.in_blueprint]

    if verdict == "pass" and not kept:
        header = "VERDICT: PASS (no findings — diagram is clean, proceed to finalize)"
    elif verdict == "pass":
        header = (
            f"VERDICT: PASS ({len(in_scope)} minor finding(s), none blocking — "
            "proceed to finalize)"
        )
    else:
        header = (
            f"VERDICT: REVISE ({len(blocking)} blocking finding(s) — send these "
            "back to the drawer, then re-critique)"
        )

    lines = [header]
    for f in kept:
        scope = "" if f.in_blueprint else " [out-of-blueprint]"
        line = f"- [{f.severity}/{f.category}]{scope} {f.title}: {f.detail}"
        if f.fix_suggestion:
            line += f" — fix: {f.fix_suggestion}"
        lines.append(line)
    if out_of_scope:
        lines.append(
            "(out-of-blueprint findings are for awareness only and do NOT block finalize)"
        )
    return "\n".join(lines)
