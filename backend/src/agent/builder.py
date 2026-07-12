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

from .constants import (
    DEFAULT_MODEL,
    DEFAULT_STYLE,
    MAIN_SKILL_PATHS,
    _CRITIC_CALL_LIMIT,
    _DRAWER_CALL_LIMIT,
    _ICON_CALL_LIMIT,
    _PPT_CALL_LIMIT,
    _WBS_CALL_LIMIT,
)
from .harness import _set_general_purpose_enabled
from .middleware import _middleware
from .streaming import _StreamingSubAgentRunnable
from .subagents import (
    _critic_subagent,
    _drawer_subagent,
    _icon_resolver_subagent,
    _ppt_generator_subagent,
    _wbs_planner_subagent,
)

logger = logging.getLogger(__name__)


def build_agent(model: str | None = None, *, style: str = DEFAULT_STYLE,
                checkpointer=None, store=None):
    """Create the diagram deep agent (a compiled LangGraph graph).

    Pass ``checkpointer``/``store`` from :func:`agent.persistence.make_persistence`
    for durable sessions; if omitted, an in-memory checkpointer is used (dev only).

    Subagents (icon_resolver, drawer, critic) are pre-compiled as
    ``CompiledSubAgent`` TypedDicts so deepagents uses our
    ``_StreamingSubAgentRunnable`` wrapper as-is.  This lets each subagent's
    internal tool calls stream through the outer graph's ``"custom"`` mode and
    appear as live ACTIVITY events.

    *model* overrides the 'main' role in config.yaml; icon_resolver/drawer/critic
    always come from config.yaml (falling back to the resolved main model).
    """
    from config import get_model, get_system_prompt_prefix, make_llm, supports_structured_output

    main_model           = model or get_model("main",          DEFAULT_MODEL)
    # LLMToolSelectorMiddleware calls main_model.with_structured_output() to pick
    # tools; only enable it when the provider actually supports that (mimo does
    # not — see config.supports_structured_output). Still AND-gated by the
    # MAIN_TOOL_SELECTOR env flag inside _middleware().
    _selector_ok         = supports_structured_output(main_model)
    icon_resolver_model  = get_model("icon_resolver",   main_model)
    drawer_model         = get_model("drawer",           main_model)
    critic_model         = get_model("critic",           main_model)
    wbs_planner_model    = get_model("wbs_planner",      main_model)
    ppt_generator_model  = get_model("ppt_generator",    main_model)

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

    icon_resolver_prefix  = get_system_prompt_prefix(icon_resolver_model)
    drawer_prefix         = get_system_prompt_prefix(drawer_model)
    critic_prefix         = get_system_prompt_prefix(critic_model)
    wbs_planner_prefix    = get_system_prompt_prefix(wbs_planner_model)
    ppt_generator_prefix  = get_system_prompt_prefix(ppt_generator_model)

    if not os.getenv("TAVILY_API_KEY"):
        logger.warning(
            "TAVILY_API_KEY not set — web_research tool will return NO_API_KEY. "
            "Set TAVILY_API_KEY in .env to enable live tech-stack fact-checking."
        )

    logger.info(
        "build_agent  main=%s  icon_resolver=%s  drawer=%s  critic=%s  style=%s",
        main_model, icon_resolver_model, drawer_model, critic_model, style,
    )

    from config import vision_in_tools as _vision_in_tools
    drawer_vision_in_tools = _vision_in_tools(drawer_model)
    # vision_relay: provider can see images in user messages but not tool messages.
    # Enable RENDER_INCLUDES_IMAGE so tools still return PNG data; InjectVisionAsUserEdit
    # will move the image from the ToolMessage into a synthetic HumanMessage.
    drawer_vision_relay = not drawer_vision_in_tools
    if drawer_vision_relay:
        os.environ["RENDER_INCLUDES_IMAGE"] = "1"
        logger.info(
            "Vision relay enabled for drawer model %s (images relayed via user message)",
            drawer_model,
        )
    else:
        os.environ.setdefault("RENDER_INCLUDES_IMAGE", "1")

    llm                 = make_llm(main_model)
    icon_resolver_llm   = make_llm(icon_resolver_model)
    drawer_llm          = make_llm(drawer_model)
    critic_llm          = make_llm(critic_model)
    wbs_planner_llm     = make_llm(wbs_planner_model)
    ppt_generator_llm   = make_llm(ppt_generator_model)
    backend = make_local_backend()

    # Pre-compile subagents so their internal steps are visible in the outer stream.
    icon_resolver_spec  = _icon_resolver_subagent(workdir, LOCAL_ICONS, LOCAL_MANIFEST)
    drawer_spec         = _drawer_subagent(workdir, LOCAL_ICONS, LOCAL_MANIFEST, style)
    critic_spec         = _critic_subagent(style)
    wbs_planner_spec    = _wbs_planner_subagent(workdir)
    ppt_generator_spec  = _ppt_generator_subagent(workdir)
    icon_resolver_spec["system_prompt"] = icon_resolver_prefix + icon_resolver_spec["system_prompt"]
    drawer_spec["system_prompt"]        = drawer_prefix + drawer_spec["system_prompt"]
    critic_spec["system_prompt"]        = critic_prefix + critic_spec["system_prompt"]
    wbs_planner_spec["system_prompt"]   = wbs_planner_prefix + wbs_planner_spec["system_prompt"]
    ppt_generator_spec["system_prompt"] = ppt_generator_prefix + ppt_generator_spec["system_prompt"]

    # NO agent gets the implicit general-purpose subagent. wbs_planner used to
    # be the one exception (built first with GP enabled + a task_call_limit=3
    # cap), but a real 6M-token trace (2026-07-04) showed it delegating WBS work
    # to task(general-purpose) anyway — a stateless nested agent re-paying the
    # full context each call. wbs_planner now does ALL WBS work itself with its
    # own tools + the wbs-planning skill; GP could never do anything more (it
    # inherits the exact same toolset). See _set_general_purpose_enabled.
    _set_general_purpose_enabled(False, {
        wbs_planner_model, icon_resolver_model, drawer_model, critic_model,
        ppt_generator_model, main_model,
    })
    wbs_planner_compiled: dict = {
        "name": wbs_planner_spec["name"],
        "description": wbs_planner_spec["description"],
        "runnable": _StreamingSubAgentRunnable(
            create_deep_agent(
                model=wbs_planner_llm,
                tools=wbs_planner_spec["tools"],
                system_prompt=wbs_planner_spec["system_prompt"],
                backend=backend,
                memory=[GLOBAL_MEMORY_PATH, MEMORY_PATH],
                skills=wbs_planner_spec.get("skills"),
                middleware=_middleware(run_limit=_WBS_CALL_LIMIT, agent_name="wbs_planner",
                                     model=wbs_planner_model),
                store=store,
            ),
            "wbs_planner",
        ),
    }
    icon_resolver_compiled: dict = {
        "name": icon_resolver_spec["name"],
        "description": icon_resolver_spec["description"],
        "runnable": _StreamingSubAgentRunnable(
            create_deep_agent(
                model=icon_resolver_llm,
                tools=icon_resolver_spec["tools"],
                system_prompt=icon_resolver_spec["system_prompt"],
                backend=backend,
                memory=[GLOBAL_MEMORY_PATH, MEMORY_PATH],
                middleware=_middleware(run_limit=_ICON_CALL_LIMIT, agent_name="icon_resolver",
                                     model=icon_resolver_model),
                store=store,
            ),
            "icon_resolver",
        ),
    }
    drawer_compiled: dict = {
        "name": drawer_spec["name"],
        "description": drawer_spec["description"],
        "runnable": _StreamingSubAgentRunnable(
            create_deep_agent(
                model=drawer_llm,
                tools=drawer_spec["tools"],
                system_prompt=drawer_spec["system_prompt"],
                backend=backend,
                memory=[GLOBAL_MEMORY_PATH, MEMORY_PATH],
                skills=drawer_spec.get("skills"),
                middleware=_middleware(run_limit=_DRAWER_CALL_LIMIT, agent_name="drawer",
                                     model=drawer_model, use_vision_relay=drawer_vision_relay),
                store=store,
            ),
            "drawer",
        ),
    }
    critic_compiled: dict = {
        "name": critic_spec["name"],
        "description": critic_spec["description"],
        "runnable": _StreamingSubAgentRunnable(
            create_deep_agent(
                model=critic_llm,
                tools=critic_spec["tools"],
                system_prompt=critic_spec["system_prompt"],
                backend=backend,
                memory=[GLOBAL_MEMORY_PATH, MEMORY_PATH],
                middleware=_middleware(run_limit=_CRITIC_CALL_LIMIT, agent_name="critic",
                                     model=critic_model, use_vision_relay=drawer_vision_relay),
                store=store,
            ),
            "critic",
        ),
    }
    ppt_generator_compiled: dict = {
        "name": ppt_generator_spec["name"],
        "description": ppt_generator_spec["description"],
        "runnable": _StreamingSubAgentRunnable(
            create_deep_agent(
                model=ppt_generator_llm,
                tools=ppt_generator_spec["tools"],
                system_prompt=ppt_generator_spec["system_prompt"],
                backend=backend,
                memory=[GLOBAL_MEMORY_PATH, MEMORY_PATH],
                skills=ppt_generator_spec.get("skills"),
                middleware=_middleware(run_limit=_PPT_CALL_LIMIT, agent_name="ppt_generator",
                                     model=ppt_generator_model),
                store=store,
            ),
            "ppt_generator",
        ),
    }

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
        subagents=[
            icon_resolver_compiled, drawer_compiled, critic_compiled,
            wbs_planner_compiled, ppt_generator_compiled,
        ],
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
