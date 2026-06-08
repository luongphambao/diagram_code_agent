"""Batch eval runner for the diagram agent.

Loads golden cases, runs the agent headlessly on each (up to max_concurrency
at once), scores with structural F1 + optional vision judge, prints a results
table and writes results.json.

Usage:
    cd backend
    uv run python -m evals.diagram.run_eval
    uv run python -m evals.diagram.run_eval --config evals/diagram/config.toml
    uv run python -m evals.diagram.run_eval --case dataset/case_01_aws_web_app.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

# Allow running from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from evals.diagram.judge import structural_f1, vision_judge
from evals.diagram.target import run_case
from diagram_mcp.agent import DEFAULT_MODEL

logger = logging.getLogger("eval.run")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")

_EVAL_DIR = Path(__file__).resolve().parent


def _load_config(config_path: str | None) -> dict:
    defaults = {
        "max_concurrency": 2,
        "score_modes": ["all_findings", "surfaced_findings"],
        "dataset_dir": "dataset",
        "judge_model": "gpt-4.1-mini",
        "diagram_style": "pretty",
        "vision_judge": True,
        "results_path": "results.json",
    }
    if config_path is None:
        return defaults
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-reattr]
        except ImportError:
            logger.warning("tomllib/tomli not available — using defaults")
            return defaults
    with open(config_path, "rb") as f:
        raw = tomllib.load(f)
    cfg = raw.get("eval", {})
    defaults.update(cfg)
    return defaults


def _load_cases(dataset_dir: Path, single_case: str | None) -> list[dict]:
    if single_case:
        return [json.loads(Path(single_case).read_text(encoding="utf-8"))]
    cases = []
    for p in sorted(dataset_dir.glob("*.json")):
        try:
            cases.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as exc:
            logger.warning("skipping %s: %s", p.name, exc)
    return cases


async def _run_one(case: dict, cfg: dict, tmp_root: Path) -> dict:
    case_id = case.get("id", "unknown")
    out_dir = tmp_root / case_id
    out_dir.mkdir(parents=True, exist_ok=True)

    model = os.getenv("DIAGRAM_AGENT_MODEL", DEFAULT_MODEL)
    logger.info("[%s] running target (model=%s style=%s)", case_id, model, cfg["diagram_style"])

    try:
        result = await run_case(
            case["prompt"],
            model=model,
            style=cfg["diagram_style"],
            out_dir=out_dir,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[%s] target failed: %s", case_id, exc)
        result = {"ok": False, "png_path": None, "blueprint": None,
                  "error": str(exc), "gate_names": []}

    # Layer 1: structural F1
    f1_scores = structural_f1(result.get("blueprint"), case)

    # Layer 2: vision judge (optional)
    vision_scores: dict = {}
    if cfg.get("vision_judge") and result.get("png_path"):
        context = f"Architecture for: {case['prompt'][:200]}"
        vision_scores = vision_judge(result["png_path"], context, cfg["judge_model"])

    entry = {
        "case_id": case_id,
        "prompt": case["prompt"][:100] + "...",
        "ok": result["ok"],
        "error": result.get("error"),
        "gate_names": result.get("gate_names", []),
        "structural": f1_scores,
        "vision": vision_scores,
    }
    logger.info(
        "[%s] micro_f1=%.3f  overall=%.2f  ok=%s",
        case_id,
        f1_scores.get("micro_f1", 0.0),
        vision_scores.get("overall", float("nan")),
        result["ok"],
    )
    return entry


async def _run_all(cases: list[dict], cfg: dict, tmp_root: Path) -> list[dict]:
    sem = asyncio.Semaphore(cfg["max_concurrency"])

    async def _bounded(case: dict) -> dict:
        async with sem:
            return await _run_one(case, cfg, tmp_root)

    return await asyncio.gather(*[_bounded(c) for c in cases])


def _print_table(results: list[dict]) -> None:
    header = f"{'case':<35} {'ok':>4} {'micro_f1':>9} {'node_f1':>8} {'edge_f1':>8} {'cluster_f1':>11} {'overall':>8}"
    print("\n" + header)
    print("-" * len(header))
    for r in results:
        s = r.get("structural", {})
        v = r.get("vision", {})
        print(
            f"{r['case_id']:<35} "
            f"{'Y' if r['ok'] else 'N':>4} "
            f"{s.get('micro_f1', 0.0):>9.3f} "
            f"{s.get('node_f1', 0.0):>8.3f} "
            f"{s.get('edge_f1', 0.0):>8.3f} "
            f"{s.get('cluster_f1', 0.0):>11.3f} "
            f"{v.get('overall', float('nan')):>8.2f}"
        )
    # Averages
    n = len(results)
    if n:
        avg_mf1 = sum(r.get("structural", {}).get("micro_f1", 0.0) for r in results) / n
        avg_ov = [r.get("vision", {}).get("overall") for r in results if r.get("vision", {}).get("overall") is not None]
        avg_ov_str = f"{sum(avg_ov)/len(avg_ov):.2f}" if avg_ov else " n/a"
        print("-" * len(header))
        print(f"{'AVERAGE':<35} {'':>4} {avg_mf1:>9.3f} {'':>8} {'':>8} {'':>11} {avg_ov_str:>8}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None,
                        help="Path to config.toml (default: evals/diagram/config.toml)")
    parser.add_argument("--case", default=None,
                        help="Run a single case JSON file instead of the full dataset.")
    args = parser.parse_args()

    config_path = args.config or str(_EVAL_DIR / "config.toml")
    cfg = _load_config(config_path if Path(config_path).exists() else None)

    dataset_dir = _EVAL_DIR / cfg["dataset_dir"]
    cases = _load_cases(dataset_dir, args.case)
    if not cases:
        logger.error("No eval cases found in %s", dataset_dir)
        sys.exit(1)
    logger.info("Running %d eval case(s) (concurrency=%d)", len(cases), cfg["max_concurrency"])

    with tempfile.TemporaryDirectory(prefix="diagram_eval_") as tmp:
        results = asyncio.run(_run_all(cases, cfg, Path(tmp)))

    _print_table(results)

    results_path = _EVAL_DIR / cfg["results_path"]
    results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    logger.info("Results written to %s", results_path)


if __name__ == "__main__":
    main()
