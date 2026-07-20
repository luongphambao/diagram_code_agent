"""Subagent registry: one SubagentSpec-factory per role. ``build_subagent_specs``
takes the runtime-known values (workdir, icon paths, style, the drawer's
vision-relay decision) and returns the ordered list ``agent.builder.build_agent``
compiles uniformly.

To add a subagent: write one ``_role_spec()`` factory returning a
``SubagentSpec`` (see spec.py), one prompt builder in ``prompts/``, one
``*_TOOLS`` list in ``tools/__init__.py``, then append it to the list built
here — no changes needed to the compile loop in ``agent/builder.py``.
"""

from __future__ import annotations

from .critic import _critic_spec
from .drawer import _drawer_spec
from .icon_resolver import _icon_resolver_spec
from .ppt_generator import _ppt_generator_spec
from .spec import SubagentSpec
from .wbs_planner import _wbs_planner_spec

__all__ = ["SubagentSpec", "build_subagent_specs"]


def build_subagent_specs(
    *,
    workdir: str,
    icons_root: str,
    manifest: str,
    style: str,
    drawer_vision_relay: bool,
) -> list[SubagentSpec]:
    """Ordered specs for every subagent role, in the order they're compiled.

    Order matters only for the streaming/log presentation, not correctness —
    kept identical to the original hand-written sequence (icon_resolver,
    drawer, critic, wbs_planner, ppt_generator) for a minimal diff.
    """
    return [
        _icon_resolver_spec(workdir=workdir, icons_root=icons_root, manifest=manifest),
        _drawer_spec(workdir=workdir, icons_root=icons_root, manifest=manifest,
                    style=style, use_vision_relay=drawer_vision_relay),
        _critic_spec(style=style, use_vision_relay=drawer_vision_relay),
        _wbs_planner_spec(workdir=workdir),
        _ppt_generator_spec(workdir=workdir),
    ]
