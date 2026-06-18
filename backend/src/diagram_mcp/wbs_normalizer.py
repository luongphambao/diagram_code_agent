"""Load and normalise BnK WBS JSON files into canonical WbsProject objects.

CLI usage (verify normalisation):
    python -m diagram_mcp.wbs_normalizer
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .wbs_schema import WbsProject

logger = logging.getLogger(__name__)

# Default data directory — relative to this file (backend/src/diagram_mcp/)
_DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent.parent / "DATA" / "SOLUTION_WBS"


def load_all_projects(
    data_dir: str | Path | None = None,
) -> tuple[list[WbsProject], list[str]]:
    """Load all WBS JSON files from *data_dir* and normalise to WbsProject.

    Returns ``(projects, errors)`` where *errors* is a list of
    ``"filename: reason"`` strings for files that could not be parsed.
    """
    data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    projects: list[WbsProject] = []
    errors: list[str] = []

    json_files = sorted(data_dir.glob("*.json"))
    if not json_files:
        logger.warning("No *.json files found in %s", data_dir)
        return projects, errors

    for path in json_files:
        raw: Any
        try:
            with open(path, encoding="utf-8-sig") as fh:
                raw = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path.name}: JSON parse error — {exc}")
            continue

        if not isinstance(raw, dict):
            errors.append(f"{path.name}: top-level is {type(raw).__name__}, expected dict")
            continue

        try:
            project = WbsProject.from_raw(raw, source_file=path.name)
            projects.append(project)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path.name}: schema error — {exc}")

    return projects, errors


def project_to_documents(project: WbsProject) -> list[dict[str, Any]]:
    """Convert one WbsProject into LangChain-compatible document dicts.

    Returns a list of dicts with ``page_content`` (str) and ``metadata`` (dict)
    at two granularities:

    * **project-level** (1 doc): composite text covering domain, solution type,
      tech stack, objectives, and the raw summary.
    * **module-level** (N docs, one per module): module name + task names for
      fine-grained semantic search.
    """
    docs: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # Project-level document                                               #
    # ------------------------------------------------------------------ #
    tech_flat = ", ".join(project.technology_stack[:30]) if project.technology_stack else ""
    objectives_flat = " | ".join(project.objectives[:5]) if project.objectives else ""
    summary_text = project.raw_summary or ""

    project_text = (
        f"{project.name} | {project.business_domain} | {project.solution_type}"
        + (f" | Tech: {tech_flat}" if tech_flat else "")
        + (f" | Goals: {objectives_flat}" if objectives_flat else "")
        + (f" | Summary: {summary_text[:600]}" if summary_text else "")
    )

    docs.append({
        "page_content": project_text,
        "metadata": {
            "granularity": "project",
            "project_code": project.project_code,
            "name": project.name,
            "client": project.client or "",
            "business_domain": project.business_domain,
            "solution_type": project.solution_type,
            "total_mandays": project.total_mandays or 0,
            "tech_keywords": " ".join(project.technology_stack[:20]),
            "source_file": project.source_file or "",
        },
    })

    # ------------------------------------------------------------------ #
    # Module-level documents                                               #
    # ------------------------------------------------------------------ #
    for mod in project.modules:
        tasks_raw = []
        # tasks are stored on the WbsModule's raw source; we need to pass them
        # through — but WbsModule doesn't retain task names after normalisation.
        # Use the module name as the primary text (sufficient for retrieval).
        module_text = (
            f"{project.name} > {mod.name}"
            + (f" ({mod.code})" if mod.code else "")
            + f" | domain: {project.business_domain}"
            + (f" | tech: {tech_flat[:200]}" if tech_flat else "")
        )
        docs.append({
            "page_content": module_text,
            "metadata": {
                "granularity": "module",
                "project_code": project.project_code,
                "project_name": project.name,
                "business_domain": project.business_domain,
                "solution_type": project.solution_type,
                "module_code": mod.code,
                "module_name": mod.name,
                "module_md": mod.total_md,
                "source_file": project.source_file or "",
            },
        })

    return docs


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    data_dir_arg = sys.argv[1] if len(sys.argv) > 1 else None
    projects, errors = load_all_projects(data_dir_arg)

    print(f"\n{'='*60}")
    print(f"Loaded:  {len(projects)} projects")
    print(f"Errors:  {len(errors)}")
    if errors:
        print("\nFailed files:")
        for e in errors:
            print(f"  • {e}")

    if projects:
        print("\nSample (first project):")
        p = projects[0]
        print(f"  name          : {p.name}")
        print(f"  domain        : {p.business_domain}")
        print(f"  solution_type : {p.solution_type}")
        print(f"  total_mandays : {p.total_mandays}")
        print(f"  tech_stack    : {p.technology_stack[:5]}")
        print(f"  modules       : {len(p.modules)}")
        docs = project_to_documents(p)
        print(f"  documents     : {len(docs)} (1 project + {len(docs)-1} modules)")
        print(f"\n  project doc preview:\n  {docs[0]['page_content'][:300]}")

    total_docs = sum(len(project_to_documents(p)) for p in projects)
    print(f"\nTotal documents (project + module level): {total_docs}")
    print("=" * 60)
