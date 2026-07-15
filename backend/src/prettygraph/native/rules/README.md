# Diagram design rules (codified knowledge base)

Ported verbatim from `drawio-ai-kit/rules/`. These are the canonical design rules
for draw.io architecture diagrams. Two kinds:

## Machine-enforced (checked by `validate_drawio.py` on `aws_native` output)

| Rule | Source | Enforced by |
| --- | --- | --- |
| Icon color = identity (never recolor) | `aws-architecture.md` §"Icon color" | `audit_aws_conventions` — recolor check |
| Container nesting order (Cloud→Region→VPC→AZ→Subnet→SG) | `aws-architecture.md` §"Containers" | `audit_aws_conventions` — nesting check |
| Square corners on frames | `aws-architecture.md` §"Edges"/`principles.md` | `audit_aws_conventions` — rounded-frame check |
| **Managed/global services outside the VPC** | `aws-architecture.md` §"Containers" | `audit_aws_conventions` — managed-outside-VPC check (NEW — beyond the kit) |
| No edge cutting through an unrelated node | `principles.md` | `audit_edges` — edge-through-node + native router (`_cross`) |
| No floating arrowhead to an invisible leaf | `principles.md` | `audit_edges` — floating-arrowhead check |
| Font/palette/fan-out/icon-size budget | `principles.md`/`style-guide.md` | `audit_aesthetics` |
| Long-detour connectors / edge crossings | `aws-architecture.md` §"Placement" | `audit_edges` |

## Reference-only (guidance for the drawer/critic; not machine-checked)

`principles.md` (grid/flow/altitude), `style-guide.md` (theme tokens), `diagram-types.md`
(per-topology presets), and the per-domain presets (`azure-`, `gcp-`, `databricks-`,
`bpmn-architecture.md`). The native layout engine (`prettygraph/native/`) already bakes
most layout rules into geometry (nesting order, container hug, edge routing), so these
docs mainly guide the LLM when it authors a `render_spec`.
