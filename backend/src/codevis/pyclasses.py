"""Extract a Python project's class-inheritance graph as a JSON graph.

A finer-grained companion to pyimports: instead of module->module imports,
emits one node per class and an edge from each subclass to its project base
classes. With group=True, classes are boxed by their module.

CLI usage:
  python3 pyclasses.py <project_dir> [-o graph.json] [--direction TB|LR] [--group]

Programmatic usage:
  from .pyclasses import build_class_graph
  graph = build_class_graph("/path/to/project", group=True)
  # -> {"direction": "TB", "nodes": [...], "edges": [...]}
"""

import argparse
import ast
import json
import os
import re

from subprocess_utils import run_tred
import sys


def _discover(root: str) -> tuple[dict[str, str], str]:
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


def _base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _classes_in(module: str, path: str) -> list[tuple[str, str, list[str]]]:
    try:
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    except SyntaxError:
        return []
    out = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = [b for b in (_base_name(b) for b in node.bases) if b]
            out.append((f"{module}.{node.name}", node.name, bases))
    return out


def _transitive_reduce(nodes: list[str], edges: list[tuple[str, str]]) -> list[tuple[str, str]]:
    idx = {n: i for i, n in enumerate(nodes)}
    dot = "digraph{" + "".join(f"{idx[s]}->{idx[t]};" for s, t in edges) + "}"
    out = run_tred(dot)
    if out is None:
        return edges
    rev = {i: n for n, i in idx.items()}
    return [(rev[int(a)], rev[int(b)]) for a, b in re.findall(r"(\d+)\s*->\s*(\d+)", out)]


def build_class_graph(
    project_dir: str, direction: str = "TB", group: bool = False, reduce: bool = True
) -> dict:
    """Build a class-inheritance graph for a Python project."""
    modules, base = _discover(project_dir)
    classes: dict[str, tuple[str, list[str]]] = {}
    by_name: dict[str, list[str]] = {}
    for mod, path in modules.items():
        for cid, name, bases in _classes_in(mod, path):
            classes[cid] = (mod, bases)
            by_name.setdefault(name, []).append(cid)
    if not classes:
        return {
            "direction": direction,
            "nodes": [],
            "edges": [],
            "error": f"no classes found under {project_dir}",
        }

    def resolve(name: str, module: str) -> str | None:
        cands = by_name.get(name, [])
        same = [c for c in cands if classes[c][0] == module]
        if same:
            return same[0]
        return cands[0] if len(cands) == 1 else None

    edges: set[tuple[str, str]] = set()
    for cid, (mod, bases) in classes.items():
        for b in bases:
            target = resolve(b, mod)
            if target and target != cid:
                edges.add((cid, target))
    edge_list = sorted(edges)
    raw_count = len(edge_list)
    if reduce:
        edge_list = _transitive_reduce(list(classes), edge_list)

    strip = base + "." if base else ""
    short = lambda m: m[len(strip) :] if strip and m.startswith(strip) else m

    def node(cid: str) -> dict:
        d: dict = {"id": cid, "label": cid.rsplit(".", 1)[1]}
        if group:
            mod = classes[cid][0]
            path = short(mod).replace(".", "/")
            if path:
                d["group"] = path
        return d

    return {
        "direction": direction,
        "nodes": [node(cid) for cid in classes],
        "edges": [{"source": s, "target": t} for s, t in edge_list],
        "stats": {"classes": len(classes), "edges": len(edge_list), "raw_edges": raw_count},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Python class-inheritance graph -> JSON.")
    ap.add_argument("project", help="package or project directory")
    ap.add_argument("-o", "--output", help="output JSON path (default: stdout)")
    ap.add_argument("--direction", default="TB", choices=["TB", "LR"])
    ap.add_argument("--group", action="store_true")
    ap.add_argument("--no-reduce", action="store_true")
    args = ap.parse_args()
    graph = build_class_graph(args.project, args.direction, args.group, not args.no_reduce)
    text = json.dumps(graph, indent=2)
    if args.output:
        open(args.output, "w", encoding="utf-8").write(text)
        sys.stderr.write(f"wrote {args.output}\n")
    else:
        sys.stdout.write(text)
    stats = graph.get("stats", {})
    sys.stderr.write(f"{stats.get('classes', 0)} classes, {stats.get('edges', 0)} edges\n")


if __name__ == "__main__":
    main()
