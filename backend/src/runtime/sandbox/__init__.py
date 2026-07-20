"""Diagram-script execution sandbox: static pre-flight audit (``guards.py``) +
the subprocess exec wrapper (``render_exec.py``) that ``tools.rendering_tools``'s
``render_diagram`` tool calls into.

Threat model / current state: ``run_render`` is a plain subprocess — same
Python interpreter, no OS-level isolation (no rlimit, no uid drop, no network
block). The only protections today are a hard timeout and the static
pre-flight audit in ``guards.py`` (which blocks obviously-defective scripts
before they ever run, at zero execution cost). Stronger isolation (POSIX
rlimit/uid-drop behind a Docker-only env flag, or moving execution to a
container/gVisor boundary) is a deliberate follow-up, not done in this pass —
see the diagram_code_agent refactor plan's "Deferred to a future effort"
appendix.
"""

from __future__ import annotations
