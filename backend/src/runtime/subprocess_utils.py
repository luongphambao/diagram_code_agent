"""Safe subprocess wrappers for external rendering tools (Graphviz).

All calls enforce:
* ``timeout`` — default 30 s; raises ``subprocess.TimeoutExpired`` on hang.
* No ``shell=True`` — arguments are always a list, preventing shell injection.
* Caller decides whether to ``check=True`` (raises ``CalledProcessError`` on
  non-zero exit) or handle errors themselves.

Import pattern::

    from subprocess_utils import run_graphviz, run_tred
"""

from __future__ import annotations

import subprocess
from typing import Any

# Default timeout for any graphviz / tred call.  Production diagrams typically
# render in < 2 s; 30 s gives a wide safety margin before we give up.
_DEFAULT_TIMEOUT: int = 30


def run_graphviz(
    cmd: list[str],
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """Run a Graphviz command (``dot``, ``neato``, etc.) with a hard timeout.

    Args:
        cmd:     Full command list, e.g. ``["dot", "-Tjson", "input.dot"]``.
                 Must NOT use ``shell=True``; pass arguments as a list.
        timeout: Seconds before the process is killed (default 30).
        **kwargs: Forwarded to ``subprocess.run`` (e.g. ``capture_output``,
                  ``text``, ``check``, ``input``).

    Returns:
        ``subprocess.CompletedProcess`` result.

    Raises:
        subprocess.TimeoutExpired: If the process runs longer than *timeout*.
        subprocess.CalledProcessError: If ``check=True`` and exit code != 0.
        FileNotFoundError: If the binary is not installed.
    """
    return subprocess.run(cmd, timeout=timeout, **kwargs)


def run_tred(
    dot_source: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
) -> str | None:
    """Run ``tred`` (Graphviz transitive reduction) on *dot_source*.

    Returns the reduced DOT string, or ``None`` if ``tred`` is not installed
    or returns a non-zero exit code (caller should fall back gracefully).
    """
    try:
        result = subprocess.run(
            ["tred"],
            input=dot_source,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
        return result.stdout
    except (FileNotFoundError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as exc:
        import sys
        sys.stderr.write(f"warning: tred unavailable or timed out ({exc})\n")
        return None
