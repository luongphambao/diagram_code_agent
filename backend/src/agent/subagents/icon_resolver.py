"""icon_resolver subagent: batch node/icon resolution before drawing."""

from __future__ import annotations

from deepagents.middleware.filesystem import FilesystemPermission

from prompts import build_icon_resolver_prompt
from tools import ICON_RESOLVER_TOOLS

from ..constants import _ICON_CALL_LIMIT
from .spec import SubagentSpec

# icon_plan.json must only ever be written by resolve_icons/update_icon_plan_entry
# (both run in-process, zero LLM turns — see tools/icon_tools.py). The prompt
# says "NEVER write_file/edit_file on icon_plan.json", but every deepagents
# subagent gets the full filesystem toolset regardless of its declared `tools`
# list, so that rule was prompt-only. A real trace showed the model defecting
# into a 32x edit_file / 19x read_file / 6x grep manual loop on this exact file
# instead — ~40 model calls / ~1M tokens before the hard call-limit cut it off.
# Denying at the permission layer turns the tool call into an immediate error
# instead of a silent, budget-burning success.
_ICON_PLAN_WRITE_DENY = FilesystemPermission(
    operations=["write"],
    paths=["/workspace/icon_plan.json"],
    mode="deny",
)


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
        permissions=[_ICON_PLAN_WRITE_DENY],
    )
