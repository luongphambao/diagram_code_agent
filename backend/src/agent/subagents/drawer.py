"""drawer subagent: render-refine loop + drawio export."""

from __future__ import annotations

from prompts import build_drawer_prompt
from tools import DRAWER_TOOLS

from ..constants import DRAWER_SKILL_PATHS


def _drawer_subagent(workdir: str, icons_root: str, manifest: str, style: str) -> dict:
    """Config for the drawer subagent: render-refine loop + export (icons pre-resolved)."""
    return {
        "name": "drawer",
        "description": (
            "Renders the approved architecture blueprint into a production-quality "
            "diagram. Reads pre-resolved icon_plan.json, writes diagram code, "
            "render-refine loop (≤3), and drawio export. Returns ONLY a short text "
            "status — no images."
        ),
        "system_prompt": build_drawer_prompt(workdir, icons_root, manifest, style=style),
        "tools": DRAWER_TOOLS,
        "skills": DRAWER_SKILL_PATHS,
    }
