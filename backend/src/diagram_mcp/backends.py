"""Agent-space backend configuration using deepagents native backends.

Layout under agent_space/:
  workspace/   — diagram generation scratch area (FilesystemBackend default)
  memories/    — persistent semantic memory; /memories/AGENTS.md
  outputs/     — timestamped run archives

Paths are resolved relative to this repo so the project is self-contained:
  backend/                 <- _BACKEND_ROOT (parents[2] of this file)
  backend/agent_space/     <- AGENT_SPACE (created at runtime)
  backend/skills/          <- SKILLS_DIR (bundled procedural skills)
  resources/icons/         <- icon pack (shared, sibling of backend/)
"""

from __future__ import annotations

from pathlib import Path

from deepagents.backends import CompositeBackend, FilesystemBackend

# backend/src/diagram_mcp/backends.py -> parents[2] == backend/
_BACKEND_ROOT  = Path(__file__).resolve().parents[2]
_REPO_ROOT     = _BACKEND_ROOT.parent

AGENT_SPACE    = _BACKEND_ROOT / "agent_space"
WORKSPACE      = AGENT_SPACE / "workspace"
MEMORIES_DIR   = AGENT_SPACE / "memories"
OUTPUTS_DIR    = AGENT_SPACE / "outputs"

# Procedural skills bundled with the repo (loaded by the deep agent).
SKILLS_DIR     = _BACKEND_ROOT / "skills"

# Icon assets gathered under resources/ (for local execution without Modal).
_RESOURCES     = _REPO_ROOT / "resources"
LOCAL_ICONS    = str(_RESOURCES / "icons")
LOCAL_MANIFEST = str(_RESOURCES / "icons_manifest.json")
LOCAL_NODE_CATALOG = str(_RESOURCES / "node_catalog.json")

# Virtual path prefix the agent uses to read/write persistent memory.
MEMORY_PATH = "/memories/AGENTS.md"


def _ensure_dirs() -> None:
    for d in (WORKSPACE, MEMORIES_DIR, OUTPUTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def make_local_backend() -> CompositeBackend:
    """Build the CompositeBackend for the single diagram deep agent.

    The agent gets ONLY filesystem tools (read_file/write_file/edit_file/ls/glob/grep)
    — no shell `execute`. Rendering a diagram is done through the custom
    `render_diagram` tool (see :mod:`diagram_mcp.tools`), which runs the generated
    ``diagrams`` code in a subprocess. This keeps the design to "deep agent + tools
    + memory".

    Routing:
      /memories/  → FilesystemBackend rooted at AGENT_SPACE
                    so /memories/AGENTS.md maps to agent_space/memories/AGENTS.md
      (default)   → FilesystemBackend rooted at WORKSPACE (real absolute paths)
                    diagram.py / out.png / out.dot / out.drawio live here.
    """
    _ensure_dirs()
    return CompositeBackend(
        default=FilesystemBackend(root_dir=str(WORKSPACE), virtual_mode=False),
        routes={
            "/memories/": FilesystemBackend(
                root_dir=str(AGENT_SPACE),
                virtual_mode=True,
            ),
        },
    )
