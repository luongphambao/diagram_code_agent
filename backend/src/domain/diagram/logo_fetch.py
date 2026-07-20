#!/usr/bin/env python3
"""Efficient logo search + download resolver (runs INSIDE the sandbox).

The agent calls this instead of an ad-hoc `urlretrieve`, so gap logos are
resolved reliably with validation + caching. Resolution order (offline first):

  1. SEARCH the local icon pack (`--icons`, default /icons) by fuzzy filename.
  2. Iconify `logos:` set (full-colour brand SVGs) -> rasterise to PNG.
  3. Google favicon service (square PNG) as a last resort.

Every candidate is validated (real image, roughly square, non-trivial size).
Downloads are cached under `<out>/_logos/`.

Usage (the agent runs this via `execute`):
    python _logo_fetch.py "Label Studio"                 # -> prints a verified path
    python _logo_fetch.py --search "redis"               # -> lists pack candidates
    python _logo_fetch.py "NVIDIA Jetson" --icons /icons --out /workspace
Prints `PATH: <abs path>` on success, or `NOT_FOUND: <reason>`.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import sys
import urllib.request
from pathlib import Path

_UA = {"User-Agent": "Mozilla/5.0 (diagram-mcp logo-fetch)"}
_MIN_BYTES = 700
_MAX_RATIO = 2.6  # reject very wide wordmarks


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


_STOP = {
    "and", "the", "of", "for", "a", "an", "service", "services", "server",
    "platform", "api", "system", "studio", "cloud", "app", "tool", "tools",
    "engine", "node", "core", "edge", "device", "data", "model",
}


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", name.lower()) if t]


def _content_tokens(name: str) -> list[str]:
    toks = [t for t in _tokens(name) if t not in _STOP and len(t) > 1]
    return toks or _tokens(name)  # fall back if everything was a stopword


def _valid_png(data: bytes) -> tuple[bool, str]:
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        w, h = im.size
        if len(data) < _MIN_BYTES:
            return False, f"too small ({len(data)}B)"
        if max(w, h) / max(1, min(w, h)) > _MAX_RATIO:
            return False, f"not square ({w}x{h})"
        return True, f"{im.format} {w}x{h}"
    except Exception as e:  # noqa: BLE001
        return False, f"not an image: {e}"


def search_pack(query: str, icons_root: str, limit: int = 8) -> list[str]:
    """Fuzzy-match the icon pack by filename; return ranked absolute paths."""
    root = Path(icons_root)
    if not root.exists():
        return []
    q_slug = _slug(query)
    content = set(_content_tokens(query))
    scored: list[tuple[int, int, str]] = []
    for png in root.rglob("*.png"):
        stem_toks = set(_tokens(png.stem)) | set(_tokens(png.parent.name))
        exact = _slug(png.stem) == q_slug
        # Qualify only on an exact slug match OR when ALL content tokens are
        # present in the candidate (avoids weak single-token false positives
        # like "label studio" -> "chaos-studio").
        if not exact and not content.issubset(stem_toks):
            continue
        extra = len(stem_toks - content)  # fewer unrelated tokens = better
        scored.append((0 if exact else 1, extra, str(png)))
    scored.sort(key=lambda x: (x[0], x[1], len(x[2])))
    return [p for _, _, p in scored[:limit]]


def _download(url: str) -> bytes | None:
    try:
        return urllib.request.urlopen(
            urllib.request.Request(url, headers=_UA), timeout=15
        ).read()
    except Exception:  # noqa: BLE001
        return None


def _from_iconify(name: str, out_png: Path) -> bool:
    """Try the Iconify `logos:` brand set -> rasterise SVG to PNG."""
    try:
        import cairosvg
    except Exception:  # noqa: BLE001
        return False
    slug = _slug(name)
    candidates = [slug, slug.replace("-", ""), f"{slug}-icon", _tokens(name)[0] if _tokens(name) else slug]
    for cand in dict.fromkeys(candidates):
        svg = _download(f"https://api.iconify.design/logos/{cand}.svg")
        if not svg or svg[:4] != b"<svg":
            continue
        try:
            png = cairosvg.svg2png(bytestring=svg, output_width=256, output_height=256)
        except Exception:  # noqa: BLE001
            continue
        ok, _ = _valid_png(png)
        if ok:
            out_png.write_bytes(png)
            return True
    return False


def _from_favicon(name: str, out_png: Path) -> bool:
    """Last resort: site favicon (square PNG) via a guessed domain."""
    slug_nodash = _slug(name).replace("-", "")
    for domain in (f"{slug_nodash}.com", f"{slug_nodash}.ai", f"{slug_nodash}.io", f"{slug_nodash}.org"):
        data = _download(
            f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
        )
        if data and _valid_png(data)[0]:
            out_png.write_bytes(data)
            return True
    return False


def get_logo(name: str, icons_root: str, out_dir: str) -> str | None:
    # 1) offline pack
    hits = search_pack(name, icons_root, limit=1)
    if hits:
        return hits[0]
    cache = Path(out_dir) / "_logos"
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"{_slug(name)}.png"
    if target.exists():
        return str(target)
    # 2) Iconify brand SVG  3) favicon
    if _from_iconify(name, target) or _from_favicon(name, target):
        return str(target)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--search", action="store_true")
    ap.add_argument("--icons", default=os.environ.get("ICONS_ROOT", "/icons"))
    ap.add_argument("--out", default=os.environ.get("LOGO_OUT", "/workspace"))
    args = ap.parse_args()

    if args.search:
        hits = search_pack(args.query, args.icons)
        if hits:
            print("\n".join(hits))
        else:
            print("NO_PACK_MATCH")
        return 0

    path = get_logo(args.query, args.icons, args.out)
    if path:
        print(f"PATH: {path}")
        return 0
    print(f"NOT_FOUND: no reliable logo for '{args.query}' — use a generic built-in node")
    return 1


if __name__ == "__main__":
    sys.exit(main())
