"""icon_resolver subagent: batch node/icon resolution before drawing."""

from __future__ import annotations

from prompts import build_icon_resolver_prompt
from tools import ICON_RESOLVER_TOOLS

from ..constants import _ICON_CALL_LIMIT
from .spec import SubagentSpec


def _icon_resolver_spec(*, workdir: str, icons_root: str, manifest: str) -> SubagentSpec:
    """Spec for the icon_resolver subagent: batch node/icon resolution before drawing."""
    return SubagentSpec(
        name="icon_resolver",
        description=(
            "Resolves all icon paths and built-in node class names for the approved "
            "blueprint. Reads render_spec.json, calls search_diagrams_nodes + "
            "resolve_icons in batch, writes icon_plan.json. Returns a short status."
        ),
        model_role="icon_resolver",
        tools=ICON_RESOLVER_TOOLS,
        run_limit=_ICON_CALL_LIMIT,
        prompt_builder=build_icon_resolver_prompt,
        prompt_kwargs={"workdir": workdir, "icons_root": icons_root, "manifest": manifest},
    )
