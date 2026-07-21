"""``SandboxRunner`` — the interface every render-execution backend implements."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..contracts import RenderResult


@runtime_checkable
class SandboxRunner(Protocol):
    def render(
        self,
        workspace: Path,
        *,
        timeout: int,
        script_name: str = "diagram.py",
    ) -> RenderResult:
        """Execute ``script_name`` (already written into ``workspace``) and
        leave ``workspace`` populated with whatever output files the run
        produced (subject to each runner's own allowlist).

        Must raise ``subprocess.TimeoutExpired`` if the script outlives
        *timeout* — callers (``tools.rendering_tools.render_diagram``) catch
        that specific exception to report a clean timeout message.
        """
        ...
