"""build_agent() — assembles the compiled main deep agent + its five subagents."""

from __future__ import annotations

import logging
import os

from deepagents import create_deep_agent
from langgraph.checkpoint.memory import MemorySaver

from backends import (
    GLOBAL_MEMORY_PATH,
    LOCAL_ICONS,
    LOCAL_MANIFEST,
    MEMORY_PATH,
    make_local_backend,
)
from context import SessionContext
from prompts import build_pretty_system_prompt, build_system_prompt
from tools import GATE_TOOL_NAMES, MAIN_TOOLS

from .constants import DEFAULT_MODEL, DEFAULT_STYLE, MAIN_SKILL_PATHS
from .harness import _set_general_purpose_enabled
from .middleware import _middleware
from .streaming import _StreamingSubAgentRunnable
from .subagents import build_subagent_specs

logger = logging.getLogger(__name__)


def build_agent(model: str | None = None, *, style: str = DEFAULT_STYLE,
                checkpointer=None, store=None):
    """Create the diagram deep agent (a compiled LangGraph graph).

    Pass ``checkpointer``/``store`` from :func:`agent.persistence.make_persistence`
    for durable sessions; if omitted, an in-memory checkpointer is used (dev only).

    Subagents are declared as ``SubagentSpec``s (see ``agent/subagents/``) and
    compiled uniformly in the loop below into ``CompiledSubAgent`` TypedDicts,
    each wrapped in ``_StreamingSubAgentRunnable`` so its internal tool calls
    stream through the outer graph's ``"custom"`` mode and appear as live
    ACTIVITY events.

    *model* overrides the 'main' role in config.yaml; every subagent role
    always comes from config.yaml (falling back to the resolved main model).
    """
    from config import get_model, get_system_prompt_prefix, make_llm, supports_structured_output

    main_model = model or get_model("main", DEFAULT_MODEL)
    # LLMToolSelectorMiddleware calls main_model.with_structured_output() to pick
    # tools; only enable it when the provider actually supports that (mimo does
    # not — see config.supports_structured_output). Still AND-gated by the
    # MAIN_TOOL_SELECTOR env flag inside _middleware().
    _selector_ok = supports_structured_output(main_model)

    # Virtual workspace root the prompts refer to. MUST be the virtual "/workspace"
    # mount (see make_local_backend's "/workspace/" route), NOT the absolute host path
    # str(WORKSPACE): under virtual_mode=True the filesystem tools re-root every path
    # under the per-thread current_workspace(), so an absolute host path baked into a
    # prompt resolves to a non-existent nested dir (the ppt_generator 404 storm).
    workdir = "/workspace"
    prefix = get_system_prompt_prefix(main_model)
    if style == "pretty":
        system_prompt = prefix + build_pretty_system_prompt(workdir, LOCAL_ICONS, LOCAL_MANIFEST)
    else:
        system_prompt = prefix + build_system_prompt(workdir, LOCAL_ICONS, LOCAL_MANIFEST)

    if not os.getenv("TAVILY_API_KEY"):
        logger.warning(
            "TAVILY_API_KEY not set — web_research tool will return NO_API_KEY. "
            "Set TAVILY_API_KEY in .env to enable live tech-stack fact-checking."
        )

    # drawer's model quirk (vision_in_tools) drives its OWN vision relay AND
    # critic's (critic reviews the same rendered image via the same relay path,
    # so it needs the same workaround the drawer's model requires) — resolved
    # once here since building the spec list needs it before either model is known.
    drawer_model_for_relay = get_model("drawer", main_model)
    from config import vision_in_tools as _vision_in_tools
    drawer_vision_in_tools = _vision_in_tools(drawer_model_for_relay)
    # vision_relay: provider can see images in user messages but not tool messages.
    # Enable RENDER_INCLUDES_IMAGE so tools still return PNG data; InjectVisionAsUserEdit
    # will move the image from the ToolMessage into a synthetic HumanMessage.
    drawer_vision_relay = not drawer_vision_in_tools
    if drawer_vision_relay:
        os.environ["RENDER_INCLUDES_IMAGE"] = "1"
        logger.info(
            "Vision relay enabled for drawer model %s (images relayed via user message)",
            drawer_model_for_relay,
        )
    else:
        os.environ.setdefault("RENDER_INCLUDES_IMAGE", "1")

    llm = make_llm(main_model)
    backend = make_local_backend()

    specs = build_subagent_specs(
        workdir=workdir, icons_root=LOCAL_ICONS, manifest=LOCAL_MANIFEST,
        style=style, drawer_vision_relay=drawer_vision_relay,
    )

    # NO agent gets the implicit general-purpose subagent. wbs_planner used to
    # be the one exception (built first with GP enabled + a task_call_limit=3
    # cap), but a real 6M-token trace (2026-07-04) showed it delegating WBS work
    # to task(general-purpose) anyway — a stateless nested agent re-paying the
    # full context each call. wbs_planner now does ALL WBS work itself with its
    # own tools + the wbs-planning skill; GP could never do anything more (it
    # inherits the exact same toolset). See _set_general_purpose_enabled.
    role_models = {spec.name: get_model(spec.model_role, main_model) for spec in specs}
    _set_general_purpose_enabled(False, set(role_models.values()) | {main_model})

    logger.info(
        "build_agent  main=%s  style=%s  roles=%s",
        main_model, style, role_models,
    )

    compiled_subagents: list[dict] = []
    for spec in specs:
        role_model = role_models[spec.name]
        role_prefix = get_system_prompt_prefix(role_model)
        role_llm = make_llm(role_model)
        role_system_prompt = role_prefix + spec.prompt_builder(**spec.prompt_kwargs)
        compiled_subagents.append({
            "name": spec.name,
            "description": spec.description,
            "runnable": _StreamingSubAgentRunnable(
                create_deep_agent(
                    model=role_llm,
                    tools=spec.tools,
                    system_prompt=role_system_prompt,
                    backend=backend,
                    memory=[GLOBAL_MEMORY_PATH, MEMORY_PATH],
                    skills=spec.skills,
                    permissions=spec.permissions,
                    middleware=_middleware(
                        run_limit=spec.run_limit, agent_name=spec.name,
                        model=role_model, use_vision_relay=spec.use_vision_relay,
                    ),
                    store=store,
                ),
                spec.name,
            ),
        })

    # Each gate tool pauses for human review/approval before it runs.
    interrupt_on = {
        name: {"allowed_decisions": ["approve", "reject"]}
        for name in GATE_TOOL_NAMES
    }
    if checkpointer is None:
        checkpointer = MemorySaver()
    return create_deep_agent(
        model=llm,
        tools=MAIN_TOOLS,
        system_prompt=system_prompt,
        backend=backend,
        memory=[GLOBAL_MEMORY_PATH, MEMORY_PATH],
        skills=MAIN_SKILL_PATHS,
        subagents=compiled_subagents,
        middleware=_middleware(agent_name="main", model=main_model, use_tool_selector=_selector_ok,
                               use_phase_filter=True, use_drawer_revise_gate=True,
                               # Happy path ≈7 task calls; 2 rejection rounds ≈11.
                               task_call_limit=int(os.getenv("TASK_CALL_LIMIT", "12"))),
        checkpointer=checkpointer,
        store=store,
        interrupt_on=interrupt_on,
        # Per-session config (credentials, account ids, user email) reaches the
        # gate tools via runtime.context instead of the prompt; see context.py.
        context_schema=SessionContext,
    )
