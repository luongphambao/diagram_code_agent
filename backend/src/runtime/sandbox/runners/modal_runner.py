"""Modal Sandbox runner (improvement plan §0.1 / Modal Sandbox decision).

Executes generated ``diagram.py`` in an isolated, ephemeral Modal Sandbox
with outbound networking blocked and no application secret in its
environment — closing the gap the local runner (see ``local_dev_runner.py``
and ``runtime/sandbox/__init__.py``'s threat-model docstring) cannot: real
OS-level isolation, not just a scrubbed environment.

Unlike ``LocalDevRunner`` (which runs *in* the local per-thread workspace
and needs no file transfer), ``render()`` here:

  1. uploads every file already staged into ``workspace`` (``diagram.py``,
     the staged ``prettygraph/`` package, any resolved icon/logo assets the
     script references — see ``tools/stage_markers.py``'s ``_stage_helpers``
     and ``tools/icon_tools.py``) into a fresh sandbox's filesystem,
  2. runs the script inside the sandbox with ``block_network=True``,
     ``secrets=[]``, and explicit CPU/memory/timeout limits,
  3. downloads back only the allowlisted output filenames into the SAME
     local workspace path, running each through
     ``artifact_validation.validate_artifact`` before it is trusted, so every
     downstream consumer (``export_drawio``, ``_layout_audit``,
     ``_inspection_image_b64``, ``record_artifact_inventory``,
     ``_archive_session``, ...) keeps working unmodified,
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
from ..contracts import RenderLimits, RenderResult

_REMOTE_WORKDIR = "/workspace"

# Names render_diagram / export_drawio / _layout_audit / _archive_session may
# look for after a render — mirrors tools/constants.py's _OUT_NAMES plus the
# JSON side files a render can produce. Anything the script writes outside
# this list never leaves the sandbox.
_ALLOWED_OUTPUT_NAMES = (
    "out.png",
    "out.body.png",
    "out.dot",
    "out.drawio",
    "out.nodes.json",
    "out.slide.json",
    "out.native_stats.json",
)

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
    ) -> RenderResult:
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
            self._upload_workspace(sandbox, workspace)
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
            self._download_artifacts(sandbox, workspace)
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

    def _upload_workspace(self, sandbox: "modal.Sandbox", workspace: Path) -> None:
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
            if path.name in _ALLOWED_OUTPUT_NAMES:
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

    def _download_artifacts(self, sandbox: "modal.Sandbox", workspace: Path) -> None:
        fs = sandbox.filesystem
        total = 0
        for name in _ALLOWED_OUTPUT_NAMES:
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
