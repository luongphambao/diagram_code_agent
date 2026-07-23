"""run_python — the sandboxed code-exec primitive (improvement plan §C).

Uses SANDBOX_PROVIDER=local (LocalDevRunner, real subprocess, no Modal
credentials needed) so these run in CI. The live Modal isolation properties
(block_network, secrets=[]) are already covered by
test_sandbox_runners.py's live Modal test; this file covers run_python's own
behavior: budget cap, output declaration, tool_call_id plumbing, and that it
sits on WBS_PLANNER_TOOLS (not the main agent) per the improvement plan's
scoping decision.
"""

import contextvars

import backends
from tools import WBS_PLANNER_TOOLS
from tools.code_interpreter import _INTERPRETER_COUNT_FILE, run_python
from tools.constants import INTERPRETER_CALL_HARD_CAP


def _bind(monkeypatch, ws):
    ws.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends,
        "_current_workspace",
        contextvars.ContextVar("current_workspace", default=ws),
    )


def _local(monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVIDER", "local")
    monkeypatch.setenv("APP_ENV", "development")


def test_run_python_is_attached_to_wbs_planner_and_main_agent():
    # improvement plan §C: S1 (WBS re-estimate) scoped run_python to wbs_planner
    # only. §C-S2 (analyze uploaded .xlsx/.csv — a general capability unrelated
    # to WBS) added it to the main agent too. Other subagents still don't get it.
    from tools import MAIN_TOOLS

    assert "run_python" in [t.name for t in WBS_PLANNER_TOOLS]
    assert "run_python" in [t.name for t in MAIN_TOOLS]


def test_run_python_produces_a_declared_output(tmp_path, monkeypatch):
    _local(monkeypatch)
    _bind(monkeypatch, tmp_path / "ws")

    msg = run_python.func(
        code="open('result.json', 'w').write('{\"ok\": true}')",
        declared_outputs=["result.json"],
        tool_call_id="tc-1",
    )
    assert msg.status == "success"
    assert "Produced: result.json" in msg.content
    assert (tmp_path / "ws" / "result.json").read_text(encoding="utf-8") == '{"ok": true}'


def test_run_python_reports_missing_declared_output(tmp_path, monkeypatch):
    _local(monkeypatch)
    _bind(monkeypatch, tmp_path / "ws")

    msg = run_python.func(
        code="pass  # writes nothing",
        declared_outputs=["never_written.json"],
        tool_call_id="tc-2",
    )
    assert msg.status == "success"  # exit 0 — the script itself didn't fail
    assert "NOT produced" in msg.content
    assert "never_written.json" in msg.content


def test_run_python_can_read_an_existing_workspace_file(tmp_path, monkeypatch):
    """The core mechanic apply_wbs_reestimate depends on: the sandboxed
    script reads wbs.json (or any file already in the workspace) and writes
    a NEW filename — never overwrites the input in place."""
    _local(monkeypatch)
    ws = tmp_path / "ws"
    _bind(monkeypatch, ws)
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "input.json").write_text('{"n": 21}', encoding="utf-8")

    msg = run_python.func(
        code=(
            "import json\n"
            "data = json.load(open('input.json'))\n"
            "json.dump({'n': data['n'] * 2}, open('output.json', 'w'))\n"
        ),
        declared_outputs=["output.json"],
        tool_call_id="tc-3",
    )
    assert msg.status == "success"
    import json as _json

    assert _json.loads((ws / "output.json").read_text(encoding="utf-8")) == {"n": 42}


def test_run_python_reports_script_failure(tmp_path, monkeypatch):
    _local(monkeypatch)
    _bind(monkeypatch, tmp_path / "ws")

    msg = run_python.func(
        code="raise ValueError('boom')",
        declared_outputs=[],
        tool_call_id="tc-4",
    )
    assert msg.status == "error"
    assert "boom" in msg.content


def test_run_python_enforces_call_hard_cap(tmp_path, monkeypatch):
    _local(monkeypatch)
    ws = tmp_path / "ws"
    _bind(monkeypatch, ws)
    ws.mkdir(parents=True, exist_ok=True)
    _INTERPRETER_COUNT_FILE.write_text(f'{{"count": {INTERPRETER_CALL_HARD_CAP}}}', encoding="utf-8")

    msg = run_python.func(code="pass", declared_outputs=[], tool_call_id="tc-5")
    assert msg.status == "error"
    assert "BUDGET EXHAUSTED" in msg.content
