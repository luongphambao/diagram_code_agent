"""wbs_planner subagent: decompose + estimate the WBS."""

from __future__ import annotations

from prompts import build_wbs_planner_prompt
from tools import WBS_PLANNER_TOOLS

from ..constants import WBS_PLANNER_SKILL_PATHS


def _wbs_planner_subagent(workdir: str) -> dict:
    """Config for the wbs_planner subagent: decompose + estimate the WBS.

    Reads the approved brief/tech_stack/blueprint, breaks the solution into a
    BnK-format WBS (phases→modules→features), estimates dev effort (BA/QC/PM are
    derived), plans timeline/team/milestones and writes wbs.json. The gate tools
    (propose_wbs_skeleton / propose_wbs / export_wbs_excel) live on the MAIN agent.
    """
    return {
        "name": "wbs_planner",
        "description": (
            "Builds a BnK-format Work Breakdown Structure from the approved solution. "
            "Reads diagram_brief.json + tech_stack.json + blueprint.json, drafts the "
            "phase/module skeleton, estimates dev effort per feature (BA/QC/PM derived), "
            "rolls up totals, plans the timeline/team/milestones, validates, and writes "
            "wbs.json / wbs_skeleton.json. Returns a short status — the MAIN agent runs "
            "the propose/export gates."
        ),
        "system_prompt": build_wbs_planner_prompt(workdir),
        "tools": WBS_PLANNER_TOOLS,
        "skills": WBS_PLANNER_SKILL_PATHS,
    }
