"""Load and normalise BnK WBS JSON files into canonical WbsProject objects.

CLI usage (verify normalisation):
    python -m diagram_mcp.wbs_normalizer
    python -m diagram_mcp.wbs_normalizer --export /tmp/normalized.json
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from wbs_schema import WbsProject

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent.parent / "DATA" / "SOLUTION_WBS"


def load_all_projects(
    data_dir: str | Path | None = None,
) -> tuple[list[WbsProject], list[str]]:
    """Load all WBS JSON files from *data_dir* and normalise to WbsProject.

    Returns ``(projects, errors)`` — errors is a list of ``"filename: reason"`` strings.
    """
    data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    projects: list[WbsProject] = []
    errors: list[str] = []

    json_files = sorted(data_dir.glob("*.json"))
    if not json_files:
        logger.warning("No *.json files found in %s", data_dir)
        return projects, errors

    for path in json_files:
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

    Three granularities:
    - **project** (1 doc): domain, solution type, tech stack, objectives, summary.
    - **module** (N docs): effort_by_module summary rows.
    - **item** (M docs): normalised wbs_items rows (tasks / deliverables).
    """
    docs: list[dict[str, Any]] = []
    tech_flat = ", ".join(project.technology_stack[:30]) if project.technology_stack else ""

    # ------------------------------------------------------------------ #
    # Project-level document                                               #
    # ------------------------------------------------------------------ #
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
        module_text = (
            f"{project.name} > {mod.name}"
            + (f" ({mod.code})" if mod.code else "")
            + f" | domain: {project.business_domain}"
            + f" | {mod.total_md} md"
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

    # ------------------------------------------------------------------ #
    # WBS item-level documents                                             #
    # ------------------------------------------------------------------ #
    for item in project.wbs_items:
        if not item.name:
            continue
        parts = [project.name]
        if item.module:
            parts.append(item.module)
        if item.phase:
            parts.append(item.phase)
        parts.append(item.code or item.id or "")
        parts.append(item.name)

        item_text = " > ".join(p for p in parts if p)
        if item.description:
            item_text += f": {item.description}"
        if item.total_md:
            item_text += f" | {item.total_md} md"
        if item.remark:
            item_text += f" | note: {item.remark}"

        docs.append({
            "page_content": item_text,
            "metadata": {
                "granularity": "item",
                "project_code": project.project_code,
                "project_name": project.name,
                "business_domain": project.business_domain,
                "solution_type": project.solution_type,
                "item_id": item.id,
                "item_code": item.code,
                "item_name": item.name,
                "item_module": item.module,
                "item_phase": item.phase,
                "item_md": item.total_md,
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

    export_path: str | None = None
    args = sys.argv[1:]
    if "--export" in args:
        idx = args.index("--export")
        export_path = args[idx + 1] if idx + 1 < len(args) else "normalized_wbs.json"
        args = [a for i, a in enumerate(args) if i not in (idx, idx + 1)]

    data_dir_arg = args[0] if args else None
    projects, errors = load_all_projects(data_dir_arg)

    print(f"\n{'='*60}")
    print(f"Loaded:  {len(projects)} projects")
    print(f"Errors:  {len(errors)}")
    if errors:
        print("\nFailed files:")
        for e in errors:
            print(f"  • {e}")

    if projects:
        all_docs = []
        for p in projects:
            all_docs.extend(project_to_documents(p))

        by_gran: dict[str, int] = {}
        for d in all_docs:
            g = d["metadata"]["granularity"]
            by_gran[g] = by_gran.get(g, 0) + 1

        print(f"\nTotal documents: {len(all_docs)}")
        for g, cnt in sorted(by_gran.items()):
            print(f"  {g}: {cnt}")

        p0 = projects[0]
        print(f"\nSample (first project): {p0.name}")
        print(f"  domain        : {p0.business_domain}")
        print(f"  solution_type : {p0.solution_type}")
        print(f"  total_mandays : {p0.total_mandays}")
        print(f"  tech_stack    : {p0.technology_stack[:5]}")
        print(f"  modules       : {len(p0.modules)}")
        print(f"  wbs_items     : {len(p0.wbs_items)}")

        if export_path:
            out = []
            for p in projects:
                out.append(p.model_dump())
            with open(export_path, "w", encoding="utf-8") as fh:
                json.dump(out, fh, indent=2, ensure_ascii=False)
            print(f"\nExported normalized JSON → {export_path}")

    print("=" * 60)
