---
name: drawio-xml
description: >
  How to generate production-quality draw.io mxGraphModel XML directly —
  mxCell structure, stencil style strings (from resolve_drawio_stencil),
  logo embedding (from embed_logo), manual grid layout, and edge styles.
  Read this BEFORE writing any XML for render_xml_preview or save_drawio.
---

# drawio-xml skill

Generate mxGraphModel XML that draw.io renders natively. No Python code,
no Graphviz — you write XML, call `render_xml_preview` to see it, refine,
then call `save_drawio` once.

---

## Document skeleton

```xml
<mxGraphModel dx="1422" dy="794" grid="1" gridSize="10" guides="1"
              pageWidth="1654" pageHeight="1169">
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
    <!-- all containers, nodes, edges go here -->
  </root>
</mxGraphModel>
```

- `id="0"` and `id="1"` are mandatory internal roots — always include them.
- `pageWidth="1654" pageHeight="1169"` → A4 landscape (default, use for most diagrams).
- Use `pageWidth="1100" pageHeight="850"` for US-letter landscape.
- All other cells have `parent="1"` (or `parent="<container-id>"` for nested nodes).

---

## Containers (clusters / tiers)

Use a **swimlane** cell for each logical tier or group:

```xml
<mxCell id="tier_compute" value="Compute"
        style="swimlane;rounded=1;arcSize=4;
               fillColor=#EAF3FF;strokeColor=#0078D4;
               startSize=28;fontStyle=1;fontSize=12;"
        vertex="1" parent="1">
  <mxGeometry x="320" y="80" width="380" height="220" as="geometry"/>
</mxCell>
```

- `startSize=28` reserves space for the header bar.
- Nodes inside the container set `parent="tier_compute"` and use coordinates
  **relative** to the container's top-left corner.
- Minimum useful container height = 40 (top padding) + N × 80 + 20 (bottom padding).

---

## Stencil nodes — use `resolve_drawio_stencil`

**NEVER guess a stencil style string.** Always call the tool first.

```
resolve_drawio_stencil("aws", "ecs") →
  shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.ecs;labelBackgroundColor=#ffffff;sketch=0;
```

Then use that string verbatim in the `style` attribute, adding font formatting:

```xml
<mxCell id="ecs" value="ECS Fargate"
        style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.ecs;
               labelBackgroundColor=#ffffff;sketch=0;
               fontStyle=1;fontSize=11;verticalLabelPosition=bottom;verticalAlign=top;"
        vertex="1" parent="tier_compute">
  <mxGeometry x="40" y="60" width="60" height="60" as="geometry"/>
</mxCell>
```

Standard icon sizes: **60 × 60** for AWS / Azure / GCP / k8s.

If `resolve_drawio_stencil` returns `NOT_FOUND`, try `search_drawio_stencils(query, provider)`.

---

## Logo-embedded nodes — use `embed_logo`

For services not in the stencil catalog:

```
embed_logo("Supabase") → data:image/png;base64,iVBORw0KGgo...
```

Use the full data URI as the `image=` value:

```xml
<mxCell id="supabase" value="Supabase"
        style="shape=image;
               image=data:image/png;base64,iVBORw0KGgo...;
               imageAlign=center;imageVerticalAlign=top;
               verticalLabelPosition=bottom;labelPosition=center;
               verticalAlign=top;whiteSpace=wrap;
               fillColor=none;strokeColor=#666666;
               fontStyle=1;fontSize=11;"
        vertex="1" parent="tier_data">
  <mxGeometry x="40" y="80" width="60" height="60" as="geometry"/>
</mxCell>
```

---

## Plain fallback (when both stencil and logo are NOT_FOUND)

```xml
<mxCell id="myservice" value="MyService"
        style="rounded=1;arcSize=10;
               fillColor=#ffffff;strokeColor=#0078D4;
               fontStyle=1;fontSize=11;"
        vertex="1" parent="tier_compute">
  <mxGeometry x="40" y="60" width="120" height="40" as="geometry"/>
</mxCell>
```

---

## Edges

```xml
<mxCell id="e_alb_ecs" value="HTTPS"
        style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;
               jettySize=auto;exitX=1;exitY=0.5;exitDx=0;exitDy=0;
               strokeColor=#2E5BBA;fontColor=#2E5BBA;fontSize=10;html=1;"
        edge="1" parent="1" source="alb" target="ecs">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
```

Edge style guide:

| use case | edgeStyle | strokeColor |
|---|---|---|
| Default request flow | `orthogonalEdgeStyle` | `#2E5BBA` |
| Data / read-write | `orthogonalEdgeStyle` | `#7A7A7A` |
| Async / event | `elbowEdgeStyle` | `#B85450` |
| Auth / security | `orthogonalEdgeStyle` + `dashed=1` | `#888888` |
| AI / LLM call | `orthogonalEdgeStyle` | `#2E8B57` |

Rules:
- One edge per (source, target) pair — never two arrows between the same nodes.
- Keep label ≤ 3 words; `fontSize=10`.
- `source=` and `target=` must match existing cell `id` values.

---

## Grid layout recipe (manual positioning — no Graphviz)

### Left-to-right pipeline (most common)

Page width = 1654. Place tier containers in columns:

| # tiers | container width | x positions |
|---|---|---|
| 2 | 500 | 80, 620 |
| 3 | 400 | 80, 520, 960 |
| 4 | 320 | 80, 440, 800, 1160 |
| 5 | 260 | 80, 380, 680, 980, 1280 |

All tiers at `y=60`. Container height = 40 + (node_count × 80) + 20.

Nodes within a container (relative coords):
- First node: `x=40, y=50`
- Each additional node below: `y += 80`
- For 2 columns of nodes inside a container: col1 x=20, col2 x=120, same row y

### Top-down stack

Page height = 1169. Stack tiers vertically, center nodes horizontally.

| # tiers | row height | y positions |
|---|---|---|
| 3 | 130 | 60, 230, 400 |
| 4 | 120 | 60, 220, 380, 540 |

---

## Complete minimal example (3-tier AWS)

```xml
<mxGraphModel dx="1422" dy="794" grid="1" gridSize="10"
              pageWidth="1654" pageHeight="1169">
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>

    <!-- Tier: Client -->
    <mxCell id="t_client" value="Client"
            style="swimlane;rounded=1;arcSize=4;fillColor=#F5F5F5;
                   strokeColor=#666666;startSize=28;fontStyle=1;"
            vertex="1" parent="1">
      <mxGeometry x="80" y="60" width="200" height="150" as="geometry"/>
    </mxCell>
    <mxCell id="browser" value="Browser"
            style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.management_console;
                   labelBackgroundColor=#ffffff;sketch=0;fontStyle=1;fontSize=11;
                   verticalLabelPosition=bottom;verticalAlign=top;"
            vertex="1" parent="t_client">
      <mxGeometry x="70" y="50" width="60" height="60" as="geometry"/>
    </mxCell>

    <!-- Tier: Edge -->
    <mxCell id="t_edge" value="Edge"
            style="swimlane;rounded=1;arcSize=4;fillColor=#EAF3FF;
                   strokeColor=#0078D4;startSize=28;fontStyle=1;"
            vertex="1" parent="1">
      <mxGeometry x="320" y="60" width="200" height="150" as="geometry"/>
    </mxCell>
    <mxCell id="alb" value="ALB"
            style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.application_load_balancer;
                   labelBackgroundColor=#ffffff;sketch=0;fontStyle=1;fontSize=11;
                   verticalLabelPosition=bottom;verticalAlign=top;"
            vertex="1" parent="t_edge">
      <mxGeometry x="70" y="50" width="60" height="60" as="geometry"/>
    </mxCell>

    <!-- Tier: Compute -->
    <mxCell id="t_compute" value="Compute"
            style="swimlane;rounded=1;arcSize=4;fillColor=#EAF3FF;
                   strokeColor=#0078D4;startSize=28;fontStyle=1;"
            vertex="1" parent="1">
      <mxGeometry x="560" y="60" width="200" height="150" as="geometry"/>
    </mxCell>
    <mxCell id="ecs" value="ECS Fargate"
            style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.ecs;
                   labelBackgroundColor=#ffffff;sketch=0;fontStyle=1;fontSize=11;
                   verticalLabelPosition=bottom;verticalAlign=top;"
            vertex="1" parent="t_compute">
      <mxGeometry x="70" y="50" width="60" height="60" as="geometry"/>
    </mxCell>

    <!-- Edges -->
    <mxCell id="e1" value="HTTPS"
            style="edgeStyle=orthogonalEdgeStyle;strokeColor=#2E5BBA;
                   fontColor=#2E5BBA;fontSize=10;html=1;"
            edge="1" parent="1" source="browser" target="alb">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="e2" value="route"
            style="edgeStyle=orthogonalEdgeStyle;strokeColor=#2E5BBA;
                   fontColor=#2E5BBA;fontSize=10;html=1;"
            edge="1" parent="1" source="alb" target="ecs">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
  </root>
</mxGraphModel>
```

---

## Hard rules

1. **Never guess a stencil style.** Always call `resolve_drawio_stencil` first. A wrong
   style renders as an empty box — same bug as a wrong Python import.
2. **If stencil = NOT_FOUND**, call `search_drawio_stencils` then `embed_logo`.
   If both fail, use the plain rounded-rectangle fallback.
3. **Calculate x/y explicitly** using the grid recipe. Do NOT leave nodes at 0,0.
4. **One edge per (source, target).** No duplicate arrows.
5. **Every vertex cell needs `vertex="1"`.** Every edge needs `edge="1"` + `source=` + `target=`.
6. **IDs must be unique** across the entire document.
7. Container geometry must be large enough to contain all child nodes (check the math).
