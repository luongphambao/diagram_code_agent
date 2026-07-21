"""Runner selection for the diagram-render sandbox (improvement plan §0.1).

``SANDBOX_PROVIDER=modal`` is the default everywhere. ``local`` is only
selectable when ``APP_ENV`` is anything other than ``production`` — CI and
laptop development keep working without Modal credentials, but a
misconfigured or forgotten env var can never silently downgrade a production
deployment back to unsandboxed host execution. There is deliberately NO
try/except fallback from Modal to local here: if Modal is unreachable in
production, the render fails with a clear, retryable error instead of
running attacker-controlled code on the API host.
"""

from __future__ import annotations

import os

from .runners.base import SandboxRunner


class SandboxConfigError(RuntimeError):
    """Raised when the configured SANDBOX_PROVIDER is unsafe or unsupported
    for the current APP_ENV — fails closed rather than falling back silently."""


def get_sandbox_runner() -> SandboxRunner:
    """Build the runner for the current process's configuration.

    Not cached: constructing either runner is cheap (no network call is made
    until ``.render()`` actually creates a sandbox / subprocess), and reading
    fresh env vars on every call keeps tests that monkeypatch
    ``SANDBOX_PROVIDER``/``APP_ENV`` per-test correct without needing to
    reset a cache.
    """
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    provider = os.getenv("SANDBOX_PROVIDER", "modal").strip().lower()

    if provider == "local":
        if app_env == "production":
            raise SandboxConfigError(
                "SANDBOX_PROVIDER=local is not permitted when APP_ENV=production "
                "— generated diagram code would run unsandboxed on the API host. "
                "Set SANDBOX_PROVIDER=modal (or unset it)."
            )
        from .runners.local_dev_runner import LocalDevRunner

        return LocalDevRunner()

    if provider == "modal":
        from .runners.modal_runner import ModalSandboxRunner

        return ModalSandboxRunner()

    raise SandboxConfigError(
        f"Unknown SANDBOX_PROVIDER={provider!r} — expected 'modal' or 'local'."
    )
