"""``SandboxRunner`` — the interface every code-execution backend implements.

Originally diagram-only (``render_diagram`` was the sole caller); generalized
in the improvement plan's code-interpreter phase into the shared "run a
script, get declared files back" primitive every sandboxed-code tool uses —
``render_diagram`` is now just the first, back-compat caller that happens to
pass diagram filenames."""

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
        allowed_outputs: tuple[str, ...] | None = None,
    ) -> RenderResult:
        """Execute ``script_name`` (already written into ``workspace``) and
        leave ``workspace`` populated with whatever of ``allowed_outputs`` the
        run produced — every other file the script writes stays inside the
        sandbox (Modal) or is simply ignored by the caller (local dev) and
        never becomes part of the returned artifact set.

        ``allowed_outputs=None`` (the default) falls back to each runner's
        own diagram-render allowlist (``contracts.DEFAULT_DIAGRAM_OUTPUTS``)
        — existing callers that don't pass this keep their exact prior
        behavior. A new caller (e.g. a WBS-recompute or data-analysis tool)
        passes its own filenames (``result.json``, ``updated_wbs.json``, ...)
        instead.

        Every returned file is still run through
        ``artifact_validation.validate_artifact`` before it's trusted —
        format-level checks only (well-formed PNG/JSON/CSV/...); a caller
        that needs its output to match a specific *shape* (e.g. a Pydantic
        schema for ``result.json``) validates that itself after reading it
        back, on top of this.

        Must raise ``subprocess.TimeoutExpired`` if the script outlives
        *timeout* — callers (``tools.rendering_tools.render_diagram``) catch
        that specific exception to report a clean timeout message.
        """
        ...
