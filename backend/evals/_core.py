"""Shared eval-harness core (docx §4.5, §10 "Eval harness").

The diagram suite (`evals/diagram/`) established the pattern: load golden cases →
run a target → score with a judge → print a table → write `results.json`. The
product plan wants the *same* pattern for intake / architecture / WBS plus a
**regression gate** so "no prompt/model change ships without an eval artifact".

This module factors the reusable pieces out of `evals/diagram/run_eval.py` so each
new suite is thin. The deterministic matcher (`soft_match`/`f1`/`normalize`) is
re-exported from `evals.diagram.judge` so all suites agree on what "covered" means.
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Optional

# Re-export the one deterministic matcher every suite shares (single source of truth).
from evals.diagram.judge import _f1 as f1            # noqa: F401
from evals.diagram.judge import _normalize as normalize  # noqa: F401
from evals.diagram.judge import _soft_match as soft_match  # noqa: F401


# --- case loading ------------------------------------------------------------

def load_cases(dataset_dir: Path, single_case: Optional[str] = None) -> list[dict]:
    """Load every `*.json` golden case in `dataset_dir`, or a single named file."""
    if single_case:
        return [json.loads(Path(single_case).read_text(encoding="utf-8"))]
    cases: list[dict] = []
    for p in sorted(Path(dataset_dir).glob("*.json")):
        try:
            cases.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return cases


# --- concurrency -------------------------------------------------------------

async def run_all(
    cases: list[dict],
    fn: Callable[[dict], Awaitable[dict]],
    *,
    max_concurrency: int = 2,
) -> list[dict]:
    """Run `fn(case)` over all cases, at most `max_concurrency` at a time."""
    sem = asyncio.Semaphore(max_concurrency)

    async def _bounded(case: dict) -> dict:
        async with sem:
            return await fn(case)

    return await asyncio.gather(*[_bounded(c) for c in cases])


def run_all_sync(cases: list[dict], fn: Callable[[dict], dict]) -> list[dict]:
    """Synchronous variant for purely deterministic suites (no agent I/O)."""
    return [fn(c) for c in cases]


# --- reporting ---------------------------------------------------------------

def print_table(results: list[dict], columns: list[tuple[str, str]]) -> None:
    """Print a results table. `columns` is a list of (key, header) pairs; nested
    keys use dotted paths (e.g. "scores.micro_f1")."""
    widths = [max(len(h), 12) for _, h in columns]
    header = "  ".join(f"{h:<{w}}" for (_, h), w in zip(columns, widths))
    print("\n" + header)
    print("-" * len(header))
    for r in results:
        cells = []
        for (key, _), w in zip(columns, widths):
            val = _dig(r, key)
            cells.append(f"{_fmt(val):<{w}}")
        print("  ".join(cells))
    print()


def _dig(obj: dict, dotted: str) -> Any:
    cur: Any = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _fmt(val: Any) -> str:
    if isinstance(val, float):
        return f"{val:.3f}"
    if isinstance(val, bool):
        return "Y" if val else "N"
    if val is None:
        return "-"
    return str(val)[:12]


def write_results(path: Path, results: list[dict]) -> None:
    Path(path).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")


# --- regression gate ---------------------------------------------------------

def aggregate(results: list[dict], metric_keys: Iterable[str]) -> dict[str, float]:
    """Mean of each (dotted) metric across cases, ignoring missing/NaN values."""
    out: dict[str, float] = {}
    for key in metric_keys:
        vals = [_dig(r, key) for r in results]
        nums = [v for v in vals if isinstance(v, (int, float)) and not math.isnan(float(v))]
        if nums:
            out[key] = sum(nums) / len(nums)
    return out


def compare_to_baseline(
    results: list[dict],
    baseline_path: Path,
    metric_keys: Iterable[str],
    *,
    tolerance: float = 0.02,
) -> tuple[bool, list[dict]]:
    """The regression gate. Compare aggregated metrics to a committed baseline.

    Returns `(passed, regressions)`. A metric regresses when its current mean drops
    below `baseline - tolerance`. If no baseline exists yet, passes (and the caller
    can write the current run as the new baseline).
    """
    metric_keys = list(metric_keys)
    current = aggregate(results, metric_keys)
    baseline_path = Path(baseline_path)
    if not baseline_path.exists():
        return True, []
    prior = json.loads(baseline_path.read_text(encoding="utf-8")).get("metrics", {})
    regressions: list[dict] = []
    for key in metric_keys:
        if key not in prior or key not in current:
            continue
        if current[key] < prior[key] - tolerance:
            regressions.append({
                "metric": key,
                "baseline": round(prior[key], 4),
                "current": round(current[key], 4),
                "drop": round(prior[key] - current[key], 4),
            })
    return (len(regressions) == 0), regressions


def write_baseline(path: Path, results: list[dict], metric_keys: Iterable[str]) -> None:
    """Write the current aggregated metrics as the committed baseline."""
    payload = {"metrics": aggregate(results, list(metric_keys)), "n_cases": len(results)}
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
