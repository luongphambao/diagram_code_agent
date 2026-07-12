"""critic subagent: read-only review of the rendered diagram."""

from __future__ import annotations

from prompts import build_critic_prompt
from tools import CRITIC_TOOLS


def _critic_subagent(style: str) -> dict:
    """Config for the critic subagent: read-only review of the rendered diagram."""
    return {
        "name": "critic",
        "description": (
            "Reviews the rendered diagram against the approved blueprint. Looks at "
            "out.png itself (no image reaches the caller's context) and returns a "
            "VERDICT: PASS / REVISE line with a small set of concrete findings. "
            "Does NOT edit code or re-render."
        ),
        "system_prompt": build_critic_prompt(style=style),
        "tools": CRITIC_TOOLS,
    }
