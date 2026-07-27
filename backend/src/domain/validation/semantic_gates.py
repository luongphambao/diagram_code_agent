"""Spec-level semantic invariants (I1-I4) for the architecture blueprint.

Ported from `docs/improve/semantic_gates.py` (external analysis), REWORKED per
`docs/improve/REVIEW-CODEBASE-FIT.md` §1: the original drop-in ran on the
rendered `.drawio` XML, which is the WRONG layer — `layout_plan._bundle_edges`
(refined preset) deliberately suppresses up to 40% of edges into a single
labelled "representative" so a dense canvas stays readable (see
`_BUNDLE_EDGE_CAP`). A card whose 3 edges were all folded into one bundle
representative looks orphaned on the rendered page even though the BLUEPRINT
declared every relationship — gating on the rendered artifact would send a
correct blueprint back for "more edges" it already has, forever.

These gates run on the render_spec (before bundling), where every declared
node/edge is still visible 1:1. `layout_plan`'s bundling then compresses the
PRESENTATION without touching what these gates already verified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Edges whose class is one of these are cross-cutting/side-channel (telemetry,
# identity/secrets plane, deferred work) — real architecture diagrams leave
# these unlabelled or terse on purpose (playbook: "self-evident sink arrows"),
# so I3's label-quality check only applies to what's left: the primary
# request/data/execution path a reader actually needs explained.
_NON_PRIMARY_CLASSES = {"monitoring", "control", "future"}

_WEAK_LABEL_RX = re.compile(
    r"^(data|calls?|uses?|flow[s]?|sync|api|request|response|link|"
    r"connect(s|ion)?|n/?a|tbd|todo|misc|other|various)$",
    re.I,
)

_AWS_FAMILY_RX = re.compile(r"mxgraph\.(aws4)\.")
_OTHER_FAMILY_RX = re.compile(r"mxgraph\.(azure\w*|gcp\w*|kubernetes|veeam|cisco\w*)\.")


@dataclass
class Finding:
    code: str  # "I1".."I4"
    message: str
    severity: str  # "hard" | "warn"
    ids: list[str] = field(default_factory=list)

    def __str__(self) -> str:  # so `str(finding)` reads like the other audits' plain messages
        return self.message


def _edge_class(e: dict) -> str:
    """Mirrors layout_plan.py's own `_class(e)` — same alias table, so a gate
    finding and the renderer's own bundling decision never talk past each
    other about what class an edge belongs to."""
    from prettygraph.native.refined_theme import FLOW_ALIAS

    flow = str(e.get("flow") or e.get("style") or "").lower()
    return FLOW_ALIAS.get(flow, flow)


def _is_annotation(n: dict) -> bool:
    """Legend/note/KPI-tile nodes aren't architecture components — a note
    explaining a zone has no business needing an inbound/outbound edge."""
    return str(n.get("kind") or "").lower() in {"note", "legend", "kpi"}


def _is_waived(code: str, node_or_edge_id: str, waivers: list[dict]) -> bool:
    for w in waivers:
        if w.get("code") == code and node_or_edge_id in (w.get("ids") or []):
            return True
    return False


def audit_spec_semantics(spec: dict, plan: dict | None = None) -> list[Finding]:
    """I1 (orphan components) / I2 (relationship density) / I3 (weak primary
    labels) / I4 (icon family mixing) — all measured on the SPEC, before
    layout_plan bundles/suppresses anything.

    ``plan`` (layout_plan.analyze_layout's output) is optional context for I4
    only (icon family is a render-time/catalog concern, not declared in the
    spec) — I1-I3 need nothing but the spec itself.
    """
    findings: list[Finding] = []
    waivers = spec.get("waivers") or []
    nodes = [n for n in (spec.get("nodes") or []) if n.get("id")]
    edges = [e for e in (spec.get("edges") or []) if e.get("from") and e.get("to")]
    components = [n for n in nodes if not _is_annotation(n)]
    comp_ids = {n["id"] for n in components}

    # I1 — every component must have at least one relationship.
    touched: set[str] = set()
    for e in edges:
        touched.add(e["from"])
        touched.add(e["to"])
    orphans = sorted(nid for nid in comp_ids if nid not in touched and not _is_waived("I1", nid, waivers))
    if orphans:
        findings.append(
            Finding(
                code="I1",
                severity="hard",
                ids=orphans,
                message=(
                    f"I1 orphan: {len(orphans)}/{len(components)} component(s) have no "
                    f"relationship in the blueprint ({', '.join(orphans[:6])}"
                    f"{', ...' if len(orphans) > 6 else ''}). Every component must be "
                    "deleted, merged into another component, or connected — a component "
                    "with no relationship is not architecture."
                ),
            )
        )

    # I2 — relationship density. A component INVENTORY (edges << components)
    # reads as "here's what exists", not "here's how it works together".
    if comp_ids:
        ratio = len(edges) / len(comp_ids)
        if ratio < 1.0:
            findings.append(
                Finding(
                    code="I2",
                    severity="hard",
                    message=(
                        f"I2 density: edge/component ratio = {ratio:.2f} (< 1.00, measured "
                        "on the DECLARED blueprint, before any presentation-layer "
                        "bundling collapses parallel edges). This reads as a component "
                        "inventory, not an architecture — add relationships or remove "
                        "components that don't participate in any flow."
                    ),
                )
            )

    # I3 — primary-path edges need a real label, not a placeholder/empty one.
    # Side-channel classes (monitoring/control/future) are exempt — those are
    # legitimately terse by convention, not an authoring gap.
    bad_primary = []
    for e in edges:
        if _edge_class(e) in _NON_PRIMARY_CLASSES:
            continue
        label = str(e.get("label") or "").strip()
        eid = f"{e['from']}->{e['to']}"
        if _is_waived("I3", eid, waivers):
            continue
        if not label or _WEAK_LABEL_RX.match(label):
            bad_primary.append(eid)
    if bad_primary:
        findings.append(
            Finding(
                code="I3",
                severity="hard",
                ids=bad_primary,
                message=(
                    f"I3 label: {len(bad_primary)} primary-path edge(s) have an empty or "
                    f"generic label ({', '.join(bad_primary[:6])}"
                    f"{', ...' if len(bad_primary) > 6 else ''}). A primary edge's label "
                    "is a contract, not a caption — protocol + auth if known "
                    "(e.g. 'HTTPS · OIDC', 'AMQP · at-least-once'), or at minimum what "
                    "actually crosses the wire."
                ),
            )
        )

    # I4 — one icon family per diagram (vendor stencils only; provider is the
    # declared hosting, so an on-prem spec dragging in AWS icons is a
    # self-inflicted credibility problem before a review board even convenes).
    families: dict[str, list[str]] = {}
    for n in nodes:
        style = str(n.get("style") or "")
        icon = str(n.get("icon") or "")
        text = f"{style} {icon}"
        m = _AWS_FAMILY_RX.search(text) or _OTHER_FAMILY_RX.search(text)
        if m:
            families.setdefault(m.group(1).split("_")[0], []).append(n["id"])
    if len(families) > 1:
        findings.append(
            Finding(
                code="I4",
                severity="hard",
                message=(
                    f"I4 icon family: mixing {sorted(families)} vendor icon families in "
                    "one diagram. Pick one family that matches the declared hosting, or "
                    "use neutral/generic shapes for anything outside it."
                ),
            )
        )
    hosting = str(spec.get("hosting") or spec.get("provider") or "").lower()
    if hosting in {"onprem", "on-premises", "on-prem"} and "aws4" in families:
        findings.append(
            Finding(
                code="I4",
                severity="hard",
                ids=families["aws4"],
                message=(
                    f"I4 icon family: {len(families['aws4'])} AWS icon(s) used on a "
                    "declared on-premises architecture — this is a self-inflicted "
                    "credibility problem before a review board even convenes."
                ),
            )
        )

    # I6 — bundle integrity: refined.py's Interface Register lists exactly
    # plan["edge_bundles"][*]["members"] (see _render_interface_register).
    # That's true by construction today, but nothing enforced it — this
    # gate is the regression guard, catching the day bundling and register
    # rendering silently drift apart and a folded relationship stops being
    # traceable anywhere.
    if plan:
        registered = {
            (m[0], m[1], m[2] if len(m) > 2 else "")
            for b in (plan.get("edge_bundles") or [])
            for m in (b.get("members") or [])
        }
        suppressed = {(s[0], s[1], s[2] if len(s) > 2 else "") for s in (plan.get("suppressed_edges") or [])}
        missing = sorted(f"{f}->{t}" for f, t, _l in suppressed - registered)
        if missing:
            findings.append(
                Finding(
                    code="I6",
                    severity="hard",
                    ids=missing,
                    message=(
                        f"I6 bundle integrity: {len(missing)} folded relationship(s) do not "
                        f"appear in any bundle's member list ({', '.join(missing[:6])}"
                        f"{', ...' if len(missing) > 6 else ''}). Bundling must fold a "
                        "relationship into the Interface Register, never drop it silently."
                    ),
                )
            )

    return findings
