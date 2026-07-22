"""drawer subagent: render-refine loop + drawio export."""

from __future__ import annotations

from prompts import build_drawer_prompt
from tools import DRAWER_TOOLS

from ..constants import DRAWER_SKILL_PATHS, _DRAWER_CALL_LIMIT
from .spec import SubagentSpec


def _drawer_spec(
    *, workdir: str, icons_root: str, manifest: str, style: str, use_vision_relay: bool
) -> SubagentSpec:
    """Spec for the drawer subagent: render-refine loop + export (icons pre-resolved)."""
    return SubagentSpec(
        name="drawer",
        description=(
            "Renders the approved architecture blueprint into a production-quality "
            "diagram. Reads pre-resolved icon_plan.json, writes diagram code, "
            "render-refine loop (≤3), and drawio export. Returns ONLY a short text "
            "status — no images."
        ),
        model_role="drawer",
        tools=DRAWER_TOOLS,
        run_limit=_DRAWER_CALL_LIMIT,
        prompt_builder=build_drawer_prompt,
        prompt_kwargs={"workdir": workdir, "icons_root": icons_root, "manifest": manifest, "style": style},
        skills=DRAWER_SKILL_PATHS,
        use_vision_relay=use_vision_relay,
    )
