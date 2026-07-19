from __future__ import annotations

from session.sse import (
    _looks_like_tool_selection_prefix,
    _tool_selection_detail,
    _tool_selection_tools,
)


def test_tool_selection_json_is_detected():
    text = '{"tools": ["propose_diagram_brief", "web_research"]}'

    assert _tool_selection_tools(text) == ["propose_diagram_brief", "web_research"]


def test_tool_selection_json_fence_is_detected():
    text = '```json\n{"tools": ["analyze_architecture_requirements"]}\n```'

    assert _tool_selection_tools(text) == ["analyze_architecture_requirements"]


def test_non_selector_json_is_not_detected():
    assert _tool_selection_tools('{"tools": ["web_research"], "note": "show this"}') is None
    assert _tool_selection_tools('{"message": "hello"}') is None
    assert _tool_selection_tools('{"tools": [{"name": "web_research"}]}') is None


def test_stream_prefix_detection_is_limited_to_json_like_text():
    assert _looks_like_tool_selection_prefix('{"tools": [')
    assert _looks_like_tool_selection_prefix("```json\n{")
    assert not _looks_like_tool_selection_prefix("I will analyze the requirements.")


def test_tool_selection_detail_summarizes_progress():
    detail = _tool_selection_detail(["a", "b"])

    assert detail == "2 tool(s): a, b"
