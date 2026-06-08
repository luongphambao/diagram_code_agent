---
name: pro-style
description: Build production-quality architecture diagrams in the "centvra/deepstream" house style using the prettygraph helper — title + subtitle, semantically-COLORED rounded node boxes (icon on the left + bold label), tinted nested clusters, and gray concern-labeled edges. Consult before writing a pretty-style diagram.
---

# pro-style

You produce diagrams that look like a senior solutions architect made them — like
the reference images `centvra_aws_preview` and `deepstream_poc_preview`. The clean
look comes from a small, consistent visual language, applied with the
`prettygraph` helper (already uploaded to your workdir as `prettygraph.py`).

## Why prettygraph (not raw `diagrams`)
The mingrammer `diagrams` default node is icon-on-top / label-below with NO box —
it looks plain. `prettygraph` renders each node as a **rounded, color-filled box
with the icon on the LEFT and a bold label** (+ optional gray sub-label), inside
**tinted clusters**, with a **title/subtitle** and **gray concern-labeled edges**.
It outputs `out.png` (rendered by Graphviz `dot`) AND a styled editable `out.drawio`.

## API (write a script, then run it)
```python
import sys; sys.path.insert(0, "<workdir>")   # so `import prettygraph` works
from prettygraph import Pretty

g = Pretty("Title", subtitle="one-line context", direction="LR",
           icons_root="<icons_root>")          # e.g. /icons

# clusters (tinted boxes). kind picks the tint — see palette below. Nest with parent=.
g.cluster("ecs", "AWS ECS Cluster", kind="Compute")
g.cluster("net", "VPC", kind="Network")

# nodes: kind picks the box color; icon is a path UNDER icons_root. Use icons for
# the vendor that matches the stack (one family per diagram) — all clouds work
# the same way: aws/…, azure/…, gcp/…, oci/…
g.box("user", "User", kind="source")                              # ungrouped
g.box("alb", "AWS Load Balancer", kind="network",
      icon="aws/network/elastic-load-balancing.png", parent="net")
g.box("svc", "ECS Service", kind="compute", sublabel="FastAPI Backend",
      icon="aws/compute/elastic-container-service.png", parent="ecs")
g.box("db", "Supabase", kind="data", sublabel="PostgreSQL",
      icon="onprem/database/postgresql.png")
# Azure / GCP equivalents (same shape, different provider subtree):
#   icon="azure/compute/app-services.png"   icon="azure/database/sql-databases.png"
#   icon="gcp/compute/run.png"              icon="gcp/database/sql.png"

# edges: label by CONCERN, short. style="dashed" for side-channels.
g.link("user", "alb", label="HTTPS")
g.link("alb", "svc", label="API Call")
g.link("svc", "db", label="SQL + vector")

g.same_rank(["svc", "db"])         # optional: force a clean row
g.render("<workdir>/out")          # -> out.png  (LOOK at this)
```
`Pretty.render("<workdir>/out")` writes `out.png`, `out.dot`, `out.nodes.json`.
A bad ImportError/IMG path raises — read the traceback and fix it.

## Node `kind` -> box color (use the right one for meaning)
- `source` / `io` — clients, users, inputs (blue)
- `network` — load balancers, gateways, VPC, DNS (purple)
- `compute` / `process` — services, workers, GPU, processing (green)
- `data` — databases, stores, warehouses (deep blue)
- `messaging` — queues, brokers, event streams (red)
- `monitoring` / `aux` — metrics, logs, calibration, config (orange)
- `security` — IAM, secrets (red)
- `neutral` — notes and the `"..."` collapse node (gray)

## Cluster `kind` -> tint (cloud-neutral palette)
`Compute` (peach), `Database` (blue), `Network` (purple), `Security` (red),
`Storage` (green), `IoT` (mint), `Management` (pink), `Neutral` (gray).
Tints are by tier, not by vendor — use them for any cloud.

## Icons (no blank boxes!)
- Icons live under `icons_root` as `<provider>/<category>/<name>.png`
  (providers: aws, azure, gcp, oci, ibm, alibabacloud, onprem, programming, saas,
  k8s, generic, …). The pack covers the major clouds equally well (Azure ~800,
  AWS ~525, GCP ~120 icons) — there is NO reason to default to AWS.
- **Always resolve paths with tools before using them — planned, bounded search:**
  - Make an exact icon plan first: one entry per visible node that truly needs an
    icon. Exclude legend, spacers, generic notes, and nodes where `icon=` should
    be omitted. Each entry has `{label, provider, icon_keyword}`.
  - Generate `icon_keyword` in the icon-pack filename dialect: short product noun,
    not full marketing label. Examples: `Amazon Aurora PostgreSQL Server` ->
    `aurora`, `AWS App Runner` -> `app runner`, `CloudFront CDN` -> `cloudfront`,
    `Azure Container Apps` -> `container apps`, `GCP Cloud Run` -> `run`,
    `Cloud SQL` -> `sql`, `Cloud Pub/Sub` -> `pubsub`.
  - `plan_icons(icons=[...])` declares the list first and sets fallback search
    budget to `unique planned icons * 3`.
  - `resolve_icons(icons=[...])` resolves the whole plan in ONE tool call. Use
    the returned `icon` relative path for prettygraph, or `path` if absolute is
    required.
  - `search_icons(icon_keyword, provider="<provider>")` is fallback for misses
    only. Never call it more than 3 times for the same icon/query/provider; total
    fallback search budget is `unique planned icons * 3`.
  - `fetch_logo("<Product Name>")` — for brand logos not in the pack (Stripe,
    Twilio, etc.); call ONLY for specific services that returned NOT_FOUND from
    local icon search, not for every service upfront.
  - NEVER guess a path — a wrong path silently drops the icon.
- If no icon exists, omit `icon=` (the box still renders with color) or use a
  generic one (e.g. `onprem/client/users.png`, `generic/database/sql.png`).
- Pick the icon for the vendor that matches the stack and keep the WHOLE diagram
  in that one family — never mix an `aws/…` icon into an Azure/GCP/OCI diagram.
  Use `onprem`/`saas`/`programming` for tech logos (PostgreSQL, Redis, Kafka,
  Python, React…) regardless of cloud.

## Layout discipline — CLEAR BLOCKS (this is what makes it clean)
Reference: deepstream / centvra — every component sits in a labeled block, blocks
flow in one direction, arrows are short and rarely cross.
1. **Title + subtitle always.** Subtitle = version / option / one-line scope.
2. **EVERY node belongs to a cluster.** Group into tiers: Client · Edge/Hosting ·
   Application · Data · AI · Monitoring · CI/CD. The only box allowed outside a
   cluster is a single entry actor (User). Nest only for real containment
   (VPC ⊃ subnet ⊃ service; ECS Cluster ⊃ tasks).
3. **Order clusters along the flow; place connected clusters ADJACENT** so edges
   stay short. Never let an edge cross the whole canvas or double back — reorder
   instead. Declare nodes/clusters in flow order.
3b. **≤5 cluster COLUMNS — fold a wide strip into a balanced grid.** A single row
   of 6-7 clusters renders as a cramped 3:1 strip: tiny text + stranded labels.
   When you have many tiers, **STACK each cross-cutting tier (Security, Monitoring,
   CI/CD) in the SAME column as the flow tier it serves.** This makes the page a
   balanced ~1.3–2:1 grid AND keeps every side-channel edge short (the secrets/
   logs/metrics/deploy labels then sit on short edges instead of floating). How:
   pin one node per column with an invisible spine, then `same_rank` a node of
   each stacked cluster onto that column:
   ```python
   # 4 flow columns: Edge -> Application -> AI -> Data
   for a, b in [("lb","nextjs"), ("nextjs","gemini"), ("gemini","cloud_sql")]:
       g.link(a, b, style="invis")              # spine fixes the 4 columns
   g.same_rank(["lb", "cloud_build"])           # CI/CD stacks under Edge   (col1)
   g.same_rank(["nextjs", "identity"])          # Security stacks under App (col2)
   g.same_rank(["gemini", "cloud_logging"])     # Monitoring stacks under AI (col3)
   # now decision->secret, decision->logs, artifact->nextjs are all SHORT.
   ```
4. **Align within a tier:** `g.same_rank([...])` on a cluster's nodes → a neat row
   (LR) / column (TB), like centvra's Fargate grid.
5. **Collapse replicas.** N identical things → ONE box "(xN)", or two reps with a
   `g.box("dots", "...", kind="neutral")` between them + `g.same_rank([...])`.
6. **Few edges, one per concern, short, labeled.** Route monitoring/secrets/
   logging on ONE dashed side-channel, not one per node.
7. **Direction**: `LR` for request flows, `TB` for layered stacks/pipelines.
8. Keep only components that matter; if it looks busy, MERGE or DROP minor nodes.

## Workflow
1. Plan tiers, clusters, the few typed edges.
2. Make the exact icon plan with `icon_keyword`, call `plan_icons(icons=[...])`
   to lock the list, then call `resolve_icons(icons=[...])` once for those icons;
   then use `search_icons` or `fetch_logo` only for NOT_FOUND brands.
3. Write the complete `prettygraph` script.
4. Call `render_diagram(code=<complete script>)` — the tool runs the script and
   returns the rendered PNG **plus a layout audit**. On error it returns the
   traceback — read and fix.
5. **Read the LAYOUT AUDIT first** (objective check the eye misses): it reports the
   page `aspect` ratio and any label-bearing edges that span too far and will
   STRAND. If it says TOO WIDE → fold cross-cutting tiers into stacked columns
   (rule 3b). If it lists strand-risk edges → move those endpoints into adjacent/
   stacked clusters. Never finalize with an unresolved audit warning.
6. THEN LOOK at the PNG like a reviewer: title present? every box has its real icon
   (no blanks)? clusters tinted & non-overlapping? edges labeled and not crossing?
   collapse applied? Fix the script and call `render_diagram` again (≤3).

---

# Staged process-flow infographics (numbered stages + bottom band)

Some asks are NOT a service-architecture diagram but a **staged process flow**
like a slide/infographic: a row of NUMBERED stages, each a short list of steps,
a bold left→right arrow through the stages, an optional **cross-cutting band**
(governance / operational controls) pinned at the very bottom, and a dashed
feedback loop. Reproduce these with the techniques below — they make the result
look hand-designed and balanced, not like a raw graphviz dump.

## 0. Turn on the PRO theme (premium look — use it for anything client-facing)
Pass `theme="pro"` to `Pretty`. It upgrades the whole figure to a modern,
designed look: a cohesive accent palette assigned per stage, **numbered badges**
in each stage header, clean accent-bordered cards on lightly-tinted sections,
crisp high-DPI raster (160), generous spacing, refined slate edges, and soft
shadows in the editable .drawio. `theme="default"` keeps the legacy look.
```python
g = Pretty(title, subtitle="one-line context", direction="LR", icons_root=ICONS,
           node_width=270, node_height=46, theme="pro")
# number => the badge; accent => pin a color (else auto-assigned in declared order)
g.cluster("s1", "Approved Product Sources", number=1, accent="blue")
g.cluster("s2", "Data Ingestion & Preparation", number=2, accent="cyan")
# accents: blue cyan teal violet indigo green amber rose slate
# (a cross-cutting band like governance reads best as accent="slate", no number)
```
In pro theme a box's `kind` no longer drives its color — every box becomes an
accent card of its stage. Keep `kind` meaningful anyway (it still documents
intent and drives the default theme). Tune `dpi=` for an even sharper export.

## 1. Uniform boxes (so blocks look balanced)
Pass `node_width`/`node_height` (points) to `Pretty` — EVERY box becomes that
fixed size, icon flush-left, so all blocks align identically. Without this,
boxes size to their text and look ragged.
```python
g = Pretty(title, ..., node_width=270, node_height=46, theme="pro")  # uniform pills
```
Keep labels short (≤ ~26 chars) and sublabels shorter (≤ ~24 chars) so they fit.
If detail is longer, abbreviate, split into another box, or widen boxes; never
ship clipped text.

For a Legend, do NOT put all entries in one long sublabel such as
`solid=sync · dashed=obs · dotted=deploy`. Split entries into short lines/nodes
(`Solid: sync`, `Dashed: obs`, `Dotted: deploy`) or give the legend extra width.

## 2. One icon FAMILY (so logos look consistent)
Mixing aws + azure + saas + programming logos looks noisy. For an infographic,
pick ONE family and use it for every box — `azure/general/*` is a clean
line-style set (file, files, tag, table, cubes, gear, workflow, search-grid,
versions, counter, support, usericon, log-streaming, dashboard, …). Verify each
paths with one `resolve_icons(icons=[...])` batch; a wrong path silently drops
the icon. Use `search_icons` fallback only for misses, and do not search any one
icon more than 3 times.

## 3. Bold flow arrows that go CLUSTER→CLUSTER (the key to aligned clusters)
If a flow edge connects a node *inside* cluster A to a node *inside* cluster B,
graphviz pulls those two nodes level and **staggers the clusters** (staircase).
Fix: keep the edge endpoints (for ranking) but **clip the visible arrow to the
cluster borders** with `ltail`/`lhead` (needs `compound=true`, which `Pretty`
sets). Make the main path bold + colored with `penwidth`; thin/dashed for side
concerns. Use `constraint=False` on a long back-edge (feedback loop) so it does
NOT drag clusters out of alignment.
```python
FLOW = "#2D6CDF"
g.link("src_top", "ing_top", label="ingest", color=FLOW, penwidth=2.6,
       ltail="cluster_s1", lhead="cluster_s2")          # arrow between BLOCKS
g.link("out_last", "ing_top", label="feedback", style="dashed", color="#82b366",
       ltail="cluster_s6", lhead="cluster_s2", constraint=False)   # no distortion
```
The cluster subgraph name is `cluster_<id>` (the id you passed to `g.cluster`).

## 4. Balanced clusters — can I set a cluster size?
Graphviz has **no direct width/height attribute for a cluster**; a cluster
auto-sizes to its contents. So you get balanced clusters by controlling the
CONTENTS, two ways:
- **Equal box count + uniform box size** → equal cluster size. Simplest; give
  every stage the same number of boxes (merge/split steps to hit the count).
- **Different counts are fine IF you equalize height**: pad shorter stages with
  an invisible spacer box so every cluster reaches the same height:
  `g.box("s5_pad", " ", kind="neutral", parent="s5")` (blank label). Graphviz
  centers cluster contents, so without padding, fewer boxes ⇒ a shorter cluster.
For pixel-exact tile sizes, render each stage as its own region and composite
(below) — that fully decouples cluster size from box count.

## 5. Pin a cross-cutting band to the bottom — REGION COMPOSITING
Graphviz cannot pin a horizontal band (e.g. "Operational Controls") to the
bottom of an LR flow — it lands at the top. Don't fight it: lay out each region
on its own and stack them with the prettygraph helpers.

All of this goes in ONE script passed to `render_diagram(code=...)`:
```python
from prettygraph import Pretty, vstack_pngs, merge_drawios_vertical

flow = build_flow()       # Pretty: numbered stages + arrows + feedback loop
band = build_band()       # Pretty(" ", direction="TB"): ONE cluster, 1 row of
                          # boxes, g.same_rank([...]) → horizontal row, NO edges
flow.render("_main"); fx = flow.to_drawio("_main")
band.render("_band"); bx = band.to_drawio("_band")
vstack_pngs(["_main.png", "_band.png"], "out.png", gap=26)        # composited PNG
merge_drawios_vertical([fx, bx], "out.drawio", gap=26)            # merged, editable
```
`vstack_pngs` centers each region; `merge_drawios_vertical` namespaces cell ids
per region and offsets geometry so the editable .drawio matches the PNG. The
script must produce `out.png` + `out.drawio` (render_diagram validates this).

## Infographic review checklist (in addition to the one above)
- All stages the SAME height and aligned on one baseline (uniform boxes + equal
  counts or padding)? Arrows run border-to-border between stages, not from a box
  inside one? Main path bold/colored, side concerns thin/dashed? Band sits at the
  very bottom spanning the width? Feedback loop dashed and not distorting ranks?
