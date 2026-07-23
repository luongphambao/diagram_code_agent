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
from runtime.sandbox.contracts import DEFAULT_DIAGRAM_OUTPUTS, RenderLimits, RenderResult
from runtime.sandbox.provider import SandboxConfigError, get_sandbox_runner
from runtime.sandbox.runners.base import SandboxRunner
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


# --- generalized "run code" primitive (improvement plan §B) -------------------
# render_diagram is one caller of SandboxRunner.render(); allowed_outputs lets
# a different tool (WBS re-estimation, data-analysis) declare its own output
# filenames instead of inheriting the diagram-render allowlist.


def test_default_diagram_outputs_matches_render_diagram_expectations():
    # A drift guard: if this list ever changes, render_diagram's explicit
    # `allowed_outputs=DEFAULT_DIAGRAM_OUTPUTS` pass-through changes with it —
    # this pins the exact set both runners fall back to.
    assert DEFAULT_DIAGRAM_OUTPUTS == (
        "out.png",
        "out.body.png",
        "out.dot",
        "out.drawio",
        "out.nodes.json",
        "out.slide.json",
        "out.native_stats.json",
    )


def test_both_runners_satisfy_the_sandbox_runner_protocol():
    from runtime.sandbox.runners.modal_runner import ModalSandboxRunner

    assert isinstance(LocalDevRunner(), SandboxRunner)
    assert isinstance(ModalSandboxRunner(), SandboxRunner)


def test_local_dev_runner_default_outputs_unchanged_when_omitted(tmp_path):
    """Not passing allowed_outputs at all must behave identically to passing
    DEFAULT_DIAGRAM_OUTPUTS explicitly — the back-compat guarantee every
    existing caller (render_diagram) relies on."""
    (tmp_path / "diagram.py").write_text("open('out.png','wb').write(b'not a real png')\n", encoding="utf-8")
    # out.png is in DEFAULT_DIAGRAM_OUTPUTS, so the fake PNG must fail
    # validation whether allowed_outputs is omitted or passed explicitly.
    with pytest.raises(ArtifactValidationError):
        LocalDevRunner().render(tmp_path, timeout=10)
    (tmp_path / "diagram.py").write_text("open('out.png','wb').write(b'not a real png')\n", encoding="utf-8")
    with pytest.raises(ArtifactValidationError):
        LocalDevRunner().render(tmp_path, timeout=10, allowed_outputs=DEFAULT_DIAGRAM_OUTPUTS)


def test_local_dev_runner_validates_a_custom_declared_output(tmp_path):
    """A non-diagram caller (e.g. a future WBS-recompute tool) declares its
    own output filename; that file gets the same untrusted-output validation
    treatment as out.png does today — this is the generalization's whole
    point, not just a wider allowlist."""
    (tmp_path / "script.py").write_text(
        "open('result.json','w').write('{not valid json')\n", encoding="utf-8"
    )
    with pytest.raises(ArtifactValidationError):
        LocalDevRunner().render(
            tmp_path, timeout=10, script_name="script.py", allowed_outputs=("result.json",)
        )


def test_local_dev_runner_ignores_files_outside_allowed_outputs(tmp_path):
    """A file the script writes that isn't in allowed_outputs is simply not
    considered — no validation, no error — matching ModalSandboxRunner's
    "only allowlisted names ever leave the sandbox" behavior."""
    (tmp_path / "script.py").write_text(
        "open('scratch.tmp','w').write('garbage, never validated')\n"
        "open('result.json','w').write('{\"ok\": true}')\n",
        encoding="utf-8",
    )
    result = LocalDevRunner().render(
        tmp_path, timeout=10, script_name="script.py", allowed_outputs=("result.json",)
    )
    assert result.returncode == 0


def test_local_dev_runner_missing_declared_output_is_not_an_error(tmp_path):
    """A script that doesn't produce every declared output shouldn't itself
    be a validation failure — the caller (e.g. render_diagram) is
    responsible for deciding whether a missing out.png means the render
    failed; the runner only validates what actually exists."""
    (tmp_path / "diagram.py").write_text("print('no files written')\n", encoding="utf-8")
    result = LocalDevRunner().render(tmp_path, timeout=10)
    assert result.returncode == 0


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
    xml = b"<mxfile><diagram><mxGraphModel><root/></mxGraphModel></diagram></mxfile>"
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


def test_validate_artifact_accepts_valid_csv():
    validate_artifact("result.csv", b"role,cost\nbackend,120\nfrontend,80\n")  # must not raise


def test_validate_artifact_rejects_non_utf8_csv():
    with pytest.raises(ArtifactValidationError):
        validate_artifact("result.csv", b"\xff\xfe not utf8")


def test_validate_artifact_rejects_empty_csv():
    with pytest.raises(ArtifactValidationError, match="empty"):
        validate_artifact("result.csv", b"")


def test_validate_artifact_rejects_oversized_csv():
    with pytest.raises(ArtifactValidationError, match="maximum size"):
        validate_artifact("result.csv", b"a" * 25_000_001)


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


# --- ModalSandboxRunner: prettygraph baked into the image (improvement plan §D) --


def test_prettygraph_dir_is_never_uploaded_from_workspace():
    """`_stage_helpers()` still writes prettygraph/*.py into the LOCAL
    per-thread workspace (LocalDevRunner needs that copy), but ModalSandboxRunner
    must skip re-uploading it file-by-file every render now that the same
    content is baked into the diagram image at build time — a workspace
    walk that ignored this would silently defeat the whole optimization."""
    from runtime.sandbox.runners.modal_runner import _SKIP_UPLOAD_DIR_NAMES

    assert "prettygraph" in _SKIP_UPLOAD_DIR_NAMES


@pytest.mark.skipif(not _HAS_MODAL_CREDS, reason="MODAL_TOKEN_ID/MODAL_TOKEN_SECRET not set")
def test_modal_sandbox_diagram_image_has_prettygraph_baked_in(tmp_path):
    """Live check that the optimization is actually correct, not just fast:
    a diagram.py that imports prettygraph must still work even though
    ModalSandboxRunner no longer uploads a workspace/prettygraph/ copy —
    proving the image-baked copy (add_local_dir in ModalSandboxRunner.__init__)
    is what the sandbox is actually importing from."""
    from runtime.sandbox.runners.modal_runner import ModalSandboxRunner

    assert not (tmp_path / "prettygraph").exists()
    (tmp_path / "diagram.py").write_text(
        "from prettygraph import Pretty\nprint('IMPORT_OK=', bool(Pretty))\n",
        encoding="utf-8",
    )
    result = ModalSandboxRunner(RenderLimits()).render(tmp_path, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "IMPORT_OK= True" in result.stdout
