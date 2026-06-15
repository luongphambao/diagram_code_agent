"""Extract a Python project's module-import graph as a JSON graph.

Walks a package/project directory, parses each module with `ast`, builds the
intra-project import edges, and optionally applies transitive reduction so
the diagram stays readable instead of becoming a hairball.

CLI usage:
  python3 pyimports.py <project_dir> [-o graph.json] [--direction TB|LR] [--no-reduce]

Programmatic usage:
  from .pyimports import build_import_graph
  graph = build_import_graph("/path/to/project", group=True, reduce=True)
  # -> {"direction": "TB", "nodes": [...], "edges": [...]}
"""
import argparse
import ast
import json
import os
import re
import subprocess
import sys


def discover(root: str) -> tuple[dict[str, str], str]:
    """Map dotted module name -> file path for every .py under root."""
    root = os.path.abspath(root)
    base = os.path.basename(root) if os.path.exists(os.path.join(root, "__init__.py")) else ""
    modules: dict[str, str] = {}
    for dirpath, _, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root)[:-3]
            parts = rel.split(os.sep)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            parts = ([base] + parts) if base else parts
            if parts:
                modules[".".join(parts)] = os.path.join(dirpath, fn)
    return modules, base


def _resolve(name: str, current: str, modules: dict) -> str | None:
    parts = name.split(".") if name else []
    while parts:
        cand = ".".join(parts)
        if cand in modules and cand != current:
            return cand
        parts = parts[:-1]
    return None


def _edges_of(name: str, path: str, modules: dict) -> set[str]:
    pkg = name if path.endswith("__init__.py") else name.rsplit(".", 1)[0] if "." in name else ""
    found: set[str] = set()
    try:
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _resolve(alias.name, name, modules)
                if target:
                    found.add(target)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = pkg.split(".") if pkg else []
                base_parts = base_parts[: len(base_parts) - (node.level - 1)]
                prefix = ".".join(base_parts)
                mod = f"{prefix}.{node.module}" if prefix and node.module else (node.module or prefix)
            else:
                mod = node.module or ""
            target = _resolve(mod, name, modules)
            if target:
                found.add(target)
            for alias in node.names:
                sub = f"{mod}.{alias.name}" if mod else alias.name
                target = _resolve(sub, name, modules)
                if target:
                    found.add(target)
    return found


def _transitive_reduce(nodes: list[str], edges: list[tuple[str, str]]) -> list[tuple[str, str]]:
    idx = {n: i for i, n in enumerate(nodes)}
    dot = "digraph{" + "".join(f"{idx[s]}->{idx[t]};" for s, t in edges) + "}"
    try:
        out = subprocess.run(["tred"], input=dot, capture_output=True,
                             text=True, check=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        sys.stderr.write(f"warning: tred unavailable, keeping all edges ({exc})\n")
        return edges
    rev = {i: n for n, i in idx.items()}
    return [(rev[int(a)], rev[int(b)]) for a, b in re.findall(r"(\d+)\s*->\s*(\d+)", out)]


def build_import_graph(project_dir: str, direction: str = "TB",
                       group: bool = False, reduce: bool = True) -> dict:
    """Build a module import graph for a Python project.

    Returns a dict with 'direction', 'nodes', 'edges' suitable for autolayout
    or prettygraph rendering.
    """
    modules, base = discover(project_dir)
    if not modules:
        return {"direction": direction, "nodes": [], "edges": [],
                "error": f"no .py modules found under {project_dir}"}
    edges = sorted({(name, t) for name, path in modules.items()
                    for t in _edges_of(name, path, modules)})
    raw_count = len(edges)
    if reduce:
        edges = _transitive_reduce(list(modules), edges)
    strip = base + "." if base else ""
    label = lambda m: m[len(strip):] if strip and m.startswith(strip) else m

    def node(m: str) -> dict:
        d: dict = {"id": m, "label": label(m)}
        if group:
            rest = label(m).split(".")
            if len(rest) > 1:
                d["group"] = "/".join(rest[:-1])
        return d

    return {
        "direction": direction,
        "nodes": [node(m) for m in modules],
        "edges": [{"source": s, "target": t} for s, t in edges],
        "stats": {"modules": len(modules), "edges": len(edges), "raw_edges": raw_count},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Python import graph -> JSON.")
    ap.add_argument("project", help="package or project directory")
    ap.add_argument("-o", "--output", help="output JSON path (default: stdout)")
    ap.add_argument("--direction", default="TB", choices=["TB", "LR"])
    ap.add_argument("--group", action="store_true")
    ap.add_argument("--no-reduce", action="store_true")
    args = ap.parse_args()
    graph = build_import_graph(args.project, args.direction, args.group, not args.no_reduce)
    text = json.dumps(graph, indent=2)
    if args.output:
        open(args.output, "w", encoding="utf-8").write(text)
        sys.stderr.write(f"wrote {args.output}\n")
    else:
        sys.stdout.write(text)
    stats = graph.get("stats", {})
    sys.stderr.write(f"{stats.get('modules', 0)} modules, {stats.get('edges', 0)} edges\n")


if __name__ == "__main__":
    main()
