"""Readiness + version reporting (improvement plan §1.5).

Extracted out of server.py so these checks are unit-testable without importing
the full agent/LangChain import chain (the same rationale as config/cors.py and
security/auth.py). /health/ready must reflect whether THIS instance can
actually serve a request right now — the dependencies /agui needs: Postgres
(when DATABASE_URL is configured) and Modal auth + App lookup (when
SANDBOX_PROVIDER=modal) — without creating a billable sandbox on every probe
(see runtime/sandbox/provider.py's docstring for why a real render is a
separate, scheduled smoke test instead of a readiness check).
"""

from __future__ import annotations

import asyncio
import os


async def check_postgres(pool) -> dict:
    """`SELECT 1` against the session pool. `pool is None` means DATABASE_URL was
    unset (in-memory dev sessions) — that's a valid, working configuration, not
    a readiness failure."""
    if pool is None:
        return {"ok": True, "note": "DATABASE_URL unset — in-memory dev sessions"}
    try:
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


async def check_modal() -> dict:
    """`modal.App.lookup(..., create_if_missing=True)` — a lightweight control-plane
    call that verifies credentials and app existence WITHOUT creating a sandbox
    (no compute, not billable). Skipped (reported ok) when SANDBOX_PROVIDER is
    "local" — that's only ever permitted outside production anyway (see
    runtime/sandbox/provider.py)."""
    provider = os.getenv("SANDBOX_PROVIDER", "modal").strip().lower()
    if provider != "modal":
        return {"ok": True, "note": f"SANDBOX_PROVIDER={provider}"}
    try:
        import modal

        app_name = os.environ.get("MODAL_SANDBOX_APP", "diagram-code-agent-render")
        await asyncio.to_thread(modal.App.lookup, app_name, create_if_missing=True)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def check_model_config() -> dict:
    """At least one LLM provider key must be configured for the agent to do
    anything — a missing key is a readiness failure, not just a runtime
    surprise on the first request."""
    if os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"):
        return {"ok": True}
    return {"ok": False, "error": "no OPENAI_API_KEY/ANTHROPIC_API_KEY configured"}


async def run_readiness_checks(pool) -> tuple[bool, dict]:
    """Run every check (Postgres + Modal concurrently; model config is
    synchronous/free) and return ``(overall_ok, checks_by_name)``."""
    postgres, modal_check = await asyncio.gather(check_postgres(pool), check_modal())
    checks = {
        "postgres": postgres,
        "modal": modal_check,
        "model_config": check_model_config(),
    }
    ok = all(c["ok"] for c in checks.values())
    return ok, checks


def version_info(*, app_version: str, auth_mode: str) -> dict:
    """Static version/build metadata (improvement plan's `/version` shape).
    `GIT_SHA`/`BUILD_TIME` are meant to be set at image-build time (see
    backend/Dockerfile); locally they fall back to "unknown" rather than
    guessing, since a wrong value is worse than an honest "not set" for a
    field whose whole purpose is pinpointing exactly what's deployed.
    `solution_schema_version` now reads memory/stores/csm.py's
    `SolutionModel.schema_version` field/default directly (improvement plan
    §1.2) instead of being a second, independently-hardcoded string that
    could silently drift from the model's own value."""
    from memory.stores.csm import SCHEMA_VERSION

    return {
        "version": app_version,
        "git_sha": os.getenv("GIT_SHA", "unknown"),
        "build_time": os.getenv("BUILD_TIME", "unknown"),
        "api_schema_version": "1",
        "solution_schema_version": SCHEMA_VERSION,
        "auth_mode": auth_mode,
        "sandbox_provider": os.getenv("SANDBOX_PROVIDER", "modal"),
    }
