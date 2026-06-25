"""Prompt builders for all diagram-agent subagents.

Backward-compatible re-exports — callers use `from prompts import build_*`
unchanged after this split from the monolithic prompts.py.
"""

from .critic_agent import build_critic_prompt
from .drawer_agent import build_drawer_prompt
from .icon_resolver_agent import build_icon_resolver_prompt
from .main_agent import build_pretty_system_prompt, build_system_prompt, paths
from .wbs_planner_agent import build_wbs_planner_prompt

__all__ = [
    "paths",
    "build_system_prompt",
    "build_pretty_system_prompt",
    "build_icon_resolver_prompt",
    "build_drawer_prompt",
    "build_critic_prompt",
    "build_wbs_planner_prompt",
]
