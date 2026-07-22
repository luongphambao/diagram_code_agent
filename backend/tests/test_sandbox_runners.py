"""Security regression tests for the SandboxRunner seam (improvement plan §0.1-0.3, §0.7).

Covers what each runner is actually responsible for:
  * ``provider.get_sandbox_runner`` — fails closed in production, never
    silently downgrades to unsandboxed local execution.
  * ``LocalDevRunner`` — strips secret-shaped env vars before the script can
    read them (it does NOT provide OS/network isolation — that's Modal's job,
    see the live Modal test below).
  * ``artifact_validation`` — rejects malformed/oversized/unsafe render
    output regardless of which runner produced it.
  * ``ModalSandboxRunner`` — a live, network-block + secret-absence
    end-to-end check, skipped unless MODAL_TOKEN_ID/MODAL_TOKEN_SECRET are
    present (mirrors the improvement plan's "Modal smoke test runs in a
    protected CI job, not on every PR" guidance — this repo's evals.yml
    doesn't export those, so it's skipped there and only runs when a
    developer has Modal credentials configured, e.g. locally).
"""

from __future__ import annotations

import os
import subprocess

import pytest

from runtime.sandbox.artifact_validation import ArtifactValidationError, validate_artifact
from runtime.sandbox.contracts import RenderLimits, RenderResult
from runtime.sandbox.provider import SandboxConfigError, get_sandbox_runner
from runtime.sandbox.runners.local_dev_runner import LocalDevRunner, _scrubbed_env


# --- provider selection: fail-closed -----------------------------------------

def test_provider_defaults_to_modal(monkeypatch):
    monkeypatch.delenv("SANDBOX_PROVIDER", raising=False)
    from runtime.sandbox.runners.modal_runner import ModalSandboxRunner

    runner = get_sandbox_runner()
    assert isinstance(runner, ModalSandboxRunner)


def test_provider_rejects_local_in_production(monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVIDER", "local")
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(SandboxConfigError, match="production"):
        get_sandbox_runner()


def test_provider_allows_local_in_development(monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVIDER", "local")
    monkeypatch.setenv("APP_ENV", "development")
    runner = get_sandbox_runner()
    assert isinstance(runner, LocalDevRunner)


def test_provider_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVIDER", "docker")
    monkeypatch.delenv("APP_ENV", raising=False)
    with pytest.raises(SandboxConfigError, match="docker"):
        get_sandbox_runner()


# --- LocalDevRunner: secret scrubbing -----------------------------------------

def test_scrubbed_env_removes_known_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("DATABASE_URL", "postgres://should-not-leak")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "as-should-not-leak")
    monkeypatch.setenv("MY_CUSTOM_TOKEN", "should-not-leak-either")  # keyword fallback
    monkeypatch.setenv("PATH", "/usr/bin")

    env = _scrubbed_env()

    assert "OPENAI_API_KEY" not in env
    assert "DATABASE_URL" not in env
    assert "MODAL_TOKEN_SECRET" not in env
    assert "MY_CUSTOM_TOKEN" not in env
    assert env["PATH"] == "/usr/bin"


def test_local_dev_runner_script_cannot_see_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    (tmp_path / "diagram.py").write_text(
        "import os\nprint(repr(os.environ.get('OPENAI_API_KEY')))\n",
        encoding="utf-8",
    )
    result = LocalDevRunner().render(tmp_path, timeout=10)
    assert result.returncode == 0
    assert result.stdout.strip() == "None"


def test_local_dev_runner_matches_render_result_contract(tmp_path):
    (tmp_path / "diagram.py").write_text("print('hi')\n", encoding="utf-8")
    result = LocalDevRunner().render(tmp_path, timeout=10)
    assert isinstance(result, RenderResult)
    assert result.returncode == 0
    assert "hi" in result.stdout


def test_local_dev_runner_propagates_timeout(tmp_path):
    (tmp_path / "diagram.py").write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    with pytest.raises(subprocess.TimeoutExpired):
        LocalDevRunner().render(tmp_path, timeout=1)


# --- artifact_validation: untrusted output ------------------------------------

def _minimal_png() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), color=(255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def test_validate_artifact_accepts_real_png():
    validate_artifact("out.png", _minimal_png())  # must not raise


def test_validate_artifact_rejects_fake_png():
    with pytest.raises(ArtifactValidationError, match="signature"):
        validate_artifact("out.png", b"not actually a png")


def test_validate_artifact_accepts_minimal_drawio():
    xml = b'<mxfile><diagram><mxGraphModel><root/></mxGraphModel></diagram></mxfile>'
    validate_artifact("out.drawio", xml)  # must not raise


def test_validate_artifact_rejects_drawio_doctype():
    xml = b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><mxfile></mxfile>'
    with pytest.raises(ArtifactValidationError, match="DOCTYPE"):
        validate_artifact("out.drawio", xml)


def test_validate_artifact_rejects_wrong_drawio_root():
    with pytest.raises(ArtifactValidationError, match="root"):
        validate_artifact("out.drawio", b"<notmxfile/>")


def test_validate_artifact_rejects_malformed_json():
    with pytest.raises(ArtifactValidationError):
        validate_artifact("engineer_report.json", b"{not valid json")


def test_validate_artifact_accepts_valid_json():
    validate_artifact("engineer_report.json", b'{"ok": true}')  # must not raise


def test_validate_artifact_rejects_non_utf8_dot():
    with pytest.raises(ArtifactValidationError):
        validate_artifact("out.dot", b"\xff\xfe not utf8")


# --- ModalSandboxRunner: live isolation check (skipped without credentials) --

_HAS_MODAL_CREDS = bool(os.environ.get("MODAL_TOKEN_ID")) and bool(os.environ.get("MODAL_TOKEN_SECRET"))


@pytest.mark.skipif(not _HAS_MODAL_CREDS, reason="MODAL_TOKEN_ID/MODAL_TOKEN_SECRET not set")
def test_modal_sandbox_blocks_network_and_secrets(tmp_path, monkeypatch):
    """Live end-to-end check: this is the actual security property the
    Modal migration exists for — a real render must not see host secrets
    and must not reach the network, not just declare the flags."""
    from runtime.sandbox.runners.modal_runner import ModalSandboxRunner

    monkeypatch.setenv("SOME_SECRET_KEY", "must-not-leak")
    (tmp_path / "diagram.py").write_text(
        "import os, socket\n"
        "print('KEY_ABSENT=', os.environ.get('SOME_SECRET_KEY') is None)\n"
        "try:\n"
        "    socket.create_connection(('8.8.8.8', 53), timeout=3)\n"
        "    print('NETWORK_BLOCKED=False')\n"
        "except OSError:\n"
        "    print('NETWORK_BLOCKED=True')\n",
        encoding="utf-8",
    )
    result = ModalSandboxRunner(RenderLimits()).render(tmp_path, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "KEY_ABSENT= True" in result.stdout
    assert "NETWORK_BLOCKED=True" in result.stdout
