"""Generate an accurate catalog of every importable `diagrams` Node class.

Source of truth = the installed `diagrams` package (version-matched), NOT the
docs website. Walks `diagrams.<provider>.<module>`, collects every class that
subclasses `diagrams.Node`, and emits:
  - assets/node_catalog.json
  - skills/diagrams-as-code/reference/nodes.md  (grouped, with import lines)

The agent reads nodes.md (via the diagrams-as-code skill) to use EXACT import
names instead of guessing.
"""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # backend/
JSON_OUT = PROJECT_ROOT.parent / "resources" / "node_catalog.json"
MD_OUT = PROJECT_ROOT / "skills" / "diagrams-as-code" / "reference" / "nodes.md"


def build_catalog() -> dict:
    import diagrams
    from diagrams import Node

    catalog: dict[str, dict[str, list[str]]] = {}
    pkg = diagrams
    for _, modname, ispkg in pkgutil.walk_packages(pkg.__path__, "diagrams."):
        # modname like "diagrams.aws.compute"; skip the top pkg + base/custom internals
        parts = modname.split(".")
        if len(parts) != 3:
            continue
        provider, module = parts[1], parts[2]
        if provider in {"base"}:
            continue
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        classes = []
        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(obj, Node)
                and obj is not Node
                and obj.__module__ == modname
                and not name.startswith("_")
            ):
                classes.append(name)
        if classes:
            catalog.setdefault(provider, {})[module] = sorted(classes)
    return catalog


def to_markdown(catalog: dict) -> str:
    total = sum(len(c) for mods in catalog.values() for c in mods.values())
    lines = [
        "# diagrams node catalog",
        "",
        f"Every importable node class in the installed `diagrams` package "
        f"({total} classes, {len(catalog)} providers). Import as "
        "`from diagrams.<provider>.<module> import <Class>`. Use ONLY names that "
        "appear here — do not guess.",
        "",
    ]
    for provider in sorted(catalog):
        lines.append(f"## {provider}")
        lines.append("")
        for module in sorted(catalog[provider]):
            names = catalog[provider][module]
            lines.append(f"`diagrams.{provider}.{module}`: " + ", ".join(names))
            lines.append("")
    return "\n".join(lines)


def generate() -> tuple[int, int]:
    catalog = build_catalog()
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    MD_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(catalog, indent=0))
    MD_OUT.write_text(to_markdown(catalog))
    total = sum(len(c) for mods in catalog.values() for c in mods.values())
    return total, len(catalog)


if __name__ == "__main__":
    total, providers = generate()
    print(f"wrote {MD_OUT} and {JSON_OUT}: {total} node classes, {providers} providers")
