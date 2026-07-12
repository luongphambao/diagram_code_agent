"""SubagentSpec — a declarative description of one subagent role.

``agent.builder.build_agent`` iterates a list of these (one per role) and
compiles each identically: resolve the role's model from config.yaml, build
its system prompt, wrap it in ``_StreamingSubAgentRunnable``. Adding a new
subagent role means adding one spec-factory function here + one prompt
builder + one ``*_TOOLS`` list — no changes to the compile loop itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class SubagentSpec:
    """Declarative config for one subagent; compiled uniformly by build_agent().

    ``model_role`` is the config.yaml role key (``get_model(model_role,
    main_model)``); ``prompt_builder`` is called as
    ``prompt_builder(**prompt_kwargs)`` to produce the raw system prompt
    (the provider prefix from ``get_system_prompt_prefix`` is prepended by
    the compile loop, not baked into the spec). ``run_limit`` is the
    resolved per-role model-call ceiling (an int from agent/constants.py —
    already env-resolved at import time, so the spec itself stays a plain
    data holder with no env/config coupling beyond the role key).
    """

    name: str
    description: str
    model_role: str
    tools: list
    run_limit: int
    prompt_builder: Callable[..., str]
    prompt_kwargs: dict = field(default_factory=dict)
    skills: list[str] | None = None
    use_vision_relay: bool = False
