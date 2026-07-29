"""brd_writer subagent: draft the BRD outline + section content."""

from __future__ import annotations

from deepagents.middleware.filesystem import FilesystemPermission

from prompts import build_brd_writer_prompt
from tools import BRD_WRITER_TOOLS

from ..constants import BRD_WRITER_SKILL_PATHS, _BRD_CALL_LIMIT
from .spec import SubagentSpec

# out.brd.docx / brd_revisions/ are the MAIN agent's own gated tools' output —
# brd_writer only ever drafts brd_outline_draft.json / brd_sections/*.json.
# Same rationale as icon_resolver's _ICON_PLAN_WRITE_DENY: every deepagents
# subagent gets the full filesystem toolset regardless of its declared `tools`
# list, so this must be enforced at the permission layer, not by prompt text.
_BRD_DOCX_WRITE_DENY = FilesystemPermission(
    operations=["write"],
    paths=["/workspace/out.brd.docx", "/workspace/brd_revisions/*"],
    mode="deny",
)


def _brd_writer_spec(*, workdir: str) -> SubagentSpec:
    """Spec for the brd_writer subagent: draft the BRD outline/content, never
    touch out.brd.docx directly — the main agent generates/patches it through
    its own gated tools once a draft is reviewed.
    """
    return SubagentSpec(
        name="brd_writer",
        description=(
            "Drafts a section-by-section BRD outline (fill/keep/skip) and the content "
            "for each 'fill' section, from the approved solution context (analysis, "
            "brief, tech stack, blueprint, WBS, CSM). Writes brd_outline_draft.json and "
            "brd_sections/<id>.json. Returns a short status — the MAIN agent runs the "
            "propose/generate/edit gates."
        ),
        model_role="brd_writer",
        tools=BRD_WRITER_TOOLS,
        run_limit=_BRD_CALL_LIMIT,
        prompt_builder=build_brd_writer_prompt,
        prompt_kwargs={"workdir": workdir},
        skills=BRD_WRITER_SKILL_PATHS,
        permissions=[_BRD_DOCX_WRITE_DENY],
    )
