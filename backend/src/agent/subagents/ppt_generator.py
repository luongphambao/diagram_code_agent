"""ppt_generator subagent: reads workspace context + writes out.pptx."""

from __future__ import annotations

from prompts import build_ppt_generator_prompt
from tools import PPT_GENERATOR_TOOLS

from ..constants import PPT_GENERATOR_SKILL_PATHS, _PPT_CALL_LIMIT
from .spec import SubagentSpec


def _ppt_generator_spec(*, workdir: str) -> SubagentSpec:
    """Spec for the ppt_generator subagent: read workspace context + write out.pptx."""
    return SubagentSpec(
        name="ppt_generator",
        description=(
            "Reads approved workspace artifacts (blueprint.json, diagram_brief.json, "
            "tech_stack.json, out.png) and generates out.pptx using the BnK proposal "
            "template.  Called BEFORE the generate_ppt_proposal gate so the main agent "
            "can pass rich defaults (title, subtitle, brand, sections) to the user. "
            "Returns a short status."
        ),
        model_role="ppt_generator",
        tools=PPT_GENERATOR_TOOLS,
        run_limit=_PPT_CALL_LIMIT,
        prompt_builder=build_ppt_generator_prompt,
        prompt_kwargs={"workdir": workdir},
        skills=PPT_GENERATOR_SKILL_PATHS,
    )
