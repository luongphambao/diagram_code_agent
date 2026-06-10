# Plan: Combine diagram-as-code + next-ai-draw-io for production-grade diagrams

## Context

The repo has **two diagram engines** that are complementary, not redundant:

- **`backend/` — diagram-as-code (the brain).** Deep Agents (LangGraph) orchestration:
  requirement-analysis → tech-stack → blueprint → **drawer** subagent → **critic** subagent →
  finalize, all gated by HITL. Real icon-resolution pipeline (`resolve_icons`/`search_icons`/
  `fetch_logo` over a 2,465-icon local pack + Iconify fallback), a `prettygraph` house-style
  renderer, and an evals harness (structural F1 + vision judge). This is the superior system.
- **`next-ai-draw-io/` — raw mxGraph XML (the rendering substrate).** The LLM emits native
  draw.io XML using **native vector stencils** (`shape=mxgraph.aws4.resourceIcon;resIcon=…`,
  `image=img/lib/azure2/…svg`), with robust XML auto-fix (27-step), browser preview, and VLM
  validation. 33 shape libraries / ~4,281 stencils, documented only as markdown
  (`docs/shape-libraries/*.md`) — **no machine-readable index exists yet**.

**The quality gap (why output looks "good but not production"):** the backend exports `.drawio`
via [gv_to_drawio.py](backend/src/diagram_mcp/gv_to_drawio.py) and
[prettygraph.dot_to_drawio](backend/src/diagram_mcp/prettygraph.py#L535), which place every node as
`shape=image;image=data:image/png,<base64>` — **fuzzy raster PNGs in a rigid Graphviz layout**.
next-ai gets **crisp, natively-editable vector stencils** but guesses stencil names (fragile) and
has no blueprint/critic.

**Decision (confirmed with user):** keep the **backend as the brain**, upgrade its draw.io output
to **native vector stencils**, and turn next-ai into a **headless render+validate service** the
agent calls. Full combine, phased so each stage ships value independently.

This directly answers the three questions:
1. **How to combine** — backend orchestration stays; we bridge next-ai's stencil catalog into the
   backend icon resolver and emit native stencils on export. (Components 1–3.)
2. **Should we customize next-ai's MCP** — yes, but as a stateless headless **render/validate
   microservice** (HTTP), not a competing brain. (Component 4.)
3. **Improve the baseline (search/fetch icon + more)** — `resolve_icons`/`search_icons` gain a
   native-stencil tier and verified styles; emitter goes vector; critic reviews the *true* draw.io
   render. (Components 1–5.)

---

## Component 1 — Stencil catalog (the bridge data)

**New:** `backend/scripts/build_stencil_catalog.py` → writes `resources/stencils_catalog.json`.

Parse each `next-ai-draw-io/docs/shape-libraries/*.md`:
- The `## Usage` fenced block → the exact **style template** (varies per library type:
  `resourceIcon`+`resIcon` for aws4, plain `shape=` for gcp2, `image=…svg` for azure2,
  `prIcon` for kubernetes).
- The `## Shapes` list → valid shape names (azure2 also carries `### {category}`).

Output shape (one entry per library, grouped under a normalized provider key):
```json
{
  "aws":   {"library":"aws4","kind":"resIcon","style":"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{shape};fillColor=#ED7100;strokeColor=#fff;verticalLabelPosition=bottom;verticalAlign=top;align=center;","shapes":["ec2","s3",...]},
  "gcp":   {"library":"gcp2","kind":"shape","style":"shape=mxgraph.gcp2.{shape};fillColor=#4285F4;...","shapes":[...]},
  "azure": {"library":"azure2","kind":"image","style":"image;aspect=fixed;image=img/lib/azure2/{category}/{shape}.svg;...","shapes_by_cat":{...}},
  "k8s":   {"library":"kubernetes","kind":"prIcon","style":"shape=mxgraph.kubernetes.icon;prIcon={shape};fillColor=#326CE5;...","shapes":[...]}
}
```
Provider normalization map (`aws→aws4, azure→azure2, gcp→gcp2, k8s→kubernetes, alibabacloud→alibaba_cloud, …`).
Catalog is generated once and committed; regenerate when `docs/shape-libraries/` changes.

## Component 2 — Bridged icon resolution (baseline improvement)

**New:** `backend/src/diagram_mcp/stencils.py`
- Load `stencils_catalog.json` once (mirror the manifest-load pattern in
  [tools.py:_search_icon_hits](backend/src/diagram_mcp/tools.py#L77)).
- `resolve_stencil(provider, keyword) -> {style, library, shape} | None` — reuse the same tokenized
  all-terms match used for the raster pack, against catalog shape names; fill the style template.
- `search_stencils(query, provider) -> list[{shape, style}]` for the misses path.

**Modify** [tools.py:resolve_icons](backend/src/diagram_mcp/tools.py#L244) so each resolved entry
returns **both** tiers (so the PNG preview still works *and* the export can go vector):
- `drawio_style`: verified native stencil style (preferred for export), when the catalog matches.
- `path`/`icon`: raster pack hit (existing) — still used for the Graphviz PNG preview, and as the
  export fallback for brand logos.

Per-icon resolution order: **(1)** native stencil catalog → `drawio_style` (+ raster for preview);
**(2)** local raster pack (existing); **(3)** `fetch_logo` (Iconify/favicon). Write all of this into
`icon_plan.json` so revision runs reuse it. Add a `search_stencils` tool to `DRAWER_TOOLS`
([tools.py:503](backend/src/diagram_mcp/tools.py#L503)).

## Component 3 — Native-stencil drawio emitter

Thread node → `drawio_style` through the existing sidecar so export goes vector while Graphviz keeps
computing the layout:
- **Extend** `prettygraph._write_sidecar` ([prettygraph.py:405](backend/src/diagram_mcp/prettygraph.py#L405))
  per-node record (currently `{label, sublabel, kind, fill, stroke, icon}`) with a `drawio_style`
  field, resolved from the catalog via the node's provider/icon.
- **Modify** `dot_to_drawio` ([prettygraph.py:535](backend/src/diagram_mcp/prettygraph.py#L535))
  and `gv_to_drawio.convert` ([gv_to_drawio.py](backend/src/diagram_mcp/gv_to_drawio.py)): when a
  node has `drawio_style`, emit that native stencil cell; otherwise fall back to the current
  `shape=image;image=data:…` raster cell (brand logos). Keep Graphviz x/y + cluster boxes + edges.
- **Fix** the malformed data-URI in both emitters: `data:image/png,` → `data:image/png;base64,`
  ([gv_to_drawio.py:34](backend/src/diagram_mcp/gv_to_drawio.py#L34),
  [prettygraph.py:438](backend/src/diagram_mcp/prettygraph.py#L438)).

After this, an exported `.drawio` opened in draw.io shows crisp, recolorable AWS/Azure/GCP/K8s
stencils — the single biggest "production look" jump — with raster only for true gap logos.

## Component 4 — Custom headless next-ai MCP (render + validate service)

Customize `next-ai-draw-io/packages/mcp-server` into a **stateless render/validate microservice**
the Python backend calls over HTTP (next-ai already ships `electron/` + `playwright.config.ts`, so
headless rendering is in reach):
- Add an **HTTP endpoint/transport** alongside the existing stdio server.
- **Headless render** mxGraph XML → PNG via drawio-desktop CLI or Playwright (no user browser tab).
- New tools: `resolve_stencil(provider, keyword)` (reads the same `stencils_catalog.json`),
  `render_drawio_png(xml)`, `validate_drawio(xml)` (reuse `validateMxCellStructure`/`autoFixXml`
  from `lib/utils.ts`, + optional VLM with an added `icon_broken` category).
- **Backend critic** then inspects the **true draw.io render** (native stencils, real fonts) instead
  of the Graphviz PNG — closing the "what the user opens ≠ what the critic reviewed" gap. Wire via a
  thin HTTP client in the backend; `inspect_diagram`/critic prompt point at the headless PNG.

## Component 5 — Prompts, skills, evals

- **Drawer prompt** ([prompts.py](backend/src/diagram_mcp/prompts.py) `build_drawer_prompt`) +
  `skills/drawer/diagrams-as-code` & `pro-style`: "resolve_icons now returns `drawio_style` native
  stencils — prefer them; never hand-type stencil names; raster only for gap brand logos."
- **Critic** ([skills/critic/SKILL.md](backend/skills/critic/SKILL.md)): add `blank_icon` /
  raster-where-stencil-exists checks; review the headless drawio PNG.
- **Evals** ([backend/evals/diagram/judge.py](backend/evals/diagram/judge.py)): add
  `icon_native_ratio` (vector vs raster nodes) and a blank-icon count to the rubric.

---

## Phasing (each phase independently shippable)

1. **Phase 1 — Catalog + resolver bridge** (Components 1–2). Highest leverage, no rendering change
   yet: `resolve_icons`/`search_stencils` return verified native styles. Kills name-guessing.
2. **Phase 2 — Native emitter** (Component 3). Exported `.drawio` becomes vector. This is the visible
   "production" jump.
3. **Phase 3 — Headless next-ai MCP** (Component 4). Critic reviews the real draw.io render.
4. **Phase 4 — Prompts/skills/evals** (Component 5) + regression.

## Critical files

- New: `backend/scripts/build_stencil_catalog.py`, `resources/stencils_catalog.json`,
  `backend/src/diagram_mcp/stencils.py`.
- Modify: [tools.py](backend/src/diagram_mcp/tools.py) (`resolve_icons`, `search_icons`,
  `DRAWER_TOOLS`), [prettygraph.py](backend/src/diagram_mcp/prettygraph.py) (`_write_sidecar`,
  `dot_to_drawio`, `_b64_image`), [gv_to_drawio.py](backend/src/diagram_mcp/gv_to_drawio.py),
  [prompts.py](backend/src/diagram_mcp/prompts.py), `backend/skills/drawer/*`,
  `backend/skills/critic/SKILL.md`, [judge.py](backend/evals/diagram/judge.py).
- next-ai: `next-ai-draw-io/packages/mcp-server/src/` (HTTP transport, headless render, new tools).

## Verification

- **Catalog:** run the generator; assert provider count and total shapes (~4,281 across 33 libs);
  spot-check `aws.shapes` contains `ec2`, `azure.shapes_by_cat` has `compute/Virtual_Machine`.
- **Resolver unit tests:** `resolve_stencil("aws","ec2")` → aws4 resIcon style; `resolve_icons` over
  aws/azure/gcp/k8s nodes returns non-null `drawio_style`; a brand product (e.g. "Supabase") falls
  through to `fetch_logo` raster.
- **Emitter:** render an eval case (e.g.
  [case_04](backend/evals/diagram/dataset/case_04_document_understanding_slide.json)) →
  `export_drawio` → `grep` shows native `mxgraph.aws4`/`image=img/lib/azure2` cells and `data:image/png`
  only for gap logos. Open in draw.io: icons crisp and recolorable.
- **Headless MCP:** `render_drawio_png(xml)` returns a PNG with no browser tab; `validate_drawio`
  catches a deliberately broken stencil name.
- **Evals:** run `backend/evals/diagram/run_eval.py`; `icon_native_ratio` up, blank-icon count 0,
  structural F1 not regressed.
