"""Loop harness for iterative poster-style diagram improvement.

Usage:
    python3 loop_runner.py --md high_level_architecture.md --tag round1-baseline
    python3 loop_runner.py --md high_level_architecture.md --tag round2 --model gpt-4.1-mini
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

# Allow running from backend/ or backend/evals/diagram/.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[1] / "src"))

from dotenv import load_dotenv

load_dotenv()
load_dotenv(_HERE.parents[1] / ".env")

from diagram_mcp.agent import DEFAULT_MODEL
from diagram_mcp.backends import WORKSPACE
from diagram_mcp.prettygraph import audit_layout

from target import run_case

_RUNS_DIR = _HERE / "loop_runs"

_ARTIFACTS = [
    "out.png",
    "out.dot",
    "out.drawio",
    "diagram.py",
    "blueprint.json",
    "critique.json",
    "style_plan.json",
    "tool_budget_summary.json",
    "render_count.json",
    "out.nodes.json",
    "out.slide.json",
]

_PROMPT_TEMPLATE = """\
Vẽ production architecture diagram poster-style từ tài liệu kiến trúc sau.

Yêu cầu:
- Output: poster 2 hàng × 4-5 cột numbered sections, ~25-40 node
- Mỗi section tô màu accent riêng, có sub-groups lồng nhau nếu cần
- Icon thật cho mọi node chính, edge có nhãn ngắn
- Aspect 1.2-2.2

---
{md_content}
"""


def _read_critique(run_dir: Path) -> tuple[str, list]:
    path = run_dir / "critique.json"
    if not path.exists():
        return "N/A", []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        verdict = data.get("verdict", "N/A")
        findings = data.get("findings", [])
        return verdict, findings
    except Exception:
        return "ERROR", []


def _read_budget(run_dir: Path) -> dict:
    summary_path = run_dir / "tool_budget_summary.json"
    render_path = run_dir / "render_count.json"
    budget = {}
    if summary_path.exists():
        try:
            budget.update(json.loads(summary_path.read_text(encoding="utf-8")))
        except Exception:
            pass
    if render_path.exists():
        try:
            rc = json.loads(render_path.read_text(encoding="utf-8"))
            budget["render_count"] = rc.get("count", "?")
        except Exception:
            pass
    return budget


def _copy_artifacts(tag: str) -> Path:
    run_dir = _RUNS_DIR / tag
    run_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in _ARTIFACTS:
        src = WORKSPACE / name
        if src.exists():
            shutil.copy2(src, run_dir / name)
            copied.append(name)
    return run_dir, copied


def _run_layout_audit(run_dir: Path) -> str:
    dot = run_dir / "out.dot"
    png = run_dir / "out.png"
    if not dot.exists():
        return "out.dot not found — skipping layout audit"
    return audit_layout(str(dot), str(png) if png.exists() else None) or "OK (no issues)"


def _print_summary(tag: str, result: dict, run_dir: Path, layout: str, verdict: str, findings: list, budget: dict) -> None:
    print("\n" + "=" * 60)
    print(f"  LOOP RUN: {tag}")
    print("=" * 60)
    print(f"  Status  : {'OK' if result['ok'] else 'FAILED'}")
    if result.get("error"):
        print(f"  Error   : {result['error']}")
    if result["ok"]:
        print(f"  PNG     : {run_dir / 'out.png'}")
    print(f"  Gates   : {', '.join(result.get('gate_names', [])) or 'none'}")
    print()
    print(f"  Critic  : {verdict}")
    if findings:
        for f in findings[:5]:
            sev = f.get("severity", "?")
            msg = f.get("message") or f.get("description") or str(f)
            print(f"    [{sev}] {msg}")
        if len(findings) > 5:
            print(f"    ... +{len(findings) - 5} more")
    print()
    print("  Layout audit:")
    for line in layout.splitlines():
        print(f"    {line}")
    print()
    print("  Budget:")
    render_count = budget.pop("render_count", "?")
    print(f"    render_count : {render_count}")
    tool_counts = budget.pop("tool_counts", {})
    if tool_counts:
        for tool, count in sorted(tool_counts.items()):
            print(f"    {tool:<30} : {count}")
    for k, v in budget.items():
        print(f"    {k:<30} : {v}")
    print()
    print(f"  Artifacts in: {run_dir}")
    print("=" * 60 + "\n")


async def _main(md_path: str, tag: str, model: str) -> None:
    md = Path(md_path).read_text(encoding="utf-8")
    if len(md) > 50_000:
        print(f"[loop_runner] Warning: md truncated from {len(md)} to 50000 chars")
        md = md[:50_000]

    prompt = _PROMPT_TEMPLATE.format(md_content=md)
    print(f"[loop_runner] Starting run: tag={tag} model={model} md_chars={len(md)}")

    result = await run_case(prompt, model=model, style="pretty")

    run_dir, copied = _copy_artifacts(tag)
    print(f"[loop_runner] Copied artifacts: {copied}")

    layout = _run_layout_audit(run_dir)
    verdict, findings = _read_critique(run_dir)
    budget = _read_budget(run_dir)

    _print_summary(tag, result, run_dir, layout, verdict, findings, budget)


def main() -> None:
    parser = argparse.ArgumentParser(description="Iterative diagram improve-loop runner")
    parser.add_argument("--md", required=True, help="Path to architecture .md file")
    parser.add_argument("--tag", required=True, help="Run tag, e.g. round1-baseline")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="LLM model override")
    args = parser.parse_args()

    asyncio.run(_main(args.md, args.tag, args.model))


if __name__ == "__main__":
    main()
