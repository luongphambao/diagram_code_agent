"""Find AI/LLM brand logos (OpenAI, Claude, Gemini, ...) as draw.io styles or PNG paths.

Resolves a brand name to:
  - A draw.io `image` style (for direct use in .drawio XML), OR
  - An absolute PNG path cached under icons_cache_dir (for use in prettygraph/Graphviz)

Uses lobe-icons (https://github.com/lobehub/lobe-icons, MIT) via unpkg CDN.
Falls back to simple-icons (CC0) for common RAG/LLM data stores not in lobe-icons.

CLI usage:
  python3 aiicons.py "openai"
  python3 aiicons.py "claude" --json
  python3 aiicons.py "langchain" --variant mono --size 48

Programmatic usage:
  from .aiicons import lookup_ai_logo, search_ai_brands
  path = lookup_ai_logo("claude", "/workspace/_logos")  # -> PNG path or None
  results = search_ai_brands("openai")                  # -> list of match dicts
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

MANIFEST = os.path.join(os.path.dirname(__file__), "data", "lobe-icons.json")
_DRAWIO_STYLE = ("shape=image;html=1;imageAspect=0;aspect=fixed;"
                 "verticalLabelPosition=bottom;verticalAlign=top;image=")
_VARIANT = re.compile(r"-(color|text)$")

# Common RAG/LLM data stores that lobe-icons lacks — simple-icons (CC0) fallback.
_SIMPLEICONS_CDN = "https://cdn.simpleicons.org/"
_SUPPLEMENT = {
    "qdrant": "qdrant",
    "milvus": "milvus",
    "supabase": "supabase",
    "redis": "redis",
    "postgresql": "postgresql",
    "mongodb": "mongodb",
    "elasticsearch": "elasticsearch",
    "neo4j": "neo4j",
    "kafka": "apachekafka",
    "clickhouse": "clickhouse",
    "duckdb": "duckdb",
    "mysql": "mysql",
    "sqlite": "sqlite",
    "cassandra": "apachecassandra",
    "snowflake": "snowflake",
    "databricks": "databricks",
    "mariadb": "mariadb",
    "couchbase": "couchbase",
}

_manifest_cache: dict | None = None


def _load_manifest() -> dict:
    global _manifest_cache
    if _manifest_cache is None:
        with open(MANIFEST, encoding="utf-8") as f:
            _manifest_cache = json.load(f)
    return _manifest_cache


def _families(icons: list[str]) -> dict[str, set[str]]:
    """base brand name -> set of its variant filenames (without .svg)."""
    fam: dict[str, set[str]] = {}
    for name in icons:
        base = _VARIANT.sub("", name)
        fam.setdefault(base, set()).add(name)
    return fam


def _squish(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def search(fam: dict, query: str, limit: int = 8) -> list[str]:
    """Rank brand bases against the query (squished + per-token matching)."""
    q = _squish(query)
    tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if t]
    scored: dict[str, int] = {}
    for base in fam:
        b = _squish(base)
        s = 0
        if q and q == b:
            s = 100
        elif q and b.startswith(q):
            s = 60
        elif q and q in b:
            s = 40
        for t in tokens:
            if t == b:
                s = max(s, 90)
            elif len(t) >= 3 and b.startswith(t):
                s = max(s, 50)
            elif len(t) >= 3 and t in b:
                s = max(s, 30)
        if s:
            scored[base] = s
    return sorted(scored, key=lambda base: (-scored[base], base))[:limit]


def _search_supplement(query: str) -> str | None:
    q = _squish(query)
    if not q:
        return None
    if q in _SUPPLEMENT:
        return q
    for brand in _SUPPLEMENT:
        if q in brand or brand in q:
            return brand
    return None


def _pick_variant(base: str, variants: set[str], prefer: str) -> str | None:
    order = {"color": ["-color", "", "-text"],
             "mono":  ["", "-color", "-text"],
             "text":  ["-text", "-color", ""]}[prefer]
    for suffix in order:
        cand = base + suffix
        if cand in variants:
            return cand
    return next(iter(sorted(variants)), None)


def _download_svg(url: str) -> bytes | None:
    try:
        return urllib.request.urlopen(url, timeout=15).read()
    except Exception:  # noqa: BLE001
        return None


def _svg_to_png(svg: bytes, size: int = 256) -> bytes | None:
    """Convert SVG bytes to PNG bytes. Requires cairosvg (used elsewhere in logo_fetch)."""
    # Fix lobe-icons' 1em intrinsic size so cairosvg can scale it.
    svg = svg.replace(b'width="1em"', f'width="{size}"'.encode())
    svg = svg.replace(b'height="1em"', f'height="{size}"'.encode())
    try:
        import cairosvg
        return cairosvg.svg2png(bytestring=svg, output_width=size, output_height=size)
    except Exception:  # noqa: BLE001
        return None


def search_ai_brands(query: str, limit: int = 8, variant: str = "color") -> list[dict]:
    """Search AI/LLM brand logos by name. Returns list of match dicts with 'brand', 'file', 'style'."""
    manifest = _load_manifest()
    fam = _families(manifest["icons"])
    cdn = manifest["cdn"]
    matches = search(fam, query, limit)
    results = []
    if matches:
        for base in matches:
            file = _pick_variant(base, fam[base], variant)
            if file is None:
                continue
            url = f"{cdn}{file}.svg"
            results.append({"brand": base, "file": file, "url": url,
                            "style": _DRAWIO_STYLE + url})
    else:
        brand = _search_supplement(query)
        if brand:
            slug = _SUPPLEMENT[brand]
            url = _SIMPLEICONS_CDN + slug
            results.append({"brand": brand, "file": f"simpleicons:{slug}",
                            "url": url, "style": _DRAWIO_STYLE + url})
    return results


def lookup_ai_logo(name: str, icons_cache_dir: str, size: int = 256,
                   variant: str = "color") -> str | None:
    """Resolve an AI/LLM brand to a cached PNG path.

    Downloads the SVG from CDN and converts to PNG using cairosvg.
    Returns the absolute path to the PNG, or None if not found / cannot convert.
    The PNG is cached in `icons_cache_dir/ai-brands/<slug>.png`.
    """
    results = search_ai_brands(name, limit=1, variant=variant)
    if not results:
        return None
    r = results[0]
    cache_dir = Path(icons_cache_dir) / "ai-brands"
    cache_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", r["brand"].lower()).strip("-")
    png_path = cache_dir / f"{slug}.png"
    if png_path.exists():
        return str(png_path)
    svg = _download_svg(r["url"])
    if svg is None:
        return None
    png = _svg_to_png(svg, size)
    if png is None:
        # cairosvg unavailable — save as .svg for Graphviz (requires librsvg build)
        svg_path = cache_dir / f"{slug}.svg"
        svg_path.write_bytes(svg)
        return str(svg_path)
    png_path.write_bytes(png)
    return str(png_path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Find AI/LLM brand logos as draw.io styles (lobe-icons via CDN).")
    ap.add_argument("query", nargs="?", help='brand name, e.g. "openai" or "claude"')
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--variant", choices=["color", "mono", "text"], default="color")
    ap.add_argument("--size", type=int, default=48)
    ap.add_argument("--embed", action="store_true",
                    help="inline the SVG as a data URI (fetches it now; portable)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", action="store_true", help="list all brand names and exit")
    args = ap.parse_args()

    if not os.path.exists(MANIFEST):
        sys.exit(f"error: manifest not found at {MANIFEST}")
    manifest = _load_manifest()
    fam = _families(manifest["icons"])
    cdn = manifest["cdn"]

    if args.list:
        for base in sorted(fam):
            print(base)
        return
    if not args.query:
        ap.error("a query is required (or use --list)")

    matches = search(fam, args.query, args.limit)
    results = []
    if matches:
        for base in matches:
            file = _pick_variant(base, fam[base], args.variant)
            if file is None:
                continue
            url = f"{cdn}{file}.svg"
            if args.embed:
                svg = _download_svg(url)
                if svg is None:
                    sys.stderr.write(f"warning: could not fetch {url}\n")
                    continue
                svg = svg.replace(b'width="1em"', b'width="24"').replace(b'height="1em"', b'height="24"')
                image = "data:image/svg+xml," + base64.b64encode(svg).decode()
            else:
                image = url
            results.append({"brand": base, "file": file, "w": args.size, "h": args.size,
                            "style": _DRAWIO_STYLE + image})
    else:
        brand = _search_supplement(args.query)
        if brand:
            slug = _SUPPLEMENT[brand]
            url = _SIMPLEICONS_CDN + slug
            image = url
            if args.embed:
                svg = _download_svg(url)
                if svg:
                    image = "data:image/svg+xml," + base64.b64encode(svg).decode()
            results.append({"brand": brand, "file": f"simpleicons:{slug}",
                            "w": args.size, "h": args.size, "style": _DRAWIO_STYLE + image})

    if not results:
        sys.exit(f"no logo for {args.query!r}")

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for r in results:
            shown = r["style"] if len(r["style"]) < 160 else r["style"][:157] + "..."
            print(f"{r['brand']}  ({r['file']}, {r['w']}x{r['h']})\n  {shown}")


if __name__ == "__main__":
    main()
