"""Sandboxed code-interpreter tool (improvement plan §C).

Lets an agent run agent-authored Python inside the SAME isolated sandbox
``render_diagram`` uses (``SandboxRunner``: ``block_network=True``,
``secrets=[]``, fresh sandbox per call, resource limits, post-run artifact
validation) to TRANSFORM a structured file precisely — e.g. re-estimating a
WBS ("drop FE/Mobile, remove the Solution Design module, scale AI effort
×0.7") — instead of the LLM retyping every leaf number in-prompt, which is
exactly how these edits are silently miscounted today (see
``domain.wbs.wbs_tools``'s docstrings — there is no edit/adjust tool; any
change means re-emitting the entire item list by hand).

Attached to the main agent AND wbs_planner (improvement plan §C: S1 was
wbs_planner-only for WBS re-estimation; §C-S2 added the main agent for
general analysis of uploaded tabular data — e.g. "tổng ngân sách theo phòng
ban" from an uploaded .xlsx — which has nothing to do with WBS). Both share
the same per-thread call budget (``INTERPRETER_CALL_HARD_CAP``) since
``current_workspace()`` resolves to the same thread workspace regardless of
which agent calls this tool.

"Transform, not derive" (the improvement plan's safety principle): this tool
only lets code reshape EXISTING data (filter/scale/aggregate rows and
columns already in the workspace). It is never the source of truth for a
DERIVED number — a domain-specific "commit" tool (e.g.
``domain.wbs.wbs_tools.apply_wbs_reestimate``) re-runs the SAME deterministic
recompute chain a hand-typed edit already goes through, so a code-interpreter
run can never silently drift from the one true computation. Do not wire this
tool's raw output straight into anything currency/effort/timeline-facing
without going through that kind of commit step.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool

from backends import current_workspace
from observability import new_id, reset_context, set_context
from runtime.sandbox.provider import get_sandbox_runner
from .constants import INTERPRETER_CALL_HARD_CAP, INTERPRETER_TIMEOUT_S, _INTERPRETER_COUNT_FILE
from .stage_markers import _bump_tool_summary, _read_json_file, _write_json_file

logger = logging.getLogger("diagram-agent")

_SCRIPT_NAME = "interpreter_script.py"


def _interpreter_count() -> int:
    return int(_read_json_file(_INTERPRETER_COUNT_FILE, {"count": 0}).get("count", 0))


def _bump_interpreter_count() -> int:
    n = _interpreter_count() + 1
    _write_json_file(_INTERPRETER_COUNT_FILE, {"count": n})
    _bump_tool_summary("run_python", interpreter_attempts=n)
    return n


@tool(parse_docstring=True)
def run_python(
    code: str,
    declared_outputs: list[str],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> ToolMessage:
    """Run Python code in an isolated sandbox and retrieve back declared output files.

    Same isolation as diagram rendering: no network access, no application
    secrets, a fresh sandbox for every call, resource/time limits. The code
    can read any file already in this workspace (e.g. wbs.json,
    tech_stack.json, an uploaded spreadsheet) via plain `open(...)`/relative
    paths — do not try to read files by absolute host path.

    IMPORTANT — do not overwrite an existing input file in place: if you are
    transforming wbs.json, write the result to a NEW filename (e.g.
    wbs_reestimated.json) and list that new name in declared_outputs, not
    "wbs.json" itself. Declaring an existing file as an output means it is
    treated as this run's fresh product, not read as input.

    Use this to TRANSFORM structured data precisely — filter/drop rows or
    columns, scale numeric fields, aggregate a table — rather than retyping
    numbers by hand. This tool does not validate the MEANING of what you
    wrote, only that declared files exist and are well-formed for their
    type; for wbs.json edits, call apply_wbs_reestimate afterward with the
    new filename so the same deterministic recompute chain every WBS edit
    goes through re-derives every downstream number from your transformed
    inputs — never treat this tool's raw output as final numbers.

    Args:
        code: Complete Python source to execute. Standard library only
            unless the sandbox image provides more — do not assume network
            access or pip install works (both are blocked).
        declared_outputs: Filenames (relative, no path separators) this call
            should retrieve after the script runs. Any other file the script
            writes is discarded.
    """
    if _interpreter_count() >= INTERPRETER_CALL_HARD_CAP:
        return ToolMessage(
            content=(
                f"CODE-INTERPRETER BUDGET EXHAUSTED ({INTERPRETER_CALL_HARD_CAP} calls this "
                "round). Work with what you already have instead of retrying."
            ),
            name="run_python",
            tool_call_id=tool_call_id,
            status="error",
        )
    attempt = _bump_interpreter_count()

    ws = current_workspace()
    (ws / _SCRIPT_NAME).write_text(code, encoding="utf-8")

    job_id = new_id()
    _ctx_token = set_context(render_job_id=job_id)
    started = time.monotonic()
    try:
        try:
            result = get_sandbox_runner().render(
                ws,
                timeout=INTERPRETER_TIMEOUT_S,
                script_name=_SCRIPT_NAME,
                allowed_outputs=tuple(declared_outputs),
            )
        except Exception as exc:  # noqa: BLE001 — timeout, artifact validation, sandbox errors
            logger.warning(
                "run_python #%d failed after %.1fs: %s",
                attempt,
                time.monotonic() - started,
                exc,
            )
            return ToolMessage(
                content=f"run_python #{attempt}/{INTERPRETER_CALL_HARD_CAP} failed: {exc}",
                name="run_python",
                tool_call_id=tool_call_id,
                status="error",
            )

        duration = time.monotonic() - started
        produced = [name for name in declared_outputs if (ws / name).exists()]
        missing = [name for name in declared_outputs if name not in produced]
        logger.info(
            "run_python #%d succeeded duration=%.1fs exit=%s produced=%s",
            attempt,
            duration,
            result.returncode,
            produced,
        )
    finally:
        reset_context(_ctx_token)

    lines = [
        f"run_python #{attempt}/{INTERPRETER_CALL_HARD_CAP} finished (exit {result.returncode}, "
        f"{duration:.1f}s)."
    ]
    if produced:
        lines.append(f"Produced: {', '.join(produced)}")
    if missing:
        lines.append(f"NOT produced (check the script — declared but missing): {', '.join(missing)}")
    if result.stdout.strip():
        lines.append(f"stdout:\n{result.stdout.strip()[-2000:]}")
    if result.returncode != 0 and result.stderr.strip():
        lines.append(f"stderr:\n{result.stderr.strip()[-2000:]}")

    return ToolMessage(
        content="\n\n".join(lines),
        name="run_python",
        tool_call_id=tool_call_id,
        status="success" if result.returncode == 0 else "error",
    )
