"""Subprocess execution of a rendered diagram script.

Extracted from ``tools.rendering_tools.render_diagram`` so the exec boundary
is a single, small, independently-testable function. See the package
docstring (``runtime/sandbox/__init__.py``) for the current threat model.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_render(
    workspace: Path,
    *,
    timeout: int,
    script_name: str = "diagram.py",
) -> subprocess.CompletedProcess:
    """Run ``script_name`` (already written into ``workspace``) with the current
    Python interpreter and capture its output.

    A plain subprocess — same interpreter, no OS-level isolation. Raises
    ``subprocess.TimeoutExpired`` if the process outlives *timeout*; the
    caller decides how to report that (render_diagram turns it into a
    ToolMessage instead of propagating the exception).
    """
    return subprocess.run(
        [sys.executable, script_name],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
