"""Agent-space backend configuration using deepagents native backends.

Layout under agent_space/:
  workspace/    — shared scratch area; only used for the default/dev thread
                  ("thread-default") — see PerThreadFilesystemBackend below
  workspaces/   — per-thread dirs (or ARTIFACTS_DIR/<thread_id> if set), each
                  with its own workspace/ (default route) + memories/ (/memories/ route)
  memories/     — durable, cross-thread semantic memory; /global-memories/AGENTS.md
  outputs/      — timestamped run archives

Paths are resolved relative to this repo so the project is self-contained:
  backend/                 <- _BACKEND_ROOT (parents[1] of this file)
  backend/agent_space/     <- AGENT_SPACE (created at runtime)
  backend/skills/          <- SKILLS_DIR (bundled procedural skills)
  resources/icons/         <- icon pack (shared, sibling of backend/)
"""

from __future__ import annotations

import contextvars
import os
from pathlib import Path

from deepagents.backends import CompositeBackend, FilesystemBackend

# backend/src/backends.py -> parents[1] == backend/
_BACKEND_ROOT  = Path(__file__).resolve().parents[1]
_REPO_ROOT     = _BACKEND_ROOT.parent

AGENT_SPACE    = _BACKEND_ROOT / "agent_space"
WORKSPACE      = AGENT_SPACE / "workspace"
MEMORIES_DIR   = AGENT_SPACE / "memories"
OUTPUTS_DIR    = AGENT_SPACE / "outputs"

# Per-thread workspace isolation (§4.10 multi-tenancy).
#
# `WORKSPACE` above is the shared scratch dir used only as a fallback for the
# default/dev thread ("thread-default", or no thread_id at all). The helpers
# below give each real thread/tenant its OWN artifact directory. Custom tools
# read/write it via `current_workspace()` (the contextvar below); the agent's
# own built-in filesystem tools (read_file/write_file/edit_file/ls/glob/grep)
# are ALSO per-thread via `PerThreadFilesystemBackend` (see `make_local_backend`
# below), which resolves the same contextvar on every call instead of being
# bound to a fixed directory at graph-build time.
#
# By default per-thread workspaces live under agent_space/workspaces/<thread_id>.
# Set ARTIFACTS_DIR to an absolute path to mount them somewhere else instead (e.g.
# a host-visible bind mount in Docker) — every session then shows up as
# <ARTIFACTS_DIR>/<thread_id>/ with no copy step, since resolve_workspace() below
# writes there directly.
_ARTIFACTS_DIR_ENV = os.getenv("ARTIFACTS_DIR", "").strip()
WORKSPACES_DIR = Path(_ARTIFACTS_DIR_ENV).resolve() if _ARTIFACTS_DIR_ENV else (AGENT_SPACE / "workspaces")

# Context-local "current workspace" — defaults to the shared WORKSPACE so existing
# code paths are unchanged. A request handler can set it for the duration of a
# thread's work via `set_current_workspace(...)`.
_current_workspace: contextvars.ContextVar[Path] = contextvars.ContextVar(
    "current_workspace", default=WORKSPACE
)


def resolve_workspace(thread_id: str | None) -> Path:
    """Return the isolated workspace directory for ``thread_id`` (created if needed).

    Falls back to the shared ``WORKSPACE`` for an empty/None thread id (dev default).
    The thread id is sanitised with ``safe_filename`` so a hostile id cannot escape
    ``WORKSPACES_DIR``.
    """
    if not thread_id or thread_id == "thread-default":
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        return WORKSPACE
    from safe_path import safe_filename
    ws = WORKSPACES_DIR / safe_filename(thread_id)
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def current_workspace() -> Path:
    """The workspace bound to the current execution context (shared by default)."""
    return _current_workspace.get()


def set_current_workspace(workspace: Path) -> contextvars.Token:
    """Bind ``workspace`` as the current-context workspace; returns a reset token."""
    return _current_workspace.set(Path(workspace))


def reset_current_workspace(token: contextvars.Token) -> None:
    """Restore the previous current-context workspace (use the token from set_*)."""
    _current_workspace.reset(token)


class WorkspaceFile:
    """A workspace-relative file resolved lazily against the *current thread's*
    workspace (see :func:`current_workspace`).

    Stage-marker / store paths used to be bound to the shared ``WORKSPACE`` at import
    time, so every thread wrote to the same files. Wrapping the name in this proxy
    defers the join to call time: each ``.exists()`` / ``.read_text()`` /
    ``.write_text()`` / ``.unlink()`` / ``.parent`` / ``str()`` resolves against
    whatever workspace is bound for the running request (per-thread isolation,
    §4.10). It quacks like a :class:`pathlib.Path` for the operations the tools use,
    so importers can keep ``from … import _BRIEF_FILE`` unchanged.
    """

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def _path(self) -> Path:
        return current_workspace() / self._name

    def __getattr__(self, attr: str):  # exists/read_text/write_text/unlink/parent/...
        return getattr(self._path(), attr)

    def __truediv__(self, other):
        return self._path() / other

    def __fspath__(self) -> str:
        return str(self._path())

    def __str__(self) -> str:
        return str(self._path())

    def __repr__(self) -> str:
        return f"WorkspaceFile({self._name!r})"


class PerThreadFilesystemBackend(FilesystemBackend):
    """FilesystemBackend whose root directory tracks the request-scoped
    ``current_workspace()`` contextvar instead of being fixed once at
    construction time (fixes the cross-thread artifact leak, §4.10).

    A single instance is built once at process startup in
    :func:`make_local_backend` and shared by every agent (main + all
    subagents) for the process lifetime. deepagents' ``FilesystemBackend``
    reads ``self.cwd`` fresh on every filesystem call rather than caching
    it, so overriding ``cwd`` as a property (with a no-op setter to swallow
    the base ``__init__``'s one-time assignment) makes the SAME backend
    instance transparently serve a different directory for every
    concurrent thread — no per-request backend/graph rebuild needed, and no
    reliance on deepagents' deprecated callable-backend-factory path.

    ``subdir``, if given, appends a fixed relative subfolder under the
    per-thread workspace (used for the per-thread ``/memories/`` route so
    it doesn't collapse onto the same directory as the default ``/`` route).
    """

    def __init__(self, *, subdir: str = "", **kwargs) -> None:
        self._subdir = subdir
        super().__init__(**kwargs)

    @property
    def cwd(self) -> Path:  # noqa: D102 - overrides FilesystemBackend.cwd
        base = current_workspace()
        if self._subdir:
            base = base / self._subdir
            base.mkdir(parents=True, exist_ok=True)
        return base

    @cwd.setter
    def cwd(self, _value) -> None:
        # Swallow FilesystemBackend.__init__'s one-time `self.cwd = ...`
        # assignment — the property getter above is the single source of
        # truth for every subsequent access.
        pass


# Procedural skills bundled with the repo (loaded by the deep agent).
SKILLS_DIR     = _BACKEND_ROOT / "skills"

# Icon assets gathered under resources/ (for local execution without Modal).
_RESOURCES     = _REPO_ROOT / "resources"
LOCAL_ICONS    = str(_RESOURCES / "icons")
LOCAL_MANIFEST = str(_RESOURCES / "icons_manifest.json")
LOCAL_NODE_CATALOG = str(_RESOURCES / "node_catalog.json")

# Virtual path prefixes the agent uses to read/write memory.
# `/memories/` is per-thread scratch (empty for every new thread); `/global-memories/`
# is the durable, cross-thread memory file every agent can read but only the main
# agent is instructed to edit (see prompts/_blocks.py).
MEMORY_PATH = "/memories/AGENTS.md"
GLOBAL_MEMORY_PATH = "/global-memories/AGENTS.md"


def _ensure_dirs() -> None:
    for d in (WORKSPACE, MEMORIES_DIR, OUTPUTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def make_local_backend() -> CompositeBackend:
    """Build the CompositeBackend for the single diagram deep agent.

    The agent gets ONLY filesystem tools (read_file/write_file/edit_file/ls/glob/grep)
    — no shell `execute`. Rendering a diagram is done through the custom
    `render_diagram` tool (see :mod:`diagram_mcp.tools`), which runs the generated
    ``diagrams`` code in a subprocess. This keeps the design to "deep agent + tools
    + memory".

    Built once at process startup and reused for the main agent and every subagent
    (§4.10) — safe because both routes below resolve their root lazily against the
    per-request `current_workspace()` contextvar instead of a path baked in here.

    Routing:
      /memories/         → PerThreadFilesystemBackend rooted at
                            <current thread's workspace>/memories/ — each thread's
                            own scratch memory, empty by default.
      /global-memories/  → FilesystemBackend rooted at MEMORIES_DIR
                            (agent_space/memories/AGENTS.md) — durable, shared across
                            every thread; read by all agents, written only by the
                            main agent (by prompt convention).
      (default)           → PerThreadFilesystemBackend rooted at
                            <current thread's workspace>/ — diagram.py / out.png /
                            out.dot / out.drawio / wbs.json / etc. live here.
    """
    _ensure_dirs()
    return CompositeBackend(
        default=PerThreadFilesystemBackend(root_dir=str(WORKSPACE), virtual_mode=True),
        routes={
            "/memories/": PerThreadFilesystemBackend(
                root_dir=str(WORKSPACE),
                subdir="memories",
                virtual_mode=True,
            ),
            "/global-memories/": FilesystemBackend(
                root_dir=str(MEMORIES_DIR),
                virtual_mode=True,
            ),
        },
    )
