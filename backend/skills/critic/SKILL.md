---
name: critic
description: Visual quality standards for reviewing rendered architecture diagrams — what a production-quality diagram must have, common defects with concrete symptoms, and a calibrated severity guide. Consult before writing findings.
---

# critic

You are reviewing a rendered PNG against an approved blueprint. This skill
documents the quality bar, the defect taxonomy, and what NOT to file.

## What a clean diagram looks like

### Layout
- **Balanced aspect ratio**: ~1.3–2.0:1 (width:height). Anything above 2.6:1 is
  too wide — text gets small, labels strand.
- **Every node inside a cluster**: Client · Edge/Hosting · Application · Data ·
  AI · Monitoring · CI/CD. Only a single entry actor (User/Browser) may float
  outside. A bare box outside any cluster is a defect.
- **No spaghetti**: edges go in one direction; no whole-canvas crossing arrows.
  Label-bearing edges that span >50% of the canvas will strand — they are a
  defect when the layout audit flags them.
- **No floating labeled edges**: labels such as generated reports, semantic
  index, conflict log, or store scores must clearly attach to the target node or
  cluster; labels floating in blank space are readability defects.
- **No label clashes**: important labels must not be cut through by dense edge
  trunks. If a label like candidate/consent/scores is crossed by multiple lines,
  file a readability defect.
- **Security boundary visible when expected**: AWS client diagrams with public
  ingress plus private app/data resources should show VPC/Public Subnet/Private
  Subnet boundaries unless the blueprint explicitly says they are out of scope.
- **Natural main flow**: the primary data path should read in one visual
  direction. A pipeline that jumps down, up, then back across the page is a
  blocking layout defect.
- **Sibling tiers**: Data and Application/Compute are separate sibling clusters,
  never nested. A "data" cluster inside an "application" cluster is a defect.
- **Collapsed replicas**: N identical services = ONE box labeled "(xN)".
- **Observability aggregated**: monitoring/secrets on ONE dashed side-channel,
  not fanned out per service.
- **Configuration aggregated**: config/calibration files collapse into one
  `Configuration Management` capability with one dashed side-channel edge, not
  one edge per file/consumer.
- **Client-facing abstraction**: for client or architecture-level diagrams,
  visible code details such as parser libraries, in-place compaction,
  non-blocking client internals, individual JSON filenames, and per-module
  metrics are readability defects.

### Visual completeness
- **Every node has a real icon** — no blank/placeholder boxes.
- **Correct provider icons**: an Azure architecture uses Azure icons; GCP uses
  GCP icons. No AWS icons in a non-AWS diagram.
- **Legend present and complete**: when the diagram uses ANY mixed edge styles
  (solid + dashed, or solid + dotted, or color-coded edges), the legend MUST
  explain EVERY distinct style/color used — not just acknowledge their existence.
  A legend that lists only "solid=request" but omits the dashed style is a
  readability defect (medium). A completely missing legend when >1 style is used
  is a higher readability defect (medium).
- **Security boundary visible when security_level is high or critical**: a
  diagram with `security_level=high` or `security_level=critical` MUST show
  explicit network/IAM boundaries (VPC/subnet, trust zone, security group
  cluster) for the compute and data tiers. Absence of any security boundary on
  a high/critical diagram is a **medium** finding (severity: medium → blocks
  finalize).
- **No empty visible shapes**: no blank rounded rectangles or spacer boxes.
- **No clipped/truncated text**: node labels, sublabels, edge labels, and Legend
  text must fit inside their boxes. If text is visibly cut off at a box edge
  (for example a long Legend like `solid=... dashed=... dotted=...` on one line),
  file a readability defect.

### pretty-style specific (prettygraph diagrams)
- Every cluster is tinted (has a colored background).
- Diagram has a title + subtitle.
- Nodes have colored boxes (not plain graphviz default).
- Orchestration diagrams number the primary path: (1), (2), (3)…

## Defect severity

| Severity  | Examples |
|-----------|---------|
| `critical` | Render is broken; topology is wrong (edges connect wrong nodes; whole tier missing) |
| `high`    | Blueprint node/edge missing; blank icon box; visible empty shape; Data nested in Application; orchestration flow not numbered |
| `medium`  | Crossing or whole-canvas edges; aspect ratio > 2.6:1 (layout audit TOO WIDE); clipped/truncated text; overlapping labels; floating un-clustered nodes; floating labeled edges; missing expected VPC/subnet boundary; mixed edge styles without Legend; incomplete legend (style used but not explained); absent security boundary when security_level=high/critical; per-service observability lines instead of one aggregated channel; per-file config fan-out; primary-flow backtracking; client-facing code-level clutter |
| `low`     | Minor misalignment; small inconsistency; negligible impact; pillar_gap (Well-Architected pillar undocumented — file as `pillar_gap` category, `in_blueprint=false`, severity `low`) |

## Do NOT file
- **Taste / aesthetics**: "would look nicer if…", color preferences, nudging boxes.
- **Speculation** about what isn't visible in THIS render.
- **Scope-policing the blueprint**: the blueprint was approved by the user. Set
  `in_blueprint=false` for out-of-scope observations — they do NOT block finalize.
- **Duplicates**: N nodes with the same defect → ONE finding listing all nodes.
- Anything the layout audit did NOT flag and you cannot see in the image.

## Verdict rule
- Any `medium`+ in-blueprint finding → `VERDICT: REVISE`
- Only `low` or out-of-blueprint findings → `VERDICT: PASS`
- Reserve REVISE for defects a careful architect would also send back.
- Keep findings tight: 3–5 maximum. A wall of nits is noise.
