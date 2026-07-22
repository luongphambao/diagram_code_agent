"""CORS origin resolution (improvement plan §0.5).

Extracted into a pure function so the fail-closed behavior — no
``ALLOWED_ORIGINS`` when ``APP_ENV=production`` refuses to start rather than
falling back to a wildcard — is unit-testable without importing ``server.py``
(whose module-level imports pull in the full agent/LangChain stack).
"""

from __future__ import annotations


class CorsConfigError(RuntimeError):
    """Raised when CORS cannot be configured safely for the current APP_ENV."""


_DEV_DEFAULT_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def resolve_allowed_origins(app_env: str, raw_origins: str) -> list[str]:
    """Return the CORS allowlist for *app_env* given the raw
    ``ALLOWED_ORIGINS`` env value (comma-separated, possibly empty).

    Raises :class:`CorsConfigError` if ``app_env == "production"`` and no
    origins were configured — production must never fall back to an open
    ("*") policy. Non-production environments fall back to a small,
    explicit local-dev default (matching docker-compose.yml's frontend
    origin) instead of a wildcard, so dev and prod share the same
    allowlist model.
    """
    origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

    if app_env.strip().lower() == "production" and not origins:
        raise CorsConfigError(
            "ALLOWED_ORIGINS is required when APP_ENV=production "
            "(comma-separated list of exact frontend origins) — refusing to "
            "start with an open CORS policy."
        )

    return origins or list(_DEV_DEFAULT_ORIGINS)
