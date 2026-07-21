"""Reference/deploy-adjacent module for the diagram-render Modal App.

NAMING NOTE: this file must never be named `runtime.py` (or anything else
that collides with a top-level package under `backend/src/`, e.g.
`runtime`, `domain`, `tools`). Running a script directly (`python
modal/app.py`) puts the script's own directory — `backend/modal/` — at
`sys.path[0]`, ahead of `backend/src` (which is only appended near the end
of `sys.path` by the project's editable install). A same-named file there
would shadow the real package for the duration of that process. Confirmed
empirically while building this module — see the improvement plan's §0.1
notes.

Modal Sandboxes (unlike Modal Functions) do NOT need `modal deploy` to run —
`runtime.sandbox.runners.modal_runner.ModalSandboxRunner` creates sandboxes
programmatically via `modal.App.lookup(name, create_if_missing=True)` at
request time, which is why the actual App + Image definition lives in
`backend/src/runtime/sandbox/runners/modal_runner.py`, not here (a single
source of truth the request-serving process actually imports).

This file exists as the documented, human-discoverable entry point the
improvement plan's file map points at — useful for `modal shell`, ad-hoc
image debugging, or a future `modal deploy` if this app grows scheduled
Functions alongside its Sandboxes. Run directly to sanity-check that
credentials resolve and the app is reachable:

    cd backend && uv run python modal/app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))  # unconditional: _SRC may already be on

# sys.path (via the editable install's .pth file) but *after* site-packages
# and after this script's own directory — inserting at position 0
# unconditionally is what actually guarantees priority, not a membership
# check (see the naming note above for why that distinction bit us).

APP_NAME = os.environ.get("MODAL_SANDBOX_APP", "diagram-code-agent-render")


def check_app_reachable() -> None:
    import modal

    app = modal.App.lookup(APP_NAME, create_if_missing=True)
    print(f"OK — Modal app {APP_NAME!r} reachable: {app}")


if __name__ == "__main__":
    check_app_reachable()
