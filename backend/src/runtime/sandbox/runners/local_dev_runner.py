"""Local subprocess runner — dev/offline fallback ONLY.

Same-interpreter execution (no OS-level isolation — see the threat-model
docstring in ``runtime/sandbox/__init__.py``), hardened with the secret
env-scrub added in the Modal-sandbox pass (improvement plan §0.2): a
malicious script that reads ``os.environ`` no longer sees API keys, database
URLs, or the Modal client's own token.

``runtime.sandbox.provider`` refuses to select this runner when
``APP_ENV=production`` — it exists so local development and CI keep working
without Modal credentials, not as a production execution path.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..artifact_validation import validate_artifact
from ..contracts import DEFAULT_DIAGRAM_OUTPUTS, RenderLimits, RenderResult
from ..render_exec import run_render

# Prefixes covering every secret-bearing env var this repo currently reads
# (see backend/.env.example and config/models.py's per-provider api_key_env
# indirection) plus a keyword fallback so a newly added `*_API_KEY`/`*_TOKEN`/
# `*_SECRET` doesn't need this list updated to stay covered.
_SECRET_ENV_PREFIXES = (
    "OPENAI_",
    "ANTHROPIC_",
    "TAVILY_",
    "COMPOSIO_",
    "GMAIL_",
    "GOOGLE_",
    "QDRANT_",
    "JIRA_",
    "MODAL_",
    "LANGSMITH_",
    "LANGCHAIN_",
    "MIMO_",
    "BNK_",
    "DATABASE_",
)
_SECRET_KEYWORDS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL")

# The minimum a Python + Graphviz process needs to run at all.
_ENV_ALLOWLIST = frozenset({"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TMP", "TEMP"})


def _is_secret_key(key: str) -> bool:
    if key in _ENV_ALLOWLIST:
        return False
    if any(key.startswith(prefix) for prefix in _SECRET_ENV_PREFIXES):
        return True
    return any(word in key for word in _SECRET_KEYWORDS)


def _scrubbed_env() -> dict[str, str]:
    """Build a copy of the current environment with every secret-shaped
    variable removed. Non-secret variables (PATH, locale, PYTHONPATH, ...)
    pass through so the interpreter and Graphviz still function normally."""
    env = {k: v for k, v in os.environ.items() if not _is_secret_key(k)}
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    return env


class LocalDevRunner:
    """Dev-only ``SandboxRunner``. See module docstring for the threat model
    this leaves open — pair with ``SANDBOX_PROVIDER=modal`` for real
    isolation; this runner is never selected in production."""

    def __init__(self, limits: RenderLimits | None = None) -> None:
        self._limits = limits or RenderLimits()

    def render(
        self,
        workspace: Path,
        *,
        timeout: int,
        script_name: str = "diagram.py",
        allowed_outputs: tuple[str, ...] | None = None,
    ) -> RenderResult:
        outputs = allowed_outputs if allowed_outputs is not None else DEFAULT_DIAGRAM_OUTPUTS
        proc = run_render(
            workspace,
            timeout=timeout,
            script_name=script_name,
            env=_scrubbed_env(),
        )
        # The script writes directly into `workspace` (no upload/download
        # step, unlike ModalSandboxRunner) — but its output is exactly as
        # untrusted, so validate every declared output that actually exists
        # before this runner is considered a drop-in for the Modal path.
        # Matches ModalSandboxRunner's behavior: a failing artifact raises
        # ArtifactValidationError rather than silently returning bad content.
        for name in outputs:
            path = workspace / name
            if path.exists():
                validate_artifact(name, path.read_bytes())
        return RenderResult(
            returncode=proc.returncode,
            stdout=(proc.stdout or "")[: self._limits.max_log_bytes],
            stderr=(proc.stderr or "")[: self._limits.max_log_bytes],
        )
