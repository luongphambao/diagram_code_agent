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
     whatever input data the caller staged there — resolved icon/logo assets
     for a diagram render, or e.g. an uploaded ``.xlsx``/``wbs.json`` for a
     data-analysis run — the ``prettygraph/`` package itself is baked into
     the diagram image at build time instead, see ``_PRETTYGRAPH_SRC_DIR``
     below, so it is skipped here) into a fresh sandbox's filesystem,
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

# improvement plan §D: the top-level prettygraph/*.py files (imported by every
# generated diagram.py as `from prettygraph import Pretty`) are static repo
# content, not per-render output — baked into the diagram image below instead
# of re-uploaded file-by-file on every render. `tools/stage_markers.py`'s
# `_stage_helpers()` still writes this same content into the LOCAL per-thread
# workspace (that copy is what LocalDevRunner's subprocess actually runs
# against), so it is skipped here purely to avoid a redundant upload of
# content the image already has baked in.
_SRC_DIR = Path(__file__).resolve().parents[3]
_PRETTYGRAPH_SRC_DIR = _SRC_DIR / "prettygraph"
# audit.py/drawio.py/graph_builder.py (all baked above) do `from subprocess_utils
# import run_graphviz` — a TOP-LEVEL sibling module, not a prettygraph submodule.
# Live-tested and confirmed: without this, `from prettygraph import Pretty` raises
# ModuleNotFoundError inside the sandbox (it was never staged into the workspace
# either, pre-dating this change — the mingrammer render path apparently never
# ran end-to-end through Modal with a real Pretty-based script before). The shim
# (`subprocess_utils.py`) re-exports from `runtime.subprocess_utils`, so both
# come along; `runtime/` itself is otherwise NOT baked (its other submodules,
# e.g. `runtime.sandbox`, pull in the `modal` SDK and app-config machinery that
# has no business running inside the sandbox it configures).
_SUBPROCESS_UTILS_SHIM = _SRC_DIR / "subprocess_utils.py"
_RUNTIME_SRC_DIR = _SRC_DIR / "runtime"

# Skipped when staging the local workspace into the sandbox — caches and
# stage-marker litter the script has no business reading, any leftover file
# from a *previous* render (cleaned locally before each render anyway, but
# skipped here defensively so a stale remote copy can never be mistaken for
# this run's fresh output), and "prettygraph"/"runtime" (see above — baked
# into the image instead).
_SKIP_UPLOAD_DIR_NAMES = frozenset({"__pycache__", "outputs", ".git", "prettygraph", "runtime"})
# subprocess_utils.py never was, and still isn't, staged into the local
# workspace by anything — skipped here by name (not dir) so a same-named file
# a caller might legitimately stage (unlikely, but this is a top-level name)
# can't collide silently; it simply won't be re-uploaded now that it's baked.
_SKIP_UPLOAD_FILE_NAMES = frozenset({"subprocess_utils.py"})


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
            # improvement plan §D: bake the top-level prettygraph/*.py files (the
            # exact set `tools/stage_markers.py`'s `_stage_helpers()` mirrors into
            # the local workspace — `native/` is a separate subpackage no
            # generated diagram.py imports) into the image layer instead of
            # uploading them via `_upload_workspace` on every single render.
            .add_local_dir(
                str(_PRETTYGRAPH_SRC_DIR),
                remote_path=f"{_REMOTE_WORKDIR}/prettygraph",
                copy=True,
                ignore=lambda p: p.suffix != ".py" or (p.parts and p.parts[0] == "native"),
            )
            # prettygraph's audit.py/drawio.py/graph_builder.py need this top-level
            # sibling module (see _SUBPROCESS_UTILS_SHIM's comment above).
            .add_local_file(
                str(_SUBPROCESS_UTILS_SHIM),
                remote_path=f"{_REMOTE_WORKDIR}/subprocess_utils.py",
                copy=True,
            )
            .add_local_dir(
                str(_RUNTIME_SRC_DIR),
                remote_path=f"{_REMOTE_WORKDIR}/runtime",
                copy=True,
                ignore=lambda p: p.parts != ("__init__.py",) and p.parts != ("subprocess_utils.py",),
            )
        )
        # improvement plan §C-S2: run_python (tools/code_interpreter.py, script_name=
        # "interpreter_script.py") needs pandas/numpy/openpyxl to analyze uploaded
        # .xlsx/.csv data — kept OUT of the diagram image above so every diagram
        # render (the common case) doesn't pay for a data-science toolchain it
        # never uses. Selected by script_name in render() below.
        self._interpreter_image = modal.Image.debian_slim(python_version="3.11").pip_install(
            "pandas>=2.0,<3",
            "numpy>=1.26,<3",
            "openpyxl>=3.1,<4",
            "matplotlib>=3.8,<4",
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

        # script_name is the existing, already-distinct signal each caller sets
        # (render_diagram always passes the default "diagram.py"; run_python always
        # passes "interpreter_script.py" — tools/code_interpreter.py's _SCRIPT_NAME)
        # — reused here instead of adding a new "job type" parameter just to pick
        # an image.
        image = self._image if script_name == "diagram.py" else self._interpreter_image

        app = modal.App.lookup(self._app_name, create_if_missing=True)

        sandbox = modal.Sandbox.create(
            "sleep",
            "infinity",
            app=app,
            image=image,
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
            if path.name in _SKIP_UPLOAD_FILE_NAMES:
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
