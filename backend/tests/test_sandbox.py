"""Direct unit tests for runtime.sandbox — the render-script execution boundary
extracted from tools/rendering_tools.py in the Stage 5 refactor.

tools/rendering_tools.py's own tests (test_drawer_streamline.py,
test_agent_run_limits.py) already exercise this code end-to-end through the
render_diagram tool; these tests instead pin the sandbox module's own
contract directly, independent of the tool wrapper.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from runtime.sandbox.guards import _audit_code
from runtime.sandbox.render_exec import run_render


def test_audit_code_passes_clean_script():
    code = (
        'from diagrams import Diagram\n'
        'with Diagram("x", filename="out", outformat=["png", "dot"], show=False):\n'
        '    pass\n'
    )
    result = _audit_code(code)
    assert result["verdict"] == "PASS"
    assert result["findings"] == []


def test_audit_code_blocks_missing_filename_and_outformat():
    code = 'from diagrams import Diagram\nwith Diagram("x", show=False):\n    pass\n'
    result = _audit_code(code)
    assert result["verdict"] == "REVISE"
    rules = {f["rule"] for f in result["findings"]}
    assert "output_filename" in rules
    assert "output_format" in rules


def test_run_render_executes_script_in_workspace(tmp_path):
    (tmp_path / "diagram.py").write_text(
        "open('marker.txt', 'w').write('ran')\n", encoding="utf-8"
    )
    proc = run_render(tmp_path, timeout=10)
    assert proc.returncode == 0
    assert (tmp_path / "marker.txt").read_text(encoding="utf-8") == "ran"


def test_run_render_captures_nonzero_exit_and_stderr(tmp_path):
    (tmp_path / "diagram.py").write_text(
        "import sys\nsys.stderr.write('boom')\nsys.exit(1)\n", encoding="utf-8"
    )
    proc = run_render(tmp_path, timeout=10)
    assert proc.returncode == 1
    assert "boom" in proc.stderr


def test_run_render_raises_timeout_expired(tmp_path):
    (tmp_path / "diagram.py").write_text(
        "import time\ntime.sleep(5)\n", encoding="utf-8"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_render(tmp_path, timeout=1)


def test_run_render_uses_current_interpreter_and_cwd(tmp_path, monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_render(tmp_path, timeout=5, script_name="diagram.py")
    assert captured["cmd"] == [sys.executable, "diagram.py"]
    assert captured["cwd"] == str(tmp_path)
