"""Headless target runner: runs the diagram agent on one eval case.

Gates (tech_stack / blueprint / finalize) are auto-approved so the run
completes without human input, producing ``out.png`` and ``blueprint.json``
that the judge evaluates.

Usage (called by run_eval.py, not usually directly):
    python -m evals.diagram.target --case dataset/case_01_aws_web_app.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Allow running from the backend/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from diagram_mcp.agent import DEFAULT_MODEL, RECURSION_LIMIT, build_agent
from diagram_mcp.backends import WORKSPACE
from diagram_mcp.tools import clear_stage_markers, GATE_TOOL_NAMES

logger = logging.getLogger("eval.target")
logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")


async def _get_pending_interrupt(agent, config: dict):
    try:
        st = await agent.aget_state(config)
    except Exception:
        return None
    for task in getattr(st, "tasks", None) or []:
        for intr in getattr(task, "interrupts", None) or []:
            return getattr(intr, "value", intr)
    for intr in getattr(st, "interrupts", None) or []:
        return getattr(intr, "value", intr)
    return None


def _pending_name(val) -> str | None:
    if isinstance(val, dict):
        ars = val.get("action_requests") or []
        if ars:
            return ars[0].get("name")
    return None


async def run_case(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    style: str = "pretty",
    out_dir: Path | None = None,
    max_gate_resumes: int = 12,
) -> dict:
    """Run the agent on ``prompt`` with all gates auto-approved.

    Returns a dict with keys:
        ok          — True if out.png was produced.
        png_path    — Path to rendered PNG (or None).
        blueprint   — Blueprint dict (or None).
        error       — Error string if run failed.
        gate_names  — List of gate names that were auto-approved.
    """
    if out_dir is None:
        out_dir = WORKSPACE
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    clear_stage_markers()
    agent = build_agent(model=model, style=style)
    thread_id = f"eval-{os.getpid()}-{id(agent)}"
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": RECURSION_LIMIT,
        "run_name": "eval-run",
    }

    gate_names: list[str] = []
    resumes = 0

    # Initial run.
    async for _ in agent.astream(
        {"messages": [HumanMessage(content=prompt)]},
        config,
        stream_mode=["updates"],
    ):
        pass

    # Auto-approve gates until the run finishes or we hit the cap.
    while resumes < max_gate_resumes:
        val = await _get_pending_interrupt(agent, config)
        if val is None:
            break
        name = _pending_name(val)
        if name not in GATE_TOOL_NAMES:
            break
        gate_names.append(name or "unknown")
        logger.info("auto-approve gate: %s", name)
        async for _ in agent.astream(
            Command(resume={"decisions": [{"type": "approve"}]}),
            config,
            stream_mode=["updates"],
        ):
            pass
        resumes += 1

    # Collect artifacts.
    png = out_dir / "out.png"
    bp_file = out_dir / "blueprint.json"
    blueprint = None
    if bp_file.exists():
        try:
            blueprint = json.loads(bp_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "ok": png.exists(),
        "png_path": str(png) if png.exists() else None,
        "blueprint": blueprint,
        "error": None if png.exists() else "out.png not produced",
        "gate_names": gate_names,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, help="Path to a golden case JSON file.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--style", default="pretty")
    args = parser.parse_args()

    case = json.loads(Path(args.case).read_text(encoding="utf-8"))
    result = asyncio.run(run_case(case["prompt"], model=args.model, style=args.style))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
