"""Trivial no-op graph — the spike only needs *something* under `graphs` in
langgraph.json for the deployment to build; the real test surface is the
custom FastAPI routes mounted via `http.app` in app.py.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph


class State(TypedDict):
    messages: list


def _noop(state: State) -> State:
    return state


_builder = StateGraph(State)
_builder.add_node("noop", _noop)
_builder.set_entry_point("noop")
_builder.add_edge("noop", END)

graph = _builder.compile()
