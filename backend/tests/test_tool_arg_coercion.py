"""Regression tests for the generic tool-arg coercion middleware.

Reproduces the exact malformed tool calls observed in LangSmith traces
(2026-07-04, project diagram-agent): mimo-v2.5 passing list/dict args as
JSON-encoded strings — search_diagrams_nodes(queries='["vpn",...]'),
fit_labels(edge_labels='[...]'), draft_wbs_skeleton(ratios='{...}') — and the
deepagents builtin `ls` called with no `path`. Each one triggered a Pydantic
ValidationError whose ToolMessage echoed the full kwargs blob, producing
call/token retry storms.
"""

from typing import Optional

import pytest
from langchain_core.messages import ToolMessage
from pydantic import BaseModel

from tool_coercion import (
    ToolArgCoercionMiddleware,
    coerce_args,
    coerce_model_values,
    compact_invocation_error,
)
from tools import ICON_RESOLVER_TOOLS


# ── schema fixtures ──────────────────────────────────────────────────────────

class _Item(BaseModel):
    label: str
    sublabel: str = ""


class _Args(BaseModel):
    nodes: list[_Item] = []
    edge_labels: Optional[list[str]] = None
    ratios: Optional[dict] = None
    note: str = ""
    count: int = 0


class _FakeTool:
    def __init__(self, args_schema):
        self.args_schema = args_schema


class _FakeRequest:
    """Duck-typed stand-in for langgraph's ToolCallRequest."""

    def __init__(self, tool_call, tool=None):
        self.tool_call = tool_call
        self.tool = tool

    def override(self, **kw):
        return _FakeRequest(kw.get("tool_call", self.tool_call), self.tool)


def _run_middleware(tool_call, tool=None):
    """Run wrap_tool_call and capture the args the handler actually received."""
    mw = ToolArgCoercionMiddleware()
    seen = {}

    def handler(request):
        seen.update(request.tool_call.get("args") or {})
        return ToolMessage(content="ok", tool_call_id=tool_call.get("id", "t1"),
                           name=tool_call.get("name", "tool"))

    mw.wrap_tool_call(_FakeRequest(tool_call, tool), handler)
    return seen


# ── coerce_args: the exact LangSmith failures ────────────────────────────────

def test_list_of_str_passed_as_json_string():
    # fit_labels(edge_labels='["HTTPS", "OAuth 2.0"]')
    out = coerce_args({"edge_labels": '["HTTPS", "OAuth 2.0"]'}, _Args)
    assert out["edge_labels"] == ["HTTPS", "OAuth 2.0"]


def test_free_dict_passed_as_json_string():
    # draft_wbs_skeleton(ratios='{"ba_on_dev": 0.1, "qc_on_dev": 0.3}')
    out = coerce_args({"ratios": '{"ba_on_dev": 0.1, "qc_on_dev": 0.3}'}, _Args)
    assert out["ratios"] == {"ba_on_dev": 0.1, "qc_on_dev": 0.3}


def test_nested_model_list_as_json_string_and_numeric_dict():
    out = coerce_args({"nodes": '[{"label": "API"}, {"label": "DB"}]'}, _Args)
    assert [n["label"] for n in out["nodes"]] == ["API", "DB"]

    out = coerce_args({"nodes": {"0": {"label": "API"}, "1": {"label": "DB"}}}, _Args)
    assert [n["label"] for n in out["nodes"]] == ["API", "DB"]


def test_search_diagrams_nodes_real_schema():
    # search_diagrams_nodes(queries='["vpn", "azure", "teams"]') — real tool schema.
    tool = next(t for t in ICON_RESOLVER_TOOLS
                if getattr(t, "name", "") == "search_diagrams_nodes")
    out = coerce_args({"queries": '["vpn", "azure", "teams"]'}, tool.args_schema)
    assert out["queries"] == ["vpn", "azure", "teams"]
    tool.args_schema.model_validate(out)  # must now pass validation


def test_plain_str_field_never_json_parsed():
    prose = '{"looks": "like json"}'
    out = coerce_args({"note": prose}, _Args)
    assert out["note"] == prose


def test_well_formed_args_are_a_noop():
    args = {"nodes": [{"label": "API"}], "edge_labels": ["a"], "count": 3}
    assert coerce_args(dict(args), _Args) == args


def test_none_for_bare_list_becomes_empty():
    class Bare(BaseModel):
        items: list[str] = []
    assert coerce_args({"items": None}, Bare)["items"] == []


def test_coerce_model_values_usable_as_validator_body():
    values = coerce_model_values(_Args, {"edge_labels": '["x"]'})
    assert values["edge_labels"] == ["x"]
    assert _Args.model_validate(values).edge_labels == ["x"]


# ── middleware behavior ──────────────────────────────────────────────────────

def test_middleware_coerces_before_handler():
    seen = _run_middleware(
        {"name": "fit_labels", "id": "t1", "args": {"edge_labels": '["HTTPS"]'}},
        tool=_FakeTool(_Args),
    )
    assert seen["edge_labels"] == ["HTTPS"]


def test_middleware_ls_default_path():
    # ls called with no args at all (RC6: "path Field required").
    seen = _run_middleware({"name": "ls", "id": "t1", "args": {}})
    assert seen["path"] == "/"


def test_middleware_whole_args_as_json_string():
    seen = _run_middleware(
        {"name": "fit_labels", "id": "t1", "args": '{"edge_labels": ["a"]}'},
        tool=_FakeTool(_Args),
    )
    assert seen["edge_labels"] == ["a"]


def test_middleware_compacts_invocation_error():
    mw = ToolArgCoercionMiddleware()
    blob = "x" * 9000
    raw = (
        f"Error invoking tool 'fit_labels' with kwargs {{'edge_labels': '{blob}'}} "
        "with error:\n 1 validation error for fit_labels\nedge_labels\n"
        "  Input should be a valid list\n Please fix the error and try again."
    )

    def handler(request):
        return ToolMessage(content=raw, tool_call_id="t1", name="fit_labels",
                           status="error")

    result = mw.wrap_tool_call(
        _FakeRequest({"name": "fit_labels", "id": "t1", "args": {}}), handler)
    assert "edge_labels" in result.content
    assert blob not in result.content            # kwargs echo gone
    assert len(result.content) < 1200
    assert "never as quoted strings" in result.content


def test_middleware_leaves_normal_errors_alone():
    mw = ToolArgCoercionMiddleware()

    def handler(request):
        return ToolMessage(content="BUDGET_EXHAUSTED", tool_call_id="t1",
                           name="web_research", status="error")

    result = mw.wrap_tool_call(
        _FakeRequest({"name": "web_research", "id": "t1", "args": {}}), handler)
    assert result.content == "BUDGET_EXHAUSTED"


@pytest.mark.anyio
async def test_middleware_async_path():
    mw = ToolArgCoercionMiddleware()
    seen = {}

    async def handler(request):
        seen.update(request.tool_call.get("args") or {})
        return ToolMessage(content="ok", tool_call_id="t1", name="fit_labels")

    await mw.awrap_tool_call(
        _FakeRequest({"name": "fit_labels", "id": "t1",
                      "args": {"edge_labels": '["a", "b"]'}},
                     _FakeTool(_Args)),
        handler,
    )
    assert seen["edge_labels"] == ["a", "b"]
