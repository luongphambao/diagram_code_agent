# Typed Diagram Foundation + MVP-3 — Production Implementation Plan

Companion to [`diagram_code_agent_extension_proposal.md`](./diagram_code_agent_extension_proposal.md).
Scope locked with the requester: **Foundation-first** (proposal Phase 1) then the **full
MVP-3** (Sequence → ERD → State Machine), piloting the framework on the **Sequence** renderer.

---

## Context

Today every diagram flows through one god object, [`Blueprint`](../backend/src/tools/schemas/blueprint.py#L145),
which already carries architecture + C4 + `layout_intent` + presentation metadata **and** an
optional `process: ProcessBlueprint` field that silently reroutes rendering to the native BPMN
builder. BPMN was bolted on exactly the way the proposal warns against. Adding Sequence, ERD and
State Machine the same way would make `Blueprint` unmaintainable.

Two facts from the codebase change how we should build this:

1. **A de-facto renderer registry already exists.** [`build_tree(spec)`](../backend/src/prettygraph/native/topology.py#L579)
   dispatches on spec fields (`spec["process"]`→BPMN, `layout_intent`→exotic/refined), and
   [`_render_native_from_spec`](../backend/src/tools/rendering_tools.py#L640) already does a
   **deterministic spec→native render**. So `render_spec.json` is *already* the canonical source
   for architecture; `diagram.py`/the drawer is a refinement layer. The new typed diagrams skip the
   drawer entirely: **pure spec → native renderer, no LLM-authored code.**
2. **BPMN is the proven template** for a new diagram family and every new type copies its shape:
   Pydantic schema → native creator module → a branch in `build_tree` → `check_semantic_preservation`
   + `audit_*` static lint → gate tool with `interrupt_on` → frontend card keyed on
   `pendingInterrupt.data.type`.

**Intended outcome:** a first-class `DiagramKind` discriminator, a `DiagramSpec` discriminated
union that ends the god-object growth, a renderer registry, and three new semantically-rich
diagram types — each deterministic, validated, and exported to editable draw.io — without breaking
the existing architecture/BPMN flows.

---

## Guiding production principles (apply to every phase)

- **Additive, backward-compatible.** `Blueprint` and `ProcessBlueprint` keep working unchanged.
  The union is introduced *alongside* them; `Blueprint` becomes one member (`kind="architecture"`),
  its embedded `process` becomes the `kind="bpmn"` member. No behavior change for existing runs —
  guard with golden-file tests (`test_native_engine.py`, `test_bpmn_native.py`, `test_diagram_types.py`).
- **Deterministic extraction, never LLM-guessed structure.** Following the repo's recent ethos
  (deterministic cost/ROI/tech-stack totals), ERD-from-DDL uses `sqlglot`; deployment/IaC uses
  PyYAML/HCL parsers. The LLM proposes *intent*; parsers produce *structure*.
- **`diagram_spec.json` is the canonical artifact** for the new types (not `diagram.py`). The
  renderer is a pure function `spec → (xml, png, stats)`.
- **Reuse the three validation tiers**, don't invent new ones:
  1. deterministic static audit — extend [`validate_drawio.py`](../backend/src/domain/validation/validate_drawio.py) with `audit_<kind>`;
  2. 0-token repair/scorecard loop — [`repair.py`](../backend/src/prettygraph/native/repair.py) + `production_scorecard`;
  3. LLM visual critic subagent — [`critic.py`](../backend/src/agent/subagents/critic.py).
  Structural lint (unreachable states, dangling FKs, orphan messages) plugs in at tier 1.
- **No new base classes in the layout engine.** It dispatches on `{"kind": ...}` dicts through the
  `_LAYOUT` table; a new node type implements the informal `(measure, place, emit)` triple.

---

## Target architecture

```
DiagramRequest
  → Diagram Type Router (kind on DiagramBrief; frontend override)
  → Type-specific analyzer/parser  → DiagramSpec (discriminated union)
  → HITL plan-approval gate (per-kind card)
  → Renderer Registry → { architecture | bpmn | sequence | erd | state_machine }
  → Structural validator (tier-1 audit_<kind>) → Visual critic (tier-3)
  → out.drawio + out.png + diagram_spec.json + engineer_report.json
```

---

## Phase 1 — Typed diagram foundation

Goal: introduce the discriminator, the union, the registry, the router and the per-kind lint
framework — proven immediately by the Sequence slice in Phase 2 (so the abstraction is validated by
a second concrete type, not built speculatively).

### 1.1 Schema: the discriminated union
Create `backend/src/tools/schemas/diagram_spec.py`:
- `DiagramKind = Literal["architecture", "bpmn", "sequence", "erd", "state_machine", "deployment", "code_map"]`
- `DiagramPlan(CoercingModel)`: `kind`, `title`, `objective`, `audience`, `source_type`,
  `presentation_style`, and `spec` (the union member). Mirrors proposal §8.
- `DiagramSpec = Annotated[Union[...], Field(discriminator="kind")]` — Pydantic v2 discriminated union.
- **Adapters, not rewrites:** `ArchitectureSpec` wraps the existing `Blueprint`; `ProcessSpec` wraps
  `ProcessBlueprint`. New members (`SequenceSpec`, `ERDSpec`, `StateMachineSpec`) land in their own
  phase. Keep every member a `CoercingModel` so the mimo-coercion path
  ([`coercion.py`](../backend/src/tools/schemas/coercion.py)) still applies.
- Re-export from [`tools/schemas/__init__.py`](../backend/src/tools/schemas/__init__.py).

### 1.2 Renderer registry
Create `backend/src/prettygraph/native/registry.py`:
- `RENDERERS: dict[str, Callable[[dict, ...], tuple[Diagram, dict]]]` keyed by `kind`.
- Refactor [`build_tree`](../backend/src/prettygraph/native/topology.py#L579) so its existing
  branches (`process`→bpmn, exotic, refined, default) register under keys `bpmn`/`architecture`.
  **This is a pure refactor** — same outputs, now table-driven. New renderers register a key.
- `_render_native_from_spec` reads `spec["kind"]` (default `"architecture"` when absent, for
  backward compat) and dispatches through the registry. The BPMN special-casing at
  [rendering_tools.py:649](../backend/src/tools/rendering_tools.py#L649) becomes one registry entry
  that declares its own post-steps (skip icon-bake / slide-wrap, run `check_semantic_preservation`).

### 1.3 Type router (lightweight — no StateGraph)
- Add `diagram_kind: DiagramKind = "architecture"` to [`DiagramBrief`](../backend/src/tools/schemas/brief.py).
  The main agent sets it in `propose_diagram_brief`; a deterministic keyword pre-classifier in
  `analyze_architecture_requirements` seeds a default (e.g. "sequence"/"login flow"→sequence,
  "CREATE TABLE"/"schema"→erd, "status"/"lifecycle"/"state"→state_machine).
- The **frontend override wins** (see 1.6). Persist `diagram_kind` to a `diagram_kind` marker file
  in the workspace so `_detect_phase` and the gate router can read it.
- Add per-kind phases/signals in [`phase_filter.py`](../backend/src/agent/middleware/phase_filter.py):
  extend `_PHASE_TOOLS` and `_detect_phase` so the new gate tools (`propose_sequence`,
  `propose_erd`, `propose_state_machine`) are surfaced and the right approval card is reachable.
  Crucially, gate the tech-stack/WAF machinery **off** for non-architecture kinds (proposal §9:
  ERD needs no tech stack, Sequence no WAF pillar).

### 1.4 Per-kind structural-lint framework
Create `backend/src/domain/validation/diagram_lint.py`:
- `LINTERS: dict[str, Callable[[dict], LintReport]]` with `Error | Warning | Info` severities
  (proposal §4 taxonomy). Each new type registers `lint_<kind>(spec)`.
- Wire into `_render_native_from_spec` after the render, writing findings into `engineer_report.json`
  (reuse the existing report file the repair loop already emits).

### 1.5 Gate plumbing (generic)
- Add the three new gate tool names to `GATE_TOOL_NAMES` and `GATE_DECISIONS`
  ([tools/__init__.py:328](../backend/src/tools/__init__.py#L328)) so `interrupt_on` pauses them for
  approval — same mechanism as `propose_blueprint`.

### 1.6 Frontend foundation
- **Diagram-type selector** in [`App.tsx`](../frontend/src/App.tsx) (`Auto detect ▼` default +
  explicit kinds), sent alongside `userRole` and consumed by the router in 1.3.
- Extend the gate `type` union in `frontend/src/hooks/agent-utils.ts` and the dispatch in
  `frontend/src/components/chat/MessageList.tsx` to route new `pendingInterrupt.data.type`s to new
  cards (added per phase). The unused `BriefApproval.tsx` type is the pattern to follow.

**Phase-1 exit test:** existing suites stay green (`cd backend && uv run pytest tests/ -q`); a
`kind="architecture"` request renders byte-identically to today (golden compare).

---

## Phase 2 — True Sequence Diagram (pilot that proves the foundation)

Native lifeline renderer — the hardest renderer, deliberately built first here to validate the
foundation against a genuinely new geometry.

### 2.1 Schema — `backend/src/tools/schemas/sequence.py`
`SequenceParticipant` (id, label, kind: actor|frontend|service|database|external),
`SequenceMessage` (order, from_, to, label, kind: sync|async|return|create|destroy),
`SequenceFragment` (kind: alt|opt|loop|par|critical, condition, start_order, end_order),
`SequenceActivation` (participant, start_order, end_order), `SequenceSpec` (participants, messages,
fragments, activations). All `CoercingModel`, `from`/`from_` alias like `BPEdge`.

### 2.2 Renderer — `backend/src/prettygraph/native/sequence.py`
Compose directly on a `Diagram` (the [`refined.py`](../backend/src/prettygraph/native/refined.py)
model — bypass `render_tree`, emit mxCells directly), because sequence geometry is coordinate-driven,
not flexbox:
1. Place participants left→right; compute a fixed x per lifeline.
2. Emit dashed vertical lifelines (`umlLifeline` draw.io shape) via `Diagram._put`.
3. Map each `message.order` to a y-coordinate (constant row pitch).
4. Draw activation bars as thin rects on lifelines; register in `d.R` so the router respects them.
5. Return messages dashed; sync solid-filled arrowhead; async open arrowhead.
6. Draw `alt`/`opt`/`loop`/`par` fragment frames spanning `[start_order, end_order]` with a label tab.
7. Register a `bpmn`-style entry in the registry; **skip** icon-bake/slide-wrap/band-planning.

### 2.3 Structural lint — `lint_sequence` (proposal §3 validation list)
Message → non-existent participant; duplicate `order`; empty fragment; malformed fragment nesting;
activation ends before it starts; return with no matching request; participant in no message;
too-many-participants width warning. Plus `check_semantic_preservation` on message ids.

### 2.4 Gate tool + flow
`propose_sequence(spec: SequenceSpec)` in a new `tools/analysis/sequence_tools.py`, mirroring
`propose_blueprint`: writes `diagram_spec.json` + a render_spec projection, runs the deterministic
native pre-render + lint, PAUSES for approval. Flow per proposal §9: `Requirement/OpenAPI →
participants+messages approval → render` (no tech-stack gate).

### 2.5 Frontend `SequenceApproval.tsx`
Card per proposal §10: participants / messages / fragments counts + main-flow summary line.

### 2.6 Tests — `tests/test_sequence_native.py`
Golden `.drawio`, lifeline/activation/fragment presence, semantic preservation, every lint rule.

### 2.7 (Fast-follow) API-flow preset
Once the engine is proven, `OpenAPI/source → endpoints → SequenceSpec` is a thin parser + reuse
(proposal §3) — no new renderer.

---

## Phase 3 — ERD / Database Schema

### 3.1 Schema — `backend/src/tools/schemas/erd.py`
`ERDColumn`, `ERDEntity`, `ERDRelationship` exactly as proposal §4.

### 3.2 Deterministic parsers (not LLM)
`backend/src/codevis/sql_schema.py` (PostgreSQL DDL first, via **`sqlglot`**) and
`backend/src/codevis/orm_schema.py` (SQLAlchemy/Django/Prisma). Add `sqlglot` to
[`backend/pyproject.toml`](../backend/pyproject.toml). Output `ERDSpec`. Expose as a
`visualize_database_schema` tool alongside [`visualize_code_structure`](../backend/src/tools/rendering_tools.py#L2039).

### 3.3 Renderer — `backend/src/prettygraph/native/erd.py`
Needs a **new layout-engine `kind` `erd_table`** (measure/place/emit + `_LAYOUT` registration in
[`layout_engine.py`](../backend/src/prettygraph/native/layout_engine.py)): header + one row per
column, PK/FK badges, FK **ports** anchored to the exact row, crow's-foot connectors. Dependency-aware
layout (proposal §4): build FK graph → root tables → layered placement → lookup tables to a side
column → junction tables centered; reuse [`layout_plan.py`](../backend/src/prettygraph/native/layout_plan.py)
band ordering + [`repair.py`](../backend/src/prettygraph/native/repair.py) for edge-crossing minimization.

### 3.4 Lint `lint_erd` + gate `propose_erd` + `ERDApproval.tsx`
FK to missing table/column, type mismatch, M:N without junction, PK-less table, duplicate index,
orphan/circular (Error/Warning/Info). Card: schemas/tables/relationships/warnings counts.

### 3.5 Tests — `tests/test_erd_native.py` (+ parser round-trip on the proposal §4 DDL sample).

---

## Phase 4 — State Machine

### 4.1 Schema — `backend/src/tools/schemas/state_machine.py`
`StateNode` (kind: initial|normal|final|choice|fork|history, group), `StateTransition`
(from_, to, event, guard, action, actor). Transition label format `event [guard] / action`.

### 4.2 Renderer — `backend/src/prettygraph/native/state_machine.py`
Reuses the most existing machinery (proposal §5). Semantic shapes: initial=filled circle,
final=bullseye, normal=rounded rect, choice=diamond, fork/join=thick bar, composite=nested container.
Layout largely reuses the exotic/hierarchy path; transitions are labeled edges through the existing
router.

### 4.3 Lint `lint_state_machine` (proposal §5 — the highest-value validation)
Unreachable-from-initial, cannot-reach-final, terminal-with-outgoing, duplicate event+guard, missing
actor/permission, exitless loop, status-in-requirement-but-not-in-diagram.

### 4.4 Transition-table export
Emit `transition_table.csv` from the spec (proposal §5 table) into the artifact panel — reuse the
`engineer_report.json` writer pattern; deterministic, no LLM.

### 4.5 Gate `propose_state_machine` + `StateApproval.tsx` (states/transitions/actors/unreachable counts)
+ `tests/test_state_machine_native.py`.

---

## Critical files

| Area | Create | Modify |
|---|---|---|
| Union/discriminator | `tools/schemas/diagram_spec.py` | `tools/schemas/__init__.py` |
| Registry/dispatch | `prettygraph/native/registry.py` | `prettygraph/native/topology.py`, `tools/rendering_tools.py` |
| Router/phases | — | `tools/schemas/brief.py`, `agent/middleware/phase_filter.py`, `routers/chat.py` |
| Lint framework | `domain/validation/diagram_lint.py` | `domain/validation/validate_drawio.py` |
| Gates | `tools/analysis/{sequence,erd,state_machine}_tools.py` | `tools/__init__.py` |
| Renderers | `prettygraph/native/{sequence,erd,state_machine}.py` | `prettygraph/native/layout_engine.py` (erd_table kind) |
| Parsers | `codevis/{sql_schema,orm_schema}.py` | `backend/pyproject.toml` (`sqlglot`) |
| Frontend | `components/chat/{Sequence,ERD,State}Approval.tsx` | `App.tsx`, `hooks/agent-utils.ts`, `components/chat/MessageList.tsx` |
| Tests | `tests/test_{sequence,erd,state_machine}_native.py` | — |

---

## Verification (end-to-end)

Per phase:
1. **Backend suite:** `cd backend && uv run pytest tests/ -q` — existing suites stay green
   (backward-compat gate), new `test_<kind>_native.py` passes.
2. **Deterministic render:** call the new `propose_<kind>` tool with a fixture spec; assert
   `out.drawio` contains the expected native shapes (`umlLifeline`, crow's-foot, `mxgraph` state
   stencils), `check_semantic_preservation` == 100%, and `engineer_report.json` lint is clean.
3. **Golden PNG:** render fixture → `out.png`; visual-diff against a committed golden.
4. **HITL loop:** run the app (`/run`), pick the type in the selector, confirm the per-kind approval
   card renders the right counts and approve/reject resumes correctly.
5. **Backward-compat golden:** a `kind="architecture"` request renders byte-identically to `main`.

---

## Sequencing summary

1. **Phase 1 foundation** (union + registry refactor + router + lint framework + FE selector) —
   pure refactor, no output change; locked by golden tests.
2. **Phase 2 Sequence** — proves the foundation on the hardest geometry.
3. **Phase 3 ERD** — deterministic parsers + new `erd_table` layout kind.
4. **Phase 4 State Machine** — reuses the graph engine; adds the transition-table export.

Each phase ships a complete vertical slice (schema → renderer → lint → gate → card → tests) and is
independently releasable behind the type selector.
