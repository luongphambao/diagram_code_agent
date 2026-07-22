"""Static pre-flight audit for diagram-rendering scripts.

Pure functions — no execution, no file writes. Runs automatically inside
``render_diagram`` (tools/rendering_tools.py) as a pre-flight gate before the
script is ever handed to ``render_exec.run_render``, so an obviously-defective
script (missing filename/outformat, no cross-cluster edges, ...) is rejected
at zero execution cost instead of burning a render-budget slot.
"""

from __future__ import annotations

import re


def _audit_add(findings: list[dict], severity: str, rule: str, detail: str, suggestion: str) -> None:
    findings.append(
        {
            "severity": severity,
            "rule": rule,
            "detail": detail,
            "suggestion": suggestion,
        }
    )


def _audit_code(code: str) -> dict:
    """Static audit of a diagram script for known `diagrams`/Graphviz pitfalls.

    Pure function (no execution, no file writes). Runs automatically inside
    `render_diagram` as a pre-flight gate, so the model no longer needs a
    separate audit tool call carrying the full script a second time.
    """
    findings: list[dict] = []
    raw_diagram = "Diagram(" in code
    pretty = "Pretty(" in code or "render_slide(" in code

    if raw_diagram:
        if (
            'filename="out"' not in code
            and "filename='out'" not in code
            and 'filename="/workspace/out"' not in code
            and "filename='/workspace/out'" not in code
        ):
            _audit_add(
                findings,
                "high",
                "output_filename",
                'Raw Diagram(...) code does not visibly set filename="out".',
                'Use Diagram(..., filename="out", outformat=["png", "dot"], show=False).',
            )
        if "outformat" not in code:
            _audit_add(
                findings,
                "high",
                "output_format",
                "Raw Diagram(...) code does not set outformat.",
                'Set outformat=["png", "dot"] so PNG and DOT are produced for draw.io export.',
            )
        if "show=False" not in code:
            _audit_add(
                findings,
                "medium",
                "show_false",
                "Raw Diagram(...) code does not visibly set show=False.",
                "Use show=False to avoid opening a viewer during automated rendering.",
            )

    if (
        pretty
        and not re.search(r"\.render\(\s*[\"'](?:/workspace/)?out[\"']", code)
        and "render_slide(" not in code
    ):
        _audit_add(
            findings,
            "high",
            "pretty_output",
            "Pretty code does not visibly render to out.",
            'End diagram-only scripts with g.render("out") or slide scripts with render_slide(g, "out", ...).',
        )

    if (
        re.search(r"graph_attr\s*=.*fontsize", code, re.DOTALL)
        and "edge_attr" not in code
        and "node_attr" not in code
    ):
        _audit_add(
            findings,
            "medium",
            "font_defaults",
            "fontsize appears only in graph_attr; that does not reliably size all node/edge labels.",
            "Use node_attr for node label defaults, edge_attr for edge label defaults, or Edge(fontsize=...) for an explicit edge.",
        )

    if "xlabel=" in code:
        _audit_add(
            findings,
            "medium",
            "floating_xlabel",
            "Edge(xlabel=...) can float in open space and detach visually from the arrow.",
            "Prefer short Edge(label=...), taillabel/headlabel for endpoint labels, or move/stack clusters so the edge is short.",
        )

    if re.search(r"\b(pos|x|y)\s*=", code):
        _audit_add(
            findings,
            "medium",
            "manual_positioning",
            "Manual pos/x/y-style positioning is present; Graphviz dot usually ignores fixed positions.",
            "Control layout through direction, declaration order, same_rank, invisible spine edges, minlen, and simpler clusters.",
        )

    if re.search(r"Cluster\([^)]*graph_attr\s*=[^)]*orientation", code, re.DOTALL) or "orientation" in code:
        _audit_add(
            findings,
            "low",
            "cluster_orientation",
            "Cluster orientation hints are present; cluster-local ordering is often not dependable in diagrams/Graphviz.",
            "Use main graph direction, declaration order, same_rank/invisible edges, or collapse repeated nodes.",
        )

    for match in re.finditer(r"range\(([^)]*)\)", code):
        nums = [int(n) for n in re.findall(r"\d+", match.group(1))]
        if nums:
            start = nums[0] if len(nums) > 1 else 0
            stop = nums[1] if len(nums) > 1 else nums[0]
            if abs(stop - start) >= 6:
                _audit_add(
                    findings,
                    "medium",
                    "large_replicas",
                    f"Loop {match.group(0)} may create many similar nodes, which often produces unstable cluster ordering.",
                    "Collapse replicas into one node labeled with the count, or show at most two representatives plus an ellipsis.",
                )
                break

    edge_labels = re.findall(r"Edge\([^)]*label\s*=\s*[\"']([^\"']+)[\"']", code)
    for label in edge_labels:
        flat = " ".join(label.split())
        if len(flat) > 28 or "\n" in label:
            _audit_add(
                findings,
                "low",
                "long_edge_label",
                f"Long edge label detected: {flat[:60]}",
                "Keep edge labels short, ideally 1-4 words; move detail into node sublabels or a legend.",
            )
            break

    if re.search(r"unhealthy|not healthy|failed|down", code, re.IGNORECASE) and not re.search(
        r"color\s*=\s*[\"']#?(?:d|c|e|f|red)", code, re.IGNORECASE
    ):
        _audit_add(
            findings,
            "low",
            "health_status",
            "Health/status language appears without an obvious red/error visual encoding.",
            "Show degraded status with a red/dashed edge, a small status node, or a red security/alert concern rather than trying to mutate built-in node borders.",
        )

    is_slide = "render_slide(" in code
    cluster_count = code.count("g.cluster(")
    is_poster = "flow_layout=False" in code or ("density='poster'" in code or 'density="poster"' in code)
    has_link = "g.link(" in code
    has_cross_cluster_edge = has_link  # any edge could be cross-cluster; we check below

    if is_slide and cluster_count >= 6:
        has_numbered = "number=" in code

        if is_poster:
            # Poster / wall-grid mode: require structural grid for each plane.
            has_grid = "grid_cluster(" in code or "poster_grid(" in code
            has_invis_spine = has_grid or 'style="invis"' in code or "style='invis'" in code

            if not has_invis_spine:
                _audit_add(
                    findings,
                    "high",
                    "poster_missing_spine",
                    f"Poster mode ({cluster_count} clusters) has no grid structure — "
                    "planes will sprawl and the layout will be sparse.",
                    "Pack each region: g.grid_cluster(region_id, cols=2 or 3) after its "
                    "boxes, and set Pretty(..., flow_layout=False) + direction='LR'.",
                )
            if "grid_cluster(" not in code and "poster_grid(" in code:
                _audit_add(
                    findings,
                    "medium",
                    "poster_uses_legacy_grid",
                    "Poster uses g.poster_grid (single-column ranks) instead of dense "
                    "in-plane grids — the diagram will read sparse, not like the reference.",
                    "Replace poster_grid with one g.grid_cluster(region_id, cols=N) per "
                    "plane so each plane packs into a dense logo grid.",
                )
        else:
            # Flow mode (default): require cross-cluster edges for visible connections.
            if not has_link:
                _audit_add(
                    findings,
                    "high",
                    "flow_missing_edges",
                    f"Flow mode ({cluster_count} clusters) has no g.link() calls — "
                    "clusters will be disconnected islands with no visible flow.",
                    "Add real cross-cluster g.link() edges for the primary data flow. "
                    "In flow_layout=True mode these edges pull the layout AND show "
                    "connections between zones — they are mandatory.",
                )
            elif cluster_count >= 4 and code.count("g.link(") < cluster_count - 1:
                _audit_add(
                    findings,
                    "medium",
                    "flow_few_cross_cluster_edges",
                    f"Flow mode has {code.count('g.link(')} edges for {cluster_count} "
                    "clusters — many zones may appear disconnected.",
                    "Add cross-cluster g.link() edges to connect every zone to the "
                    "primary flow. The connections are what make the diagram readable.",
                )

        if not has_numbered:
            _audit_add(
                findings,
                "high",
                "missing_cluster_numbers",
                f"Diagram with {cluster_count} clusters has no number= arguments.",
                "Add number=1, number=2, ... to every top-level g.cluster() call.",
            )

    if not findings:
        return {"verdict": "PASS", "findings": []}
    verdict = "REVISE" if any(f["severity"] in {"high", "medium"} for f in findings) else "PASS_WITH_NOTES"
    return {"verdict": verdict, "findings": findings}
