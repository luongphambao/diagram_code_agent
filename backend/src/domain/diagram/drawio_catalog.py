"""draw.io stencil catalog — ground-truth icon/group names + verbatim styles.

Ported from drawio-ai-kit/src/core.mjs (loadCatalog / searchIcon /
styleForIcon / styleForGroup). The catalog data lives under
``resources/drawio_catalog/*.json`` (copied verbatim from the kit; AWS styles
are taken verbatim from data/shape-index.json.gz, jgraph/drawio-mcp Apache-2.0).

Purpose:
  - Guarantee stencil names are real (the AI cannot invent ``mxgraph.aws4.*``
    names that render blank).
  - Provide the exact ``style=`` string to paste so an icon renders as a crisp
    native vector shape in draw.io instead of an embedded base64 PNG.

Used by:
  - validate_drawio.py — to validate every resIcon/grIcon against the catalog
    and to suggest near matches.
  - prettygraph/drawio.py — to emit native stencils instead of base64 images
    when a node maps to a known stencil.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

FAMILY = "mxgraph.aws4"

# backend/src/domain/diagram/drawio_catalog.py -> parents[4] == repo root
_CATALOG_DIR = Path(__file__).resolve().parents[4] / "resources" / "drawio_catalog"
# AWS is the primary file; sibling packs (bigdata/database/...) merge on top.
_PRIMARY = _CATALOG_DIR / "aws.json"


class Catalog:
    """Loaded, indexed stencil catalog."""

    def __init__(self) -> None:
        self.meta: dict = {}
        self.category_colors: dict[str, str] = {}
        self.icons: list[dict] = []
        self.groups: list[dict] = []
        self.by_name: dict[str, dict] = {}
        self.valid_names: set[str] = set()

    def _add_pack(self, pack: dict) -> None:
        for it in pack.get("icons", []) or []:
            self.icons.append(it)
            self.by_name[it["name"]] = {**it, "kind": "icon"}
        for g in pack.get("groups", []) or []:
            self.groups.append(g)
            self.by_name[g["name"]] = {**g, "kind": "group"}
        self.category_colors.update(pack.get("categoryColors", {}) or {})
        self.valid_names = set(self.by_name.keys())


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    """Read aws.json plus every sibling pack, building a lookup index (cached)."""
    cat = Catalog()
    if not _PRIMARY.exists():
        return cat
    primary = json.loads(_PRIMARY.read_text(encoding="utf-8"))
    cat.meta = primary.get("meta", {})
    cat._add_pack(primary)
    for f in sorted(_CATALOG_DIR.glob("*.json")):
        if f == _PRIMARY:
            continue
        try:
            cat._add_pack(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return cat


def _norm(s: object) -> str:
    s = unicodedata.normalize("NFKD", str(s if s is not None else ""))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


# Vendor shorthand -> the words that actually appear in catalog entry names.
# Catalog names spell products out ("key_management_service"), while specs and
# labels use the abbreviation everyone says ("AWS KMS") — without this table
# those queries score 0 and the node renders icon-less. Expansions ADD tokens
# (the original stays, so exact-name entries like "s3" still get their bonus).
_ABBREV: dict[str, str] = {
    # AWS
    "kms": "key management service",
    "sqs": "simple queue service",
    "sns": "simple notification service",
    "s3": "simple storage service s3",
    "ses": "simple email service",
    "ec2": "ec2 elastic compute",
    "ecs": "ecs elastic container service",
    "eks": "eks elastic kubernetes service",
    "ecr": "elastic container registry",
    "emr": "emr elastic mapreduce",
    "rds": "rds relational database",
    "alb": "application load balancer",
    "elb": "elastic load balancing",
    "nlb": "network load balancer",
    "ddb": "dynamodb",
    "sfn": "step functions",
    "acm": "certificate manager",
    "msk": "managed streaming for apache kafka",
    "waf": "waf web application firewall",
    "route53": "route 53",
    "cfn": "cloudformation",
    "cw": "cloudwatch",
    # Azure
    "aks": "kubernetes service",
    "acr": "container registry",
    "adf": "data factory",
    "aad": "azure active directory",
    "entra": "entra active directory",
    "apim": "api management",
    "nsg": "network security group",
    "vnet": "virtual network",
    "adls": "data lake storage",
    "asb": "service bus",
    "cosmos": "cosmos db",
    # GCP
    "gke": "kubernetes engine",
    "gcs": "cloud storage",
    "bq": "bigquery",
    "gcr": "container registry",
    "pubsub": "pub sub",
    "vpcsc": "vpc service controls",
}


def expand_tokens(tokens: list[str]) -> list[str]:
    """Tokens + the words their abbreviations expand to (order kept, deduped)."""
    out = list(tokens)
    seen = set(out)
    for t in tokens:
        for w in _ABBREV.get(t, "").split(" "):
            if w and w not in seen:
                seen.add(w)
                out.append(w)
    return out


def _score_entry(entry: dict, q_tokens: list[str], q_raw: str) -> int:
    name = _norm(entry.get("name"))
    haystack = _norm(" ".join(str(x) for x in [
        entry.get("name", ""), entry.get("label", ""), entry.get("category", ""),
        entry.get("tags", ""), *(entry.get("aliases") or []),
        *(entry.get("keywords") or []),
    ]))
    score = 0
    if name == q_raw:
        score += 100
    if name.replace(" ", "") == q_raw.replace(" ", ""):
        score += 60
    name_words = name.split(" ")
    for t in q_tokens:
        if not t:
            continue
        if t in name_words:
            score += 25
        elif t in name:
            score += 12
        if t in haystack:
            score += 6
    return score


def _color_for(cat: Catalog, entry: dict) -> str:
    return entry.get("color") or cat.category_colors.get(entry.get("category"), "#232F3E")


def style_for_icon(cat: Catalog, name: str, width: int | None = None,
                   height: int | None = None) -> dict | None:
    """Full draw.io style for a resource icon (verbatim from the catalog)."""
    entry = cat.by_name.get(name)
    if not entry:
        return None
    if entry.get("style"):
        return {"style": entry["style"],
                "width": width or entry.get("w", 48),
                "height": height or entry.get("h", 48)}
    color = _color_for(cat, entry)
    style = (
        f"sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;fillColor={color};"
        "strokeColor=none;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;align=center;"
        f"html=1;fontSize=12;fontStyle=0;aspect=fixed;shape={FAMILY}.resourceIcon;resIcon={FAMILY}.{name};"
    )
    return {"style": style, "width": width or 48, "height": height or 48}


def style_for_group(cat: Catalog, name: str) -> dict | None:
    """Style for a group container (AWS Cloud / Region / VPC / AZ ...)."""
    entry = cat.by_name.get(name)
    if entry and entry.get("style"):
        return {"style": entry["style"], "width": entry.get("w"), "height": entry.get("h")}
    stroke = (entry or {}).get("stroke") or "#232F3E"
    fill = (entry or {}).get("fill") or "none"
    dashed = 1 if (entry or {}).get("dashed") else 0
    style = (
        "sketch=0;outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=12;fontStyle=0;"
        f"container=1;pointerEvents=0;collapsible=0;recursiveResize=0;shape={FAMILY}.group;"
        f"grIcon={FAMILY}.{name};strokeColor={stroke};fillColor={fill};verticalAlign=top;align=left;"
        f"spacingLeft=30;fontColor={stroke};dashed={dashed};"
    )
    return {"style": style}


def _decorate(cat: Catalog, entry: dict, score: int | None = None) -> dict:
    if entry.get("kind") == "group":
        style_obj = style_for_group(cat, entry["name"]) or {}
    else:
        style_obj = style_for_icon(cat, entry["name"]) or {}
    out = {
        "name": entry["name"],
        "fqn": f"{FAMILY}.{entry['name']}",
        "label": entry.get("label", entry["name"]),
        "category": entry.get("category"),
        "kind": entry.get("kind"),
        "color": _color_for(cat, entry),
        "aliases": entry.get("aliases", []),
        "style": style_obj.get("style"),
    }
    if style_obj.get("width"):
        out["width"] = style_obj["width"]
        out["height"] = style_obj["height"]
    if score is not None:
        out["score"] = score
    return out


def search_icon(cat: Catalog, query: str, category: str | None = None,
                limit: int = 8, kind: str | None = None) -> list[dict]:
    """Search for an icon/group by keyword; returns ranked decorated entries."""
    q_raw = _norm(query)
    q_tokens = expand_tokens([t for t in q_raw.split(" ") if t])
    cat_filter = _norm(category) if category else None
    ranked: list[tuple[dict, int]] = []
    for entry in cat.by_name.values():
        if kind and entry.get("kind") != kind:
            continue
        if cat_filter:
            ec = _norm(entry.get("category"))
            if ec != cat_filter and cat_filter not in ec:
                continue
        score = _score_entry(entry, q_tokens, q_raw)
        if score > 0:
            ranked.append((entry, score))
    ranked.sort(key=lambda r: r[1], reverse=True)
    return [_decorate(cat, e, s) for e, s in ranked[:limit]]


def get_icon(cat: Catalog, name: str) -> dict | None:
    entry = cat.by_name.get(name)
    return _decorate(cat, entry) if entry else None
