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
g.grid_cluster("ecs", cols=3)      # poster planes: pack a cluster's boxes into a
                                   # dense COLS-wide logo grid (see Poster mode)
g.render("<workdir>/out")          # -> out.png  (LOOK at this)
```
`Pretty.render("<workdir>/out")` writes `out.png`, `out.dot`, `out.nodes.json`.
A bad ImportError/IMG path raises — read the traceback and fix it.

## Slide-style production output (the DEFAULT — flow-driven)
Default output: single-page 16:9 landscape, white background, **no blue hero band**
(`include_hero=False` by default). The engine scales the diagram to fit one page.
Use the slide wrapper instead of plain `g.render` unless the blueprint explicitly
says `presentation_style="diagram"`. The body diagram stays auditable/editable.

```python
from prettygraph import Pretty, render_slide

# sizes pre-computed in style_plan.json —
# paste its pretty_kwargs so icons/text scale with the cards:
g = Pretty("Document Understanding System Architecture",
           subtitle="end-to-end architecture",
           direction="LR",       # landscape — clusters arrange left to right
           flow_layout=True,     # real edges pull the layout (default)
           icons_root=ICONS, theme="pro",
           node_width=300, node_height=60, icon_size=44, title_size=16,
           sublabel_size=13, edge_label_size=13, cluster_label_size=18)

g.cluster("ingest", "① Data Ingestion", number=1, accent="blue")
g.box("src", "Data Source", kind="source",
      sublabel="S3 / APIs", icon="aws/storage/simple-storage-service.png", parent="ingest")
g.box("pipe", "ETL Pipeline", kind="compute",
      sublabel="Airflow", icon="onprem/workflow/apache-airflow.png", parent="ingest")

g.cluster("ai", "② AI Pipeline", number=2, accent="green")
g.box("embed", "Embeddings", kind="compute",
      sublabel="OpenAI text-3", icon="onprem/mlops/mlflow.png", parent="ai")
g.box("llm", "LLM", kind="compute",
      sublabel="GPT-4o", icon="onprem/mlops/mlflow.png", parent="ai")
g.box("rerank", "Re-ranker", kind="compute",
      sublabel="Cohere", icon="onprem/mlops/mlflow.png", parent="ai")
g.box("router", "Query Router", kind="compute",
      sublabel="LangChain", icon="onprem/mlops/mlflow.png", parent="ai")
g.grid_cluster("ai", cols=2)   # optional: force 2-wide; engine auto-packs ≥3-node regions

g.cluster("store", "③ Storage", number=3, accent="cyan")
g.box("vec", "Vector Store", kind="data",
      sublabel="Weaviate", icon="onprem/database/mongodb.png", parent="store")
g.box("rdb", "Metadata DB", kind="data",
      sublabel="PostgreSQL", icon="onprem/database/postgresql.png", parent="store")

# REAL cross-cluster edges — MANDATORY: they pull the layout and show connections.
# Color-code each edge by its semantic `flow` (from render_spec.json edge.flow):
# data | control | serving | registry | monitoring | security. `flow=` sets a
# consistent color + dash from the shared palette — do NOT hand-pick edge colors.
g.link("src", "pipe", flow="data", label="raw data")
g.link("pipe", "embed", flow="data", label="chunks")
g.link("embed", "vec", flow="data", label="vectors")
g.link("llm", "router", flow="serving", label="response")
g.link("monitor", "router", flow="monitoring")  # dashed automatically

render_slide(
    g, "out",
    title="AI Document Understanding System",
    diagram_title="DOCUMENT UNDERSTANDING SYSTEM ARCHITECTURE",
    # Pass render_spec.json["legend"] straight through: each row is
    # {"label": ..., "flow": ...} and the flow resolves the matching color/dash so
    # the legend always matches the arrows.
    legend=[
        {"label": "Data Flow", "flow": "data"},
        {"label": "Serving / Inference", "flow": "serving"},
        {"label": "Monitoring", "flow": "monitoring"},
    ],
    # include_hero=False  ← default; pass True only when user requests the blue band
)
```

Slide-mode hard rules:
- `direction="LR"`, `flow_layout=True` (defaults for `density="detailed"`).
- **Cross-cluster edges are MANDATORY** — they pull the layout and show connections.
  Every zone must link to at least one other. Color-code edges with `flow=`
  (data/control/serving/registry/monitoring/security); side-channels like
  `flow="monitoring"`/`flow="security"` render dashed automatically.
- **Grid packing is AUTOMATIC** — the engine packs every region with ≥3 boxes into
  a 2-wide grid and regions with ≥7 boxes into a 3-wide grid. You do NOT need to
  call `g.grid_cluster(...)` unless you want to force a specific column count (e.g.
  `g.grid_cluster("ai", cols=3)` for a wide region). Aim for **4-7 nodes per
  top-level region** — thin 1-2 box regions leave empty bands; fold them into the
  adjacent tier they serve.
- `theme="pro"` plus fixed `node_width` / `node_height`.
- Sizes are pre-computed in `style_plan.json` — pass its `pretty_kwargs` verbatim.
- Label fits are pre-computed in `label_fits.json` — apply every suggestion before rendering.
- Every top-level cluster has `number=1`, `number=2`, ... and a clear label.
- Include `legend` whenever >2 edge colors/styles appear.
- Still call `export_drawio()` after `render_diagram`.

## Poster mode (blueprint `density="poster"` — use ONLY when explicitly requested)
A dense wall-grid layout with 25-40 nodes. **Set `flow_layout=False`.**
Read the pre-computed sizes from `style_plan.json` (poster mode).

Group nodes into 4-8 numbered region planes. Pick direction by plane count:
**5+ planes → `direction="LR"`** (tall portrait poster); **≤4 planes →
`direction="TB"`** (planes side by side). Pack each plane into a compact grid:

```python
g = Pretty(title=..., subtitle=..., direction="LR",
           flow_layout=False, theme="pro", **sizes)  # 5+ planes

# one plane = one numbered cluster; add its boxes (real logo + tech sublabel)
g.cluster("ai", "② AI & Compute Engine", number=2, accent="green")
for nid, label, tech, icon in AI_NODES:
    g.box(nid, label, kind="compute", sublabel=tech, icon=icon, parent="ai")
g.grid_cluster("ai", cols=3)        # pack this plane into a 3-wide logo grid

# ... declare the other planes the same way, each with its own grid_cluster ...

# only a few cross-plane edges for the primary flow — they auto-relax so the
# grids drive the layout (do NOT call g.poster_grid; it fights the in-plane grids)
g.link("net0", "ai0", label="route")
g.link("ai0", "db0", label="query")
```

`cols=2` for ≤24 nodes, `cols=3` for denser posters (or per the `grid_cols` value
from `style_plan.json`). The panel auto-fits the body — fill the WIDTH with planes.

**Sub-groups encouraged:** nest clusters inside a plane for natural groupings
(model families, storage tiers, KB sources, parser types):
```python
g.cluster("inference", "⑤ Inference Layer", number=5, accent="violet")
g.cluster("llm_models", "LLM Models", kind="Compute", parent="inference")
g.cluster("embed_models", "Embedding Models", kind="Compute", parent="inference")
```

**Icon aliases for AI stack** (common NOT_FOUND entries — use these keywords):
| Service | `search_icons` keyword | provider |
|---|---|---|
| RAGFlow | `ragflow` → fallback `fetch_logo("RAGFlow")` | onprem |
| vLLM | `vllm` → fallback `fetch_logo("vLLM")` | onprem |
| MCP server | `mcp` → fallback `generic/compute/server.png` | generic |
| Docling | `fetch_logo("Docling")` | onprem |
| MinerU | `fetch_logo("MinerU")` | onprem |
| DeepDoc | `fetch_logo("DeepDoc")` | onprem |
| MinIO | `minio` | onprem |
| Qdrant | `qdrant` | onprem |

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
- **Always resolve paths with tools before using them:**
  - `search_icons("<service>", provider="<provider>")` — finds the exact path
    within a provider subtree (e.g. `search_icons("App Service", provider="azure")`).
  - `fetch_logo("<Product Name>")` — for brand logos not in the pack (Stripe,
    Twilio, etc.), returns `PATH: <file>` or `NOT_FOUND`.
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
3c. **No L-shaped layouts / vertical towers.** Never route the main flow along
   the bottom and then stack later tiers in one tall right-side column. That
   creates a huge blank center and a wall of edge labels. If the audit says
   `SPARSE CENTER`, `L-SHAPE WARNING`, or `SIDE-CHANNEL FANOUT`, rebuild as a
   balanced 3x2 or 4x2 grid: main flow across the top/middle row, Data/Security/
   Observability/CI-CD in the row directly beneath the columns they serve.
4. **Align within a tier:** `g.same_rank([...])` on a cluster's nodes → a neat row
   (LR) / column (TB), like centvra's Fargate grid.
5. **Collapse replicas.** N identical things → ONE box "(xN)", or two reps with a
   `g.box("dots", "...", kind="neutral")` between them + `g.same_rank([...])`.
6. **Few edges, one per concern, short, labeled.** Route monitoring/secrets/
   logging on ONE dashed side-channel, not one per node.
7. **Direction**: `LR` for request flows, `TB` for layered stacks/pipelines.
8. Keep only components that matter; if it looks busy, MERGE or DROP minor nodes.

### Spaghetti prevention
- Never draw one dashed line from each config/calibration file to each consumer.
  Collapse files into `Configuration Management` and draw one dashed edge into
  the service or service cluster.
- Never draw one metrics/logs edge per internal module. Draw one dashed edge from
  the processing service to `Observability` / `Monitoring`.
- Never draw one security/secrets/audit edge per app node. Collapse it to one
  dashed cluster-level concern edge (`ltail`/`lhead`) or one representative edge.
- No labeled edge should cross more than half the canvas. If it would, move the
  concern cluster adjacent/stacked, use a cluster-level edge, or omit the label.
- Never leave a labeled edge floating in blank space or visually pointing at no
  target. Long data flows into storage/search/analytics should terminate on the
  target cluster boundary with `ltail` / `lhead` where possible.
- If a label sits in a dense edge trunk, move it with `taillabel`, shorten the
  edge, or split the label so other lines do not cut through it.
- For client-facing diagrams, hide implementation details such as parser library
  names, in-place compaction, client threading modes, and per-file JSON names.

### Whitespace and layout
- Prefer 4-5 primary columns for client-facing architecture diagrams.
- Avoid oversized outer clusters with large dead space; size clusters through
  balanced contents and avoid wrapping the whole page in one giant container.
- Use cluster-to-cluster flow arrows with `ltail` / `lhead` for major stages so
  arrows hit block borders instead of weaving through inner boxes.
- Use uniform `node_width` / `node_height` when a client diagram has comparable
  capability boxes.
- For pipelines, the main path should read left-to-right: External I/O -> Input
  Stream -> Processing Service -> Output/Monitoring.
- For AWS customer diagrams with app services plus private databases/caches,
  include a visible VPC boundary with Public Subnet for edge/web ingress and
  Private Subnet for core services and data stores when it matches the design.

### Raw `diagrams` pitfalls learned from real issue reports
- Exact edge positioning is not a stable control surface. If an edge must appear
  above/below a cluster, redesign the layout: move clusters adjacent, add anchor
  nodes, shorten the edge, use `minlen`, or mark side/back edges
  `constraint="false"` instead of relying on `xlabel` or manual coordinates.
- Large cluster lists reorder unpredictably. Collapse replicas, use one
  representative node with a count, or switch to prettygraph rows with
  `same_rank` and invisible spine edges.
- Global label sizing belongs in `node_attr` and `edge_attr` for raw diagrams.
  Use per-edge `fontsize` only for exceptions.
- For health/status overlays, encode state with red/dashed edges, alert nodes,
  or status side-channels. Do not try to draw custom crosses or borders on
  built-in nodes.
- `render_diagram` runs the static audit automatically as a pre-flight gate;
  fix every high/medium finding it returns and re-call (no budget consumed).

## Pattern: AWS Multi-Account Production Focus
Use this when requirements mention AWS Organizations, governance, security
services, centralized monitoring, CI/CD, EKS/ECS, or multi-account production.
The goal is a production-readable architecture, not a full org inventory.

Layout:
- Keep external actors outside account clusters: End Users, Admin/DevOps, GitHub,
  third-party monitoring.
- Put `Management Account` or `Security/Shared Services Account` in a separate
  top/right-side block with Organizations/IAM Identity Center, CloudTrail,
  GuardDuty/Security Hub, Config, CloudWatch, and Secrets Manager grouped by
  capability.
- Put `Production Account` on the main path. Inside it, use:
  `Static Frontend Hosting` (CloudFront + S3), `VPC`, `Public Subnets`
  (ALB/NAT/IGW), `Private Subnets` (EKS/ECS + VPC endpoints), and `Data`
  (RDS/Aurora/PostgreSQL).
- Put CI/CD as a side lane: GitHub/GitHub Actions -> registry -> deployment
  controller such as ArgoCD -> compute cluster.
- Put Monitoring/Security as side-channel clusters adjacent to the resources
  they observe. Use one dashed/dotted representative edge per concern instead of
  fanning out to every node.

Simplification:
- If Dev/Staging accounts exist but the brief is production-focused, collapse
  them into one `Non-Production Accounts` summary box or omit them.
- If a cluster needs external account-level links, create an explicit anchor
  node inside it (`Account`, `VPC`, `Security Hub`, `Observability`) and connect
  edges to that node. Do not connect to a cluster boundary as if it were a node.
- Keep concern colors limited: user/API blue, CI/CD slate/brown, management teal,
  security red/dotted, monitoring blue-gray/dashed. Edge labels stay under two
  short lines.

## Workflow
1. Plan tiers, clusters, the few typed edges.
2. Use `search_icons` / `fetch_logo` to resolve all icon paths before writing code.
3. Write the complete `prettygraph` script.
4. Call `render_diagram(code=<complete script>)` — the tool runs the script and
   returns the rendered PNG **plus a layout audit**. On error it returns the
   traceback — read and fix.
5. **Read the LAYOUT AUDIT first** (objective check the eye misses): it reports the
   page `aspect` ratio, any label-bearing edges that span too far (`STRAND RISK`),
   and canvas fill (`LOW FILL`). Act on every warning:
   - `TOO WIDE` → fold cross-cutting tiers into stacked columns (rule 3b).
   - `STRAND RISK` → move those cluster endpoints adjacent/stacked so the edge
     and label stay short.
   - `LOW FILL` → the page is airy; add missing per-node detail, merge thin
     1-2-box regions into adjacent tiers, keep connected regions adjacent.
   Never finalize with an unresolved audit warning.
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
Keep labels short (≤ ~26 chars) so they fit; push detail into a short `sublabel=`.

## 2. One icon FAMILY (so logos look consistent)
Mixing aws + azure + saas + programming logos looks noisy. For an infographic,
pick ONE family and use it for every box — `azure/general/*` is a clean
line-style set (file, files, tag, table, cubes, gear, workflow, search-grid,
versions, counter, support, usericon, log-streaming, dashboard, …). Verify each
path with `search_icons("<name>", provider="azure")` — a wrong path silently
drops the icon.

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

---

## ML/DL Diagram Preset

Use for neural network architectures (BERT, ResNet, LLM pipelines, RAG systems, etc.).

### Node kinds — `ml_*` color coding
| kind | color | use for |
|------|-------|---------|
| `ml_input` | green | Data input, dataset, feature extraction |
| `ml_embed` | amber | Embedding, tokenizer, positional encoding |
| `ml_conv` / `ml_pool` | blue | Conv layers, pooling, downsampling |
| `ml_attention` / `ml_transformer` | purple | Attention heads, transformer blocks, MHA |
| `ml_rnn` / `ml_lstm` | yellow | RNN, LSTM, GRU cells |
| `ml_fc` / `ml_dense` | orange | Fully connected, linear, dense layers |
| `ml_norm` | gray | BatchNorm, LayerNorm, Dropout |
| `ml_loss` | red | Loss function, objective, softmax output |
| `ml_output` | dark green | Final output, predictions, logits |

### Cluster kinds — `ML_*` tints
Use for grouping layers by stage: `ML_Input`, `ML_Embedding`, `ML_Encoder`,
`ML_Attention`, `ML_Decoder`, `ML_Output`, `ML_Training`, `ML_Inference`, `ML_Pipeline`.

### Example — Transformer encoder
```python
g = Pretty("BERT Encoder Architecture", subtitle="12-layer bidirectional transformer",
           direction="TB", icons_root="<icons_root>")

g.cluster("inp", "Input", kind="ML_Input")
g.box("tokens", "Tokenizer", kind="ml_input", sublabel="WordPiece", parent="inp")
g.box("posenc", "Positional Encoding", kind="ml_embed", parent="inp")

g.cluster("enc", "Encoder Block ×12", kind="ML_Attention")
g.box("mha", "Multi-Head Attention", kind="ml_attention", sublabel="12 heads, d=768", parent="enc")
g.box("ffn", "Feed-Forward Network", kind="ml_fc", sublabel="d_ff=3072", parent="enc")
g.box("ln", "LayerNorm + Residual", kind="ml_norm", parent="enc")

g.cluster("out", "Output", kind="ML_Output")
g.box("cls", "[CLS] Representation", kind="ml_output", sublabel="768-dim", parent="out")
g.box("pool", "Pooler (tanh)", kind="ml_dense", parent="out")

g.link("tokens", "posenc", label="token ids")
g.link("posenc", "mha", label="embeddings\n768-dim")
g.link("mha", "ffn", label="attended")
g.link("ffn", "ln", label="transformed")
g.link("ln", "cls", label="sequence")
g.link("cls", "pool", label="[CLS] token")
```

### Tips for ML/DL diagrams
- Direction: `TB` for layer stacks (best for encoder/decoder architectures)
- Direction: `LR` for data pipelines (best for training/inference flows)
- Annotate tensor shapes in `sublabel`: `sublabel="[B, 512, 768]"` 
- Collapse `×N` repeated blocks: one box with `sublabel="×12 layers"` is cleaner
- Use `same_rank` to align parallel branches (encoder/decoder)
- For RAG architectures: use standard node kinds (source, data, compute, messaging)
  for the retrieval/generation flow; reserve `ml_*` kinds for the model internals

---

## AI/LLM Brand Icons (NEW)

The `fetch_logo` tool now resolves **321 AI/LLM brand logos** automatically via
lobe-icons CDN before falling back to web scraping. Just call `fetch_logo` with
the brand name — no need to guess paths:

```
fetch_logo("claude")        -> /icons/ai-brands/claude.png
fetch_logo("openai")        -> /icons/ai-brands/openai.png  
fetch_logo("langchain")     -> /icons/ai-brands/langchain.png
fetch_logo("qdrant")        -> /icons/ai-brands/qdrant.png  (simple-icons fallback)
fetch_logo("huggingface")   -> /icons/ai-brands/huggingface.png
```

Supported brands include: Claude, Anthropic, OpenAI, Gemini, Mistral, Llama, Ollama,
LangChain, LangGraph, LangSmith, LlamaIndex, HuggingFace, Cohere, CrewAI, PydanticAI,
DeepSeek, Grok, Groq, Perplexity, Replicate, Together, Fireworks, NVIDIA, Azure AI,
Vertex AI, Bedrock, Tavily, Dify, n8n, Zapier, and 290+ more.

---

## draw.io Shape Search (NEW)

Use `search_drawio_shapes` to **confirm the canonical vendor/service shape exists
and find the right keyword** (instead of guessing `mxgraph.*` names):

```
search_drawio_shapes("aws lambda")    -> confirms the official AWS Lambda shape
search_drawio_shapes("k8s pod")       -> confirms the Kubernetes Pod shape
search_drawio_shapes("dynamodb")      -> confirms DynamoDB shape + dimensions
```

Covers 10,446 shapes: AWS, Azure, GCP, Cisco, Kubernetes, UML, BPMN, ER, flowchart,
network, electrical, P&ID, and more.

**Important — how this export works:** the `.drawio` is generated from your
prettygraph script (each node becomes a `shape=label` box with `icon=` + theme
colour by `kind`). The export does NOT consume a raw `style=` string, so use the
result to pick the right icon (`search_icons` / `fetch_logo` → `icon=`), not to
paste a style. For non-architecture types (ERD / UML / sequence / flowchart) and
the full mapping, see `diagrams-as-code/reference/drawio_export.md`.

---

## Code Structure Visualization (NEW)

To visualize a Python codebase's module dependencies or class hierarchy:

```python
# In the agent, call:
result = visualize_code_structure(
    project_path="/path/to/project",
    mode="imports",   # or "classes"
    language="python",
    group=True        # group by sub-package into nested clusters
)
# result is a JSON graph with nodes/edges/groups
# then use the graph to build a prettygraph diagram
```

Use cases: architecture reviews, onboarding diagrams, refactor planning, dependency audits.
