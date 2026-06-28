# .drawio export — how it works here & shape/diagram-type guidance

Read this when the user asks for an editable `.drawio` file, names a non-architecture
diagram type (ERD / UML class / sequence / flowchart), or you reach for
`search_drawio_shapes`. Adapted from the community **drawio-skill** (MIT) — but this
project's `.drawio` is produced by a different pipeline, so the rules differ.

## How the `.drawio` is actually produced (important)
You do NOT hand-write `.drawio` XML. The flow is:

1. You write a **prettygraph** script (`g.box / g.cluster / g.link`) and call
   `render_diagram` → `out.png` + `out.dot` + `out.nodes.json` (sidecar).
2. `export_drawio()` runs `prettygraph.dot_to_drawio` (Graphviz lays out `out.dot`;
   the sidecar carries per-node `kind/fill/stroke/icon/sublabel`).
3. Every node is emitted as a draw.io **`shape=label`** box — icon-left + bold
   label + theme fill/stroke. Edges are orthogonal with a centered label.

Consequences — keep these straight:
- **Labels are auto-escaped** (`html.escape`). Do NOT pre-escape `&`/`<`/`>` or
  add `&#xa;` yourself — write plain text in `label=`/`sublabel=`.
- **Node colour comes from `kind`**, not from any style string you pass. See the
  `kind → colour` and `ml_* → colour` tables in `pro-style/SKILL.md`.
- The sidecar has **no field for a raw drawio `style=`**, so a style string from
  `search_drawio_shapes` is NOT injected per-node — it would be dropped.

## What `search_drawio_shapes` is for here
Use it to **confirm the canonical vendor/service shape exists and find the right
keyword**, then resolve the actual icon with `search_icons` / `fetch_logo` and pass
it via `icon=`. Treat the returned `style=` as confirmation/metadata, not as
something to paste into the export.

```
search_drawio_shapes("aws lambda")   # confirms the official AWS Lambda shape/name
search_icons("lambda", provider="aws")   # → real icon path for icon=
```

Pick the icon for the vendor that matches the stack and keep ONE family per diagram
(see `pro-style` "Icons"). For 321 AI/LLM brand logos use `fetch_logo("claude")`,
`fetch_logo("langchain")`, etc.

## Diagram-type requests → prettygraph vocabulary
prettygraph is an architecture / flow tool. Map type requests onto its `kind`s:

| Request | Build with |
|---|---|
| **ERD** | one `g.box(kind="data")` per table; columns/PK·FK in `sublabel`; `g.link(label="FK")` between tables; `direction="TB"` |
| **UML class** | `g.box(kind="compute")` per class; attributes/methods summarised in `sublabel`; inheritance as `g.link(label="extends")`; `direction="TB"` |
| **Flowchart** | start/end `kind="source"`, steps `kind="compute"`, decisions `kind="messaging"` with `Yes`/`No` edge labels; `direction="TB"` |
| **Sequence** | not prettygraph's strength — prefer a left→right flow of `kind="compute"` actors with ordered, labelled `g.link`s, or tell the user a true lifeline diagram needs manual draw.io |
| **ML / Deep learning** | use the **ML/DL preset** already in `pro-style/SKILL.md` (`ml_*` kinds, `ML_*` cluster tints, tensor shapes in `sublabel`) |

## Layout & correctness
The transferable principles (spacing to avoid overlap, short labelled edges, one
concern per edge, every node in a cluster, mandatory cross-cluster edges) all live
in `pro-style/SKILL.md` — follow those.

After `export_drawio()`, read the **Lint** line it returns (from `validate_drawio`).
It now reports three buckets: **errors** (must fix before `finalize_diagram` —
e.g. an invented stencil name or a dangling edge), **warnings**, and **design
advice** (a deterministic pre-critic check, ported from drawio-ai-kit). The advice
catches, WITHOUT a render, the same "looks auto-generated" tells the visual critic
would flag — act on it before re-rendering so you don't burn render/vision passes:

- **Recolored icon** → keep each icon's category colour (Compute orange, Storage
  green, Database pink/magenta, Security red, Networking purple). Don't override it.
- **Too many font sizes / oversized text** → ≤ 4 distinct sizes, label text ≤ 14px;
  put the title in its own area, not as a giant in-canvas label.
- **Palette too scattered** → ≤ ~8 background fill colours; reserve strong colour
  for notes/accents. Prefer `light-dark(...)` tokens so it reads in dark mode too.
- **Fan-out branch should be sharp + pinned** → for one-source→many-targets, use
  `rounded=0` and pin `exitX/exitY`+`entryX/entryY` so the parallel lines align.
  This is the single biggest hand-made-vs-auto tell.
- **Edge label on a bent (L/Z) route** → add one waypoint in the middle of the
  corridor so the label sits centred on a straight segment.
- **Stacked arrowheads (fan-in)** / **overlap** / **child spills its frame** /
  **edge runs through an unrelated node** / **long detour connectors** → these are
  PLACEMENT smells: move nodes closer, keep shared resources next to their
  consumers, and give edges a clear lane.

`validate_drawio --profile aws_native|generic|auto` controls which audits run; the
export uses `auto` (AWS-convention checks only fire when the diagram uses
`mxgraph.aws4.*` stencils).

## Appendix — raw mxgraph styles (reference only, NOT auto-applied)
If a future raw-XML export or manual draw.io edit is needed, these are the official
style strings per diagram type (from drawio-skill's `diagram-types.md`):
ERD table `shape=table;startSize=30;container=1;childLayout=tableLayout;…`,
UML class `swimlane;fontStyle=1;startSize=26;html=1;`, sequence lifeline
`shape=umlLifeline;perimeter=lifelinePerimeter;…`, flowchart decision
`rhombus;whiteSpace=wrap;html=1;`. Fetch exact strings on demand with
`search_drawio_shapes("<vendor shape>")`. These are documentation only — the
prettygraph export above does not consume them.
