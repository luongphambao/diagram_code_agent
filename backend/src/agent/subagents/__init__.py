"""Subagent config factories — one per role. Each returns a plain dict consumed
by ``agent.builder.build_agent`` to construct a ``CompiledSubAgent``.
"""

from __future__ import annotations

from .critic import _critic_subagent
from .drawer import _drawer_subagent
from .icon_resolver import _icon_resolver_subagent
from .ppt_generator import _ppt_generator_subagent
from .wbs_planner import _wbs_planner_subagent

__all__ = [
    "_critic_subagent",
    "_drawer_subagent",
    "_icon_resolver_subagent",
    "_ppt_generator_subagent",
    "_wbs_planner_subagent",
]
