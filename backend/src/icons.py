"""Build a manifest of the bundled Custom-icon pack.

The pack (``resources/icons``) lets the agent discover which logos are
available for
``diagrams.custom.Custom(label, "<icons_root>/<provider>/<category>/<name>.png")``
when a built-in ``diagrams`` node does not exist (e.g. NVIDIA, Supabase).
"""

from __future__ import annotations

import json
from pathlib import Path

from backends import LOCAL_ICONS, LOCAL_MANIFEST

ICONS_DIR = Path(LOCAL_ICONS)
MANIFEST_PATH = Path(LOCAL_MANIFEST)

# Root the agent references icons from (the real local resources/icons path).
SANDBOX_ICONS_ROOT = LOCAL_ICONS


def build_manifest(icons_dir: Path = ICONS_DIR) -> dict:
    """Scan the icon pack and return ``{provider: {category: [names]}}``."""
    providers: dict[str, dict[str, list[str]]] = {}
    for png in sorted(icons_dir.rglob("*.png")):
        rel = png.relative_to(icons_dir)
        parts = rel.parts
        provider = parts[0]
        category = parts[1] if len(parts) >= 3 else "_root"
        name = png.stem
        providers.setdefault(provider, {}).setdefault(category, []).append(name)
    total = sum(len(v) for c in providers.values() for v in c.values())
    return {
        "root": SANDBOX_ICONS_ROOT,
        "total": total,
        "path_template": f"{SANDBOX_ICONS_ROOT}/{{provider}}/{{category}}/{{name}}.png",
        "providers": providers,
    }


def write_manifest(path: Path = MANIFEST_PATH) -> Path:
    manifest = build_manifest()
    path.write_text(json.dumps(manifest, indent=0))
    return path


if __name__ == "__main__":
    p = write_manifest()
    data = json.loads(p.read_text())
    print(f"wrote {p} — {data['total']} icons, {len(data['providers'])} providers")
