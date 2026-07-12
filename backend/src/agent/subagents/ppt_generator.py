"""ppt_generator subagent: reads workspace context + writes out.pptx."""

from __future__ import annotations

from prompts import build_ppt_generator_prompt
from tools import PPT_GENERATOR_TOOLS

from ..constants import PPT_GENERATOR_SKILL_PATHS


def _ppt_generator_subagent(workdir: str) -> dict:
    """Config for the ppt_generator subagent: read workspace context + write out.pptx."""
    return {
        "name": "ppt_generator",
        "description": (
            "Reads approved workspace artifacts (blueprint.json, diagram_brief.json, "
            "tech_stack.json, out.png) and generates out.pptx using the BnK proposal "
            "template.  Called BEFORE the generate_ppt_proposal gate so the main agent "
            "can pass rich defaults (title, subtitle, brand, sections) to the user. "
            "Returns a short status."
        ),
        "system_prompt": build_ppt_generator_prompt(workdir),
        "tools": PPT_GENERATOR_TOOLS,
        "skills": PPT_GENERATOR_SKILL_PATHS,
    }
