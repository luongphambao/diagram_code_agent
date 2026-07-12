"""icon_resolver subagent: batch node/icon resolution before drawing."""

from __future__ import annotations

from prompts import build_icon_resolver_prompt
from tools import ICON_RESOLVER_TOOLS


def _icon_resolver_subagent(workdir: str, icons_root: str, manifest: str) -> dict:
    """Config for the icon_resolver subagent: batch node/icon resolution before drawing."""
    return {
        "name": "icon_resolver",
        "description": (
            "Resolves all icon paths and built-in node class names for the approved "
            "blueprint. Reads render_spec.json, calls search_diagrams_nodes + "
            "resolve_icons in batch, writes icon_plan.json. Returns a short status."
        ),
        "system_prompt": build_icon_resolver_prompt(workdir, icons_root, manifest),
        "tools": ICON_RESOLVER_TOOLS,
    }
