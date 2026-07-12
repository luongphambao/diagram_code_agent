"""critic subagent: read-only review of the rendered diagram."""

from __future__ import annotations

from prompts import build_critic_prompt
from tools import CRITIC_TOOLS

from ..constants import _CRITIC_CALL_LIMIT
from .spec import SubagentSpec


def _critic_spec(*, style: str, use_vision_relay: bool) -> SubagentSpec:
    """Spec for the critic subagent: read-only review of the rendered diagram.

    ``use_vision_relay`` mirrors the drawer's — critic inspects the same
    rendered image via the same relay path, so it needs the same provider
    workaround the drawer's model requires.
    """
    return SubagentSpec(
        name="critic",
        description=(
            "Reviews the rendered diagram against the approved blueprint. Looks at "
            "out.png itself (no image reaches the caller's context) and returns a "
            "VERDICT: PASS / REVISE line with a small set of concrete findings. "
            "Does NOT edit code or re-render."
        ),
        model_role="critic",
        tools=CRITIC_TOOLS,
        run_limit=_CRITIC_CALL_LIMIT,
        prompt_builder=build_critic_prompt,
        prompt_kwargs={"style": style},
        use_vision_relay=use_vision_relay,
    )
