"""design_token_block() (prompts/_blocks.py) must generate its numbers from
refined_theme.as_json() — the same dict written to design_tokens.json next to
every refined render — so the drawer prompt can never drift from what the
engine actually draws (docs/improve/REVIEW-CODEBASE-FIT.md, Patch 5)."""

from __future__ import annotations

from prompts._blocks import design_token_block
from prompts.drawer_agent import build_drawer_prompt


def test_design_token_block_reflects_refined_theme():
    from prettygraph.native import refined_theme as RT

    block = design_token_block()
    # spot-check a few live values so a refined_theme.py edit is caught here
    assert f"card={RT.TYPE_SCALE['card']}" in block
    assert RT.EDGE_CLASSES["data"][0] in block
    assert str(RT.GEO["card_w"]) in block


def test_design_token_block_is_in_the_drawer_prompt():
    prompt = build_drawer_prompt(style="pretty")
    assert "## Design tokens" in prompt
    assert "do NOT invent a different number" in prompt
