"""Contracts for the diagram-render sandbox seam (improvement plan §0.1).

Deliberately smaller than a full byte-in/byte-out request/response model:
``tools/rendering_tools.py`` and its downstream helpers (``export_drawio``,
``_layout_audit``, ``_inspection_image_b64``, ``record_artifact_inventory``,
``_archive_session``, ...) all read and write named files (``out.png``,
``out.dot``, ...) directly against the per-thread *local* workspace. Reworking
every one of those call sites onto an in-memory request/response object would
be a much larger blast radius than the actual security goal — isolating
*execution* — requires.

Instead, a :class:`~runtime.sandbox.runners.base.SandboxRunner` keeps the
existing file-based contract: it is handed the *local* workspace directory
(already containing ``diagram.py`` plus any assets the script needs — the
staged ``prettygraph`` package, resolved icon/logo files, ...) and is
expected to leave that same directory populated with the render's output
files when it returns, whether execution happened in-process (the dev
runner) or in a remote Modal Sandbox (whose runner uploads the workspace,
executes remotely, and downloads back only the allowlisted outputs — see
``runners/modal_runner.py``).

Callers only ever read ``.returncode`` / ``.stdout`` / ``.stderr`` off the
result (see ``tools/rendering_tools.py``'s ``render_diagram``), so
``RenderResult`` below is a minimal drop-in for
``subprocess.CompletedProcess``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RenderLimits:
    """Resource ceilings enforced by whichever runner executes the script.

    Every field has an explicit production default per the improvement
    plan's security requirements — nothing here should be left to a
    provider's own default.
    """

    command_timeout_seconds: int = 180
    sandbox_idle_timeout_seconds: int = 20
    cpu_cores: float = 1.0
    memory_mib: int = 1024
    max_source_bytes: int = 256_000
    max_log_bytes: int = 256_000
    max_artifact_bytes: int = 25_000_000
    max_total_artifact_bytes: int = 50_000_000


@dataclass(frozen=True)
class RenderResult:
    """Minimal, ``subprocess.CompletedProcess``-compatible render result."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    sandbox_id: str | None = None
