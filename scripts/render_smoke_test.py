"""Manual smoke test: render a diagram through the configured SandboxRunner
(Modal by default) and save the result under ./artifacts/<label>/ so it's
visible on the host — same host-visible layout docker-compose.yml already
uses for real per-thread workspaces.

Why this exists: while verifying the Modal sandbox wiring, the agent
environment used to develop this repo could not resolve *.w.modal.host
(Modal's per-sandbox exec/file-transfer hostname) — api.modal.com and every
other common dev domain resolved fine, so it's a narrow egress restriction
specific to that dev sandbox, not a bug in this code. Run this from YOUR OWN
terminal (not through an agent tool) against the real backend container,
where that restriction should not apply.

Usage (from repo root, with `docker compose up -d` already running):
    docker compose exec backend python /app/backend/scripts/render_smoke_test.py

Or directly on the host if you have the backend's Python env (uv):
    cd backend && uv run python scripts/render_smoke_test.py
"""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, "/app/backend/src" if pathlib.Path("/app/backend/src").exists() else "src")

from runtime.sandbox.provider import get_sandbox_runner  # noqa: E402

DIAGRAM_CODE = """
from diagrams import Diagram
from diagrams.aws.compute import EC2
from diagrams.aws.database import RDS
from diagrams.aws.network import ELB

with Diagram("smoke test", filename="out", outformat=["png", "dot"], show=False):
    ELB("lb") >> EC2("web") >> RDS("db")
"""


def main() -> None:
    label = f"sandbox-smoke-{int(time.time())}"
    # Host-visible path — matches ARTIFACTS_DIR's per-thread layout so the
    # result shows up under ./artifacts/<label>/ on your machine.
    artifacts_root = pathlib.Path("/app/artifacts" if pathlib.Path("/app/artifacts").exists() else "../artifacts")
    workspace = artifacts_root / label
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "diagram.py").write_text(DIAGRAM_CODE, encoding="utf-8")

    runner = get_sandbox_runner()
    print(f"Runner: {type(runner).__name__}")
    print(f"Workspace: {workspace}")

    t0 = time.monotonic()
    try:
        result = runner.render(workspace, timeout=90)
    except Exception as exc:  # noqa: BLE001
        print(f"RENDER RAISED after {time.monotonic() - t0:.1f}s: {exc!r}")
        raise
    duration = time.monotonic() - t0

    print(f"Duration: {duration:.1f}s")
    print(f"Exit code: {result.returncode}")
    print(f"Sandbox id: {getattr(result, 'sandbox_id', 'N/A')}")
    if result.stderr:
        print(f"Stderr (tail): {result.stderr[-500:]}")

    png = workspace / "out.png"
    if png.exists():
        print(f"SUCCESS — out.png saved at {png} ({png.stat().st_size} bytes)")
    else:
        print("out.png was NOT produced — see exit code / stderr above.")


if __name__ == "__main__":
    main()
