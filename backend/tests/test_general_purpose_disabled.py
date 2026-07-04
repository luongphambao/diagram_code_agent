"""The implicit "general-purpose" subagent must be disabled for EVERY agent.

create_deep_agent() auto-adds a "general-purpose" subagent (and with it the
`task` tool) unless the harness profile for the agent's model disables it.
build_agent() disables it for all six models before any create_deep_agent
call. wbs_planner used to be the one exception (GP enabled + task cap 3), but
a real 6M-token trace (2026-07-04) showed it delegating WBS work to
task(general-purpose) — a stateless nested agent with the exact same toolset,
so pure waste. A regression here re-opens the retry escape hatch that once
burned 1.66M tokens (42% of a 4M-token run) via the drawer.
"""

import pytest

import agent as agent_module
from deepagents.profiles.harness.harness_profiles import _HARNESS_PROFILES


@pytest.fixture()
def fake_llm_keys(monkeypatch):
    """build_agent() instantiates real LLM clients; dummy keys satisfy them."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MIMO_API_KEY", "test-key")


def _gp_enabled_for(model_str: str):
    profile = _HARNESS_PROFILES.get(f"openai:{model_str}")
    gp = getattr(profile, "general_purpose_subagent", None) if profile else None
    return getattr(gp, "enabled", None)


def _tool_names(graph) -> set[str]:
    names: set[str] = set()
    for node in getattr(graph, "nodes", {}).values():
        bound = getattr(node, "bound", None)
        tools_by_name = getattr(bound, "tools_by_name", None)
        if tools_by_name:
            names |= set(tools_by_name)
    return names


def test_general_purpose_disabled_everywhere(monkeypatch, fake_llm_keys):
    real_create = agent_module.create_deep_agent
    snapshots: list[tuple[str, object]] = []
    graphs: list = []

    def recording_create(*args, **kwargs):
        model = kwargs.get("model")
        model_name = str(getattr(model, "model_name", None) or getattr(model, "model", "?"))
        snapshots.append((model_name, _gp_enabled_for(model_name)))
        graph = real_create(*args, **kwargs)
        graphs.append(graph)
        return graph

    monkeypatch.setattr(agent_module, "create_deep_agent", recording_create)
    main_graph = agent_module.build_agent()

    # 6 create_deep_agent calls: wbs_planner, 4 workers, then main.
    assert len(snapshots) == 6, snapshots
    # Every single one is built with general-purpose disabled.
    assert all(enabled is False for _, enabled in snapshots), snapshots

    # Behavioral check on the compiled graphs: only the MAIN graph exposes
    # `task` (for its five named subagents). No subagent — wbs_planner
    # included — may expose `task`.
    subagent_graphs = graphs[:5]
    assert "task" in _tool_names(main_graph)
    for subagent_graph in subagent_graphs:
        assert "task" not in _tool_names(subagent_graph)
