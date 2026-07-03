"""The implicit "general-purpose" subagent must be disabled for every agent
except wbs_planner.

create_deep_agent() auto-adds a "general-purpose" subagent (and with it the
`task` tool) unless the harness profile for the agent's model disables it.
build_agent() toggles that profile around each create_deep_agent call:
wbs_planner is built first with general-purpose enabled (unchanged behavior),
then the toggle flips to disabled for icon_resolver/drawer/critic/
ppt_generator and the main agent. A regression here re-opens the drawer's
task(general-purpose) retry escape hatch that once burned 1.66M tokens
(42% of a 4M-token run).
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


def test_general_purpose_toggle_order(monkeypatch, fake_llm_keys):
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

    # 6 create_deep_agent calls: wbs_planner first, then the 4 workers, main last.
    assert len(snapshots) == 6, snapshots
    # wbs_planner keeps the default general-purpose subagent (enabled=True).
    assert snapshots[0][1] is True, snapshots
    # Everyone built after the flip — workers and main — has it disabled.
    assert all(enabled is False for _, enabled in snapshots[1:]), snapshots

    # Behavioral check on the compiled graphs: the wbs_planner graph keeps the
    # `task` tool (via its auto-added general-purpose subagent) and so does the
    # main graph (for its five named subagents); no other worker graph may
    # expose `task`.
    wbs_graph, worker_graphs = graphs[0], graphs[1:5]
    assert "task" in _tool_names(wbs_graph)
    assert "task" in _tool_names(main_graph)
    for worker_graph in worker_graphs:
        assert "task" not in _tool_names(worker_graph)
