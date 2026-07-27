"""Guards against reintroducing the `skills/drawer/*` duplicate skill trees.

`skills/drawer/pro-style/` and `skills/drawer/diagrams-as-code/` used to be
byte-for-byte-drifted COPIES of `skills/pro-style/` and `skills/diagrams-as-code/`
— `agent/constants.py` was updated to point both `MAIN_SKILL_PATHS` and
`DRAWER_SKILL_PATHS` at the single top-level copies, but the stale duplicate
directories were left on disk, still readable by anything that walked
`skills/` directly. Two copies of the same skill that can silently drift apart
is exactly the kind of non-deterministic-behavior bug this repo has already
been bitten by once (see AGENTS.md's "Luật cấm"). This test fails loudly if
they come back.
"""

from __future__ import annotations

from pathlib import Path

from backends import SKILLS_DIR


def test_drawer_skill_duplicate_tree_does_not_exist():
    assert not (SKILLS_DIR / "drawer").exists(), (
        "skills/drawer/ has reappeared — agent/constants.py's MAIN_SKILL_PATHS "
        "and DRAWER_SKILL_PATHS both already point at the single top-level "
        "skills/pro-style/ and skills/diagrams-as-code/ copies. Add new skill "
        "content there, not under skills/drawer/."
    )


def test_agent_constants_skill_paths_share_the_same_top_level_dirs():
    """DRAWER_SKILL_PATHS must stay a copy of MAIN_SKILL_PATHS, not its own
    (potentially drifting) list of paths."""
    from agent.constants import DRAWER_SKILL_PATHS, MAIN_SKILL_PATHS

    assert DRAWER_SKILL_PATHS == MAIN_SKILL_PATHS
    for p in MAIN_SKILL_PATHS:
        assert Path(p).is_relative_to(SKILLS_DIR), f"{p} escaped skills/ — check for a drifted duplicate"
