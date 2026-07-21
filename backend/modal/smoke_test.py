"""End-to-end Modal Sandbox smoke test (improvement plan §0.1 verification).

Renders a tiny real `diagrams` script through `ModalSandboxRunner` and
asserts the security properties the improvement plan requires:

  * the sandbox executes successfully and produces out.png / out.dot,
  * secrets are NOT visible inside the sandbox (OPENAI_API_KEY absent),
  * outbound network is blocked (block_network=True is actually enforced,
    not just requested),
  * the sandbox always terminates.

Run manually (needs MODAL_TOKEN_ID/MODAL_TOKEN_SECRET in the environment —
see backend/.env):

    cd backend && uv run python modal/smoke_test.py

Not part of the pytest suite (it costs real Modal compute and needs live
credentials) — CI should run this as a separate, protected-branch job per
the improvement plan's CI section, not on every PR.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
# Unconditional insert at position 0: _SRC may already be on sys.path via the
# editable install's .pth file, but only *after* site-packages and after this
# script's own directory (backend/modal/) — see modal/app.py's naming note
# for why a plain membership check isn't enough to guarantee priority.
sys.path.insert(0, str(_SRC))

_SMOKE_SCRIPT = '''
import os
from diagrams import Diagram
from diagrams.aws.compute import EC2
from diagrams.aws.database import RDS

with Diagram("smoke test", filename="out", outformat=["png", "dot"], show=False):
    EC2("web") >> RDS("db")

assert not os.environ.get("OPENAI_API_KEY"), "secret leaked into sandbox env"

try:
    import socket
    socket.create_connection(("8.8.8.8", 53), timeout=3)
    print("NETWORK_BLOCKED=False")
except OSError:
    print("NETWORK_BLOCKED=True")
'''


def main() -> int:
    from runtime.sandbox.runners.modal_runner import ModalSandboxRunner

    workspace = Path(tempfile.mkdtemp(prefix="modal-smoke-"))
    try:
        (workspace / "diagram.py").write_text(_SMOKE_SCRIPT, encoding="utf-8")

        runner = ModalSandboxRunner()
        result = runner.render(workspace, timeout=60)

        ok = True
        if result.returncode != 0:
            print(f"FAIL: non-zero exit ({result.returncode})\nstderr:\n{result.stderr}")
            ok = False
        if "NETWORK_BLOCKED=True" not in result.stdout:
            print(f"FAIL: network was not blocked. stdout:\n{result.stdout}")
            ok = False
        if not (workspace / "out.png").exists():
            print("FAIL: out.png was not produced")
            ok = False
        if not (workspace / "out.dot").exists():
            print("FAIL: out.dot was not produced")
            ok = False

        if ok:
            print(f"OK — sandbox {result.sandbox_id} rendered successfully, "
                  f"network blocked, no secret leak.")
        return 0 if ok else 1
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
