---
name: diagrams-as-code
description: How to write clean, production-quality architecture diagrams with the Python `diagrams` (mingrammer) library — the official Node/Cluster/Edge/Diagram idioms, exact node import names, and gallery-quality layout patterns. Consult before writing any `diagrams` code.
---

# diagrams-as-code

Write `diagrams` code that renders like the official gallery. The clean look
comes from STRUCTURE (variables + chaining, list fan-out, nested clusters,
edges colored/labeled by concern) — not from fighting the layout engine.

## Reference files (read them — do not guess)
- `reference/cloud_services.md` — **for any NON-AWS cloud (Azure, GCP, OCI, IBM,
  Alibaba), check this FIRST.** Maps product names → exact imports (the class
  names are non-obvious: "Azure Functions" → `FunctionApps`, "Cloud Run" → `Run`).
  AWS is well-covered; the other clouds are where wrong guesses happen.
- `reference/nodes.md` — EVERY importable node class, grouped by
  `diagrams.<provider>.<module>`. Look up exact class names here before
  importing. 1998 classes across 17 providers (aws, gcp, azure, onprem, k8s,
  programming, saas, digitalocean, …). Grep it, e.g. `grep -i redis reference/nodes.md`.
- `reference/patterns.md` — full worked examples to imitate, for AWS **and**
  Azure/GCP/OCI/IBM. The idioms are provider-agnostic: keep the WHOLE diagram in
  one provider's node set — never mix AWS icons into an Azure/GCP/OCI diagram.

## Diagram object
```python
from diagrams import Diagram, Cluster, Edge
with Diagram("Title", filename="/workspace/out", outformat=["png", "dot"],
             show=False, direction="LR", graph_attr=graph_attr):
    ...
```
- `direction`: `LR` (request flows, left→right) or `TB` (layered stacks /
  fan-out trees). Also `BT`, `RL`. Choose deliberately.
- `outformat=["png","dot"]` ALWAYS (the .dot is converted to editable .drawio).
- `filename` has no extension. `theme="neutral"` (or blues/greens/orange/pastel)
  for cohesion. `graph_attr/node_attr/edge_attr` pass Graphviz attrs through.

## Node
- Import: `from diagrams.<provider>.<module> import <Class>` — names from
  `reference/nodes.md` ONLY. A component shown as a bare logo-less box is a bug.
- Instantiate with a label, store in a variable: `web = ECS("web1")`.
- For a product with NO built-in node (e.g. Label Studio, Weights & Biases,
  Jetson), include it in the icon plan first. Call `fetch_logo("<Product Name>")`
  only if `resolve_icons` returns `NOT_FOUND` for that planned product and
  fallback `search_icons` also returns no icon; it validates a brand logo and
  returns the exact file path. Use that path in `Custom("<Product>", "<PATH>")`.
  On `NOT_FOUND`, fall back to a generic built-in node.
- **Non-AWS cloud services with no built-in class** (common on GCP/OCI/IBM): make
  an exact icon plan with a short `icon_keyword` in the icon-pack filename style
  (`Cloud Run` -> `run`, `Cloud SQL` -> `sql`, `Cloud Pub/Sub` -> `pubsub`,
  `Azure Container Apps` -> `container apps`). Then call `plan_icons(icons=[...])`
  to lock the list and call `resolve_icons(icons=[...])` once for all planned
  missing services. Use `search_icons(icon_keyword, provider="<provider>")` only
  for misses. Never search the same icon/query/provider more than 3 times; total
  fallback search budget is `unique planned icons * 3`. Never fall back to an AWS
  node or a generic box for a named cloud service.
- MLflow → built-in `from diagrams.onprem.mlops import Mlflow` (do NOT fetch it).
- NEVER guess paths like `/icons/generic/file.png` — they usually do NOT exist
  and render a blank box. For generic concepts (dataset, file, user, database,
  server) use a real built-in node from `reference/nodes.md`, e.g.
  `diagrams.generic.storage.Storage`, `diagrams.onprem.client.Users`,
  `diagrams.generic.database.SQL`.

## Cluster (this is what makes diagrams look organized)
- `with Cluster("Service Cluster"):` groups nodes in a labeled box.
- **Nest freely** (no depth limit) to show hierarchy, e.g. `Cluster("Event
  Flows")` containing `Cluster("Workers")` + `Cluster("Processing")`.
- Put anything that "lives inside" something (a VPC, an ECS cluster, an HA pair)
  in its own cluster.

## Edge & operators (avoid spaghetti)
- `a >> b` (arrow), `a << b` (reverse), `a - b` (undirected/peer link).
- **Collapse replicas — this is the #1 rule against spaghetti.** If something
  has N identical copies (e.g. "Task Fargate (x4)", "3 workers"), draw exactly
  ONE node labeled with the count, e.g. `Fargate("Task Fargate (x4)")`. Do NOT
  create N separate nodes. Wording like "(x4)" / "N replicas" means *one node*,
  not four. Only draw multiple nodes when they are genuinely DIFFERENT things.
- When you do have a real list, use **list fan-out / fan-in**:
  `lb >> [web1, web2, web3] >> db` — never one edge per item.
- **A source connects to a group ONCE.** Never draw an edge from a source to
  each of several targets that represent the same role (e.g. ECR→each task,
  SSM→each task, each task→CloudWatch). Connect to the single collapsed node.
- Style/label by concern: `a >> Edge(label="API", color="#5B8DD6") >> b`.
  Give each concern its own color (request path, CI/CD, data). Keep labels short.
- HA / peer pairs: `primary - Edge(style="dashed") - replica`.
- Side-channels (monitoring, secrets) clutter the main flow — connect ONE
  representative node and use a dashed edge (optionally `constraint="false"`).

## Graphviz limits and edit rules
- Do not promise exact edge placement. `diagrams` delegates layout to Graphviz;
  precise "route this edge above that cluster" control is fragile. Prefer moving
  clusters adjacent, adding explicit anchor nodes, using short edges, `minlen`,
  `constraint="false"` for side/back edges, or simplifying the path.
- Avoid `Edge(xlabel=...)` for important labels; it can float away from the
  visible arrow. Prefer short `label`, `taillabel`, or `headlabel`, and make the
  edge shorter by changing layout.
- Large repeated clusters/nodes have unstable ordering. Collapse replicas into
  one node such as `Worker (x12)`, or show two representatives plus an ellipsis.
- Use `node_attr` for node label defaults and `edge_attr` for edge label defaults.
  Graph-level `fontsize` does not reliably control all node/edge labels.
- To show unhealthy/degraded state, encode status with a red/dashed edge, a small
  status/alert node, or a red alert side-channel. Built-in nodes are not good
  targets for custom cross marks or per-node border overlays.
- Before rendering, call `audit_diagram_code(code=...)` and fix high/medium
  findings unless they are clearly irrelevant.

## Recipe for a clean diagram
1. Pick `direction`. 2. Declare nodes as variables, grouped by `Cluster`.
3. Connect with chained operators + lists so the code reads like the flow.
4. Color/label edges by concern; dashed for peers/side-channels.
5. Call `render_diagram(code=<complete Python script>)`. The tool runs it and
   returns the rendered PNG — LOOK at it, fix overlaps / missing logos, repeat
   (≤3 renders). On error it returns the traceback — read it and fix the script.
See `reference/patterns.md` for worked examples to copy.
