"""Modal Sandbox runner (improvement plan §0.1 / Modal Sandbox decision).

Executes agent-generated Python in an isolated, ephemeral Modal Sandbox with
outbound networking blocked and no application secret in its environment —
closing the gap the local runner (see ``local_dev_runner.py`` and
``runtime/sandbox/__init__.py``'s threat-model docstring) cannot: real
OS-level isolation, not just a scrubbed environment.

Originally diagram-only (a fixed ``diagram.py`` in, ``out.png``/``out.dot``/
``out.drawio`` out). Generalized in the improvement plan's code-interpreter
phase (§B/§C) into a general "run this script, get these declared files
back" primitive: ``render_diagram`` (``tools/rendering_tools.py``) remains
one caller, passing its own diagram-output filenames; other tools (WBS
re-estimation, data-analysis) pass their own via ``allowed_outputs``.

Unlike ``LocalDevRunner`` (which runs *in* the local per-thread workspace
and needs no file transfer), ``render()`` here:

  1. uploads every file already staged into ``workspace`` (the script, plus
     whatever input data the caller staged there — the ``prettygraph/``
     package + resolved icon/logo assets for a diagram render, or e.g. an
     uploaded ``.xlsx``/``wbs.json`` for a data-analysis run) into a fresh
     sandbox's filesystem,
  2. runs the script inside the sandbox with ``block_network=True``,
     ``secrets=[]``, and explicit CPU/memory/timeout limits,
  3. downloads back only ``allowed_outputs`` into the SAME local workspace
     path, running each through ``artifact_validation.validate_artifact``
     before it is trusted (format-level checks only — a caller needing a
     specific *shape*, e.g. a Pydantic schema for a JSON result, validates
     that itself after reading the file back),
  4. always terminates the sandbox, even on error — no sandbox is ever left
     running past a single render.

No pip install, git clone, icon fetch, or any other network access happens
*inside* the sandbox — everything the script needs must already be a file in
the uploaded workspace. That is enforced by ``block_network=True``, not by
convention: if a script does try to reach the network, the connection fails
closed rather than silently succeeding.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import modal

from ..artifact_validation import validate_artifact
from ..contracts import DEFAULT_DIAGRAM_OUTPUTS, RenderLimits, RenderResult

_REMOTE_WORKDIR = "/workspace"

# Skipped when staging the local workspace into the sandbox — caches and
# stage-marker litter the script has no business reading, and any leftover
# file from a *previous* render (cleaned locally before each render anyway,
# but skipped here defensively so a stale remote copy can never be mistaken
# for this run's fresh output).
_SKIP_UPLOAD_DIR_NAMES = frozenset({"__pycache__", "outputs", ".git"})


class ModalSandboxRunner:
    """Production ``SandboxRunner``. See module docstring for the isolation
    model; see the improvement plan's "Security requirements for Modal"
    section for the policy every sandbox created here must follow."""

    def __init__(self, limits: RenderLimits | None = None) -> None:
        self._limits = limits or RenderLimits()
        self._app_name = os.environ.get("MODAL_SANDBOX_APP", "diagram-code-agent-render")
        self._image = (
            modal.Image.debian_slim(python_version="3.11")
            .apt_install("graphviz", "fontconfig", "fonts-dejavu-core")
            .pip_install(
                "diagrams>=0.23,<1",
                "pillow>=9,<12",
                "cairosvg>=2.7,<3",
            )
        )

    def render(
        self,
        workspace: Path,
        *,
        timeout: int,
        script_name: str = "diagram.py",
        allowed_outputs: tuple[str, ...] | None = None,
    ) -> RenderResult:
        outputs = allowed_outputs if allowed_outputs is not None else DEFAULT_DIAGRAM_OUTPUTS
        source_path = workspace / script_name
        if source_path.exists() and source_path.stat().st_size > self._limits.max_source_bytes:
            raise ValueError(
                f"Generated source exceeds the configured limit ({self._limits.max_source_bytes} bytes)"
            )

        app = modal.App.lookup(self._app_name, create_if_missing=True)

        sandbox = modal.Sandbox.create(
            "sleep",
            "infinity",
            app=app,
            image=self._image,
            workdir=_REMOTE_WORKDIR,
            cpu=self._limits.cpu_cores,
            memory=self._limits.memory_mib,
            timeout=timeout + self._limits.sandbox_idle_timeout_seconds,
            idle_timeout=self._limits.sandbox_idle_timeout_seconds,
            block_network=True,  # mandatory — see module docstring
            secrets=[],  # mandatory — no application secret is ever passed in
            env={
                "HOME": "/tmp",
                "PYTHONUNBUFFERED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            tags={"service": "diagram-code-agent"},
        )
        try:
            self._upload_workspace(sandbox, workspace, outputs)
            proc = sandbox.exec(
                "python",
                script_name,
                timeout=timeout,
                workdir=_REMOTE_WORKDIR,
            )
            stdout = self._bounded(proc.stdout.read())
            stderr = self._bounded(proc.stderr.read())
            returncode = proc.wait()
            if returncode == -1:
                # Modal's exec-level `timeout` kills the process and reports
                # -1 (verified empirically: a script that sleeps past
                # `timeout` returns -1 well before its own runtime elapses —
                # no POSIX signal produces -1, so this is Modal's own
                # timeout sentinel, not a script exit code). Translate to
                # subprocess.TimeoutExpired so this runner is a drop-in for
                # LocalDevRunner: render_diagram's `except
                # subprocess.TimeoutExpired` catch (tools/rendering_tools.py)
                # doesn't need a provider-specific branch.
                raise subprocess.TimeoutExpired(
                    cmd=["python", script_name],
                    timeout=timeout,
                    output=stdout,
                    stderr=stderr,
                )
            self._download_artifacts(sandbox, workspace, outputs)
            return RenderResult(
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                sandbox_id=sandbox.object_id,
            )
        finally:
            try:
                sandbox.terminate()
            except Exception:  # noqa: BLE001 — never let cleanup mask the real error
                pass

    def _upload_workspace(self, sandbox: "modal.Sandbox", workspace: Path, outputs: tuple[str, ...]) -> None:
        fs = sandbox.filesystem
        made_dirs: set[str] = set()
        for path in sorted(workspace.rglob("*")):
            if path.is_dir():
                continue
            rel_parts = path.relative_to(workspace).parts
            if any(part in _SKIP_UPLOAD_DIR_NAMES for part in rel_parts):
                continue
            if path.suffix == ".pyc":
                continue
            if path.name in outputs:
                # Stale output from a prior render — never re-upload; the
                # script is expected to produce it fresh.
                continue

            rel = path.relative_to(workspace).as_posix()
            remote_path = f"{_REMOTE_WORKDIR}/{rel}"
            remote_dir = remote_path.rsplit("/", 1)[0]
            if remote_dir != _REMOTE_WORKDIR and remote_dir not in made_dirs:
                fs.make_directory(remote_dir, create_parents=True)
                made_dirs.add(remote_dir)

            fs.write_bytes(path.read_bytes(), remote_path)

    def _download_artifacts(
        self, sandbox: "modal.Sandbox", workspace: Path, outputs: tuple[str, ...]
    ) -> None:
        fs = sandbox.filesystem
        total = 0
        for name in outputs:
            remote_path = f"{_REMOTE_WORKDIR}/{name}"
            try:
                info = fs.stat(remote_path)
            except modal.exception.SandboxFilesystemNotFoundError:
                continue

            if info.size > self._limits.max_artifact_bytes:
                raise ValueError(f"Artifact too large: {name}")
            total += info.size
            if total > self._limits.max_total_artifact_bytes:
                raise ValueError("Total artifact size exceeds the limit")

            data = fs.read_bytes(remote_path)
            # Untrusted output — validate before it touches the local
            # workspace (and therefore every downstream consumer).
            validate_artifact(name, data)
            (workspace / name).write_bytes(data)

    def _bounded(self, value) -> str:
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        return (value or "")[: self._limits.max_log_bytes]
