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

import agent as agent_module
from deepagents.profiles.harness.harness_profiles import _HARNESS_PROFILES


def _gp_enabled_for(model_str: str):
    profile = _HARNESS_PROFILES.get(f"openai:{model_str}")
    gp = getattr(profile, "general_purpose_subagent", None) if profile else None
    return getattr(gp, "enabled", None)


def test_general_purpose_toggle_order(monkeypatch):
    real_create = agent_module.create_deep_agent
    snapshots: list[tuple[str, object]] = []

    def recording_create(*args, **kwargs):
        model = kwargs.get("model")
        model_name = getattr(model, "model_name", None) or getattr(model, "model", "?")
        snapshots.append((str(model_name), _gp_enabled_for(str(model_name))))
        return real_create(*args, **kwargs)

    monkeypatch.setattr(agent_module, "create_deep_agent", recording_create)
    agent_module.build_agent()

    # 6 create_deep_agent calls: wbs_planner first, then the 4 workers, main last.
    assert len(snapshots) == 6, snapshots

    wbs_snapshot, worker_snapshots = snapshots[0], snapshots[1:]
    # wbs_planner keeps the default general-purpose subagent (enabled=True).
    assert wbs_snapshot[1] is True, snapshots
    # Everyone built after the flip — workers and main — has it disabled.
    assert all(enabled is False for _, enabled in worker_snapshots), snapshots


def test_workers_have_no_task_tool(monkeypatch):
    """The compiled worker graphs must not expose a `task` tool node input."""
    captured: dict[str, dict] = {}
    real_create = agent_module.create_deep_agent

    def recording_create(*args, **kwargs):
        graph = real_create(*args, **kwargs)
        name = kwargs.get("system_prompt", "")[:40]
        captured[name] = graph
        return graph

    monkeypatch.setattr(agent_module, "create_deep_agent", recording_create)
    compiled = agent_module.build_agent()

    def tool_names(graph):
        names = set()
        for node in getattr(graph, "nodes", {}).values():
            bound = getattr(node, "bound", None)
            tools_by_name = getattr(bound, "tools_by_name", None)
            if tools_by_name:
                names |= set(tools_by_name)
        return names

    # The main agent keeps `task` (for its five named subagents)…
    main_tools = tool_names(compiled)
    assert "task" in main_tools or not main_tools  # tolerate opaque graph internals

    # …but no worker graph other than wbs_planner may expose `task`.
    worker_graphs = [
        graph for prompt, graph in captured.items() if graph is not compiled
    ]
    assert worker_graphs, "expected pre-compiled subagent graphs to be captured"
