"""Re-export shim — moved to ``runtime/backends.py``.

The ``_current_workspace`` ContextVar is defined exactly once in
``runtime.backends`` and re-exported here as the SAME object (not a copy), so
``backends._current_workspace`` and ``runtime.backends._current_workspace``
are identical — required for per-thread workspace binding to work regardless
of which import path a caller uses (see runtime/backends.py's module docstring).
"""

from __future__ import annotations

from runtime.backends import (
    AGENT_SPACE,
    GLOBAL_MEMORY_PATH,
    LOCAL_ICONS,
    LOCAL_MANIFEST,
    LOCAL_NODE_CATALOG,
    MEMORIES_DIR,
    MEMORY_PATH,
    OUTPUTS_DIR,
    SKILLS_DIR,
    WORKSPACE,
    WORKSPACES_DIR,
    PerThreadFilesystemBackend,
    WorkspaceFile,
    _current_workspace,
    _ensure_dirs,
    current_workspace,
    make_local_backend,
    reset_current_workspace,
    resolve_workspace,
    set_current_workspace,
)
