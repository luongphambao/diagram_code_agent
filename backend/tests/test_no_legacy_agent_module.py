"""Guards against reintroducing the legacy agent.py monolith (improvement plan §1.1).

`agent.py` used to be a 1544-line flat module. It was split into the `agent/`
package (agent/__init__.py re-exports every name for parity), which shadows a
same-named flat module — `agent.py` sat in the tree dead and unimported for a
while before being deleted. This test fails loudly if it (or an equivalent flat
module) comes back, since a future edit could otherwise silently start editing
dead code again.
"""

from __future__ import annotations

from pathlib import Path

import agent

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def test_agent_py_flat_module_does_not_exist():
    assert not (_SRC_DIR / "agent.py").exists(), (
        "backend/src/agent.py has reappeared — it is dead code shadowed by the "
        "agent/ package (see agent/__init__.py's docstring). Add new code to "
        "agent/<submodule>.py instead."
    )


def test_agent_import_resolves_to_the_package():
    assert Path(agent.__file__).parent.name == "agent", (
        f"`import agent` resolved to {agent.__file__!r}, not the agent/ package "
        "— a flat agent.py is shadowing it again."
    )
