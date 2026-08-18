"""Guard against the shadowed top-level duplicates coming back.

``backend/src/agent.py``, ``backend/src/config.py``, and
``backend/src/runtime/backends.py`` were tracked, dead code: Python's import
system always resolves a package (``agent/``, ``config/``) before a sibling
module of the same name, so the ``.py`` files were unreachable — 1544 + 176 +
277 lines nobody ever ran, carrying stale imports. Removed as part of the
LangGraph Platform migration cleanup (see plans/*cicd*.md Phase 1). This test
keeps them from silently reappearing.
"""

from __future__ import annotations

from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"


def test_agent_is_a_package_not_a_shadowed_module() -> None:
    assert (_SRC / "agent" / "__init__.py").exists(), "agent/ package must exist"
    assert not (_SRC / "agent.py").exists(), (
        "src/agent.py is dead code shadowed by the agent/ package — do not re-add it"
    )


def test_config_is_a_package_not_a_shadowed_module() -> None:
    assert (_SRC / "config" / "__init__.py").exists(), "config/ package must exist"
    assert not (_SRC / "config.py").exists(), (
        "src/config.py is dead code shadowed by the config/ package — do not re-add it"
    )


def test_runtime_backends_duplicate_is_gone() -> None:
    assert (_SRC / "backends.py").exists(), "src/backends.py is the real module"
    assert not (_SRC / "runtime" / "backends.py").exists(), (
        "runtime/backends.py was a divergent, unimported duplicate of "
        "src/backends.py (different parents[N] depth) — do not re-add it"
    )
