from __future__ import annotations

from types import SimpleNamespace

from agent.middleware import SafeLLMToolSelectorMiddleware
from agent.middleware.phase_filter import PhaseToolFilterMiddleware


class _Tool:
    def __init__(self, name: str):
        self.name = name


def test_phase_filter_preserves_deep_agent_builtins(monkeypatch, tmp_path):
    monkeypatch.setattr("backends.current_workspace", lambda: tmp_path)

    tools = [
        _Tool("read_file"),
        _Tool("ls"),
        _Tool("glob"),
        _Tool("grep"),
        _Tool("task"),
        _Tool("write_todos"),
        _Tool("propose_diagram_brief"),
        _Tool("finalize_diagram"),
    ]

    names = {tool.name for tool in PhaseToolFilterMiddleware()._filtered_tools(tools)}

    assert {"read_file", "ls", "glob", "grep", "task", "write_todos"} <= names
    assert "propose_diagram_brief" in names
    assert "finalize_diagram" not in names


def test_safe_tool_selector_intersects_always_include_with_request_tools():
    middleware = SafeLLMToolSelectorMiddleware(
        max_tools=20,
        always_include=["read_file", "task", "write_todos", "finalize_diagram"],
    )
    request = SimpleNamespace(tools=[_Tool("read_file"), _Tool("web_research")])

    selector = middleware._selector(request)

    assert selector.always_include == ["read_file"]
