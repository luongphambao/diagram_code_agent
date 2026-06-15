# Plan: Improve Diagram Cluster Layout — Production Quality

## Context
Diagram renders (e.g. Project CLARA) show certain clusters stretched too wide horizontally — "Compute Platform" holding "Container Registry" + "Container Apps" spanning 3-4 columns because in `rankdir=LR`, Graphviz expands a cluster's bounding box to cover every rank its nodes occupy. The user wants the most professional, production-quality output.

**Root causes:**
1. `_cluster_block()` emits no `margin` attribute → Graphviz uses a large default that bloats the bounding box
2. No `ordering` attribute → nodes shuffle freely within ranks, creating irregular spacing
3. Prompt has no guidance about `same_rank` for sibling nodes *within* a cluster (only cross-cluster stacking is covered)
4. Audit catches aspect ratio but not per-cluster width

---

## Changes (highest impact first)

### 1. `prompts.py` — Add "prevent wide clusters" guidance
**Location:** `_PRETTY_DIAGRAM_DETAIL`, after the `≤5 cluster COLUMNS` bullet (~line 536)

Add this bullet inside `## Layout into CLEAR BLOCKS`:
```
- **Prevent wide clusters (rankdir=LR):** A cluster expands horizontally to
  cover every rank its nodes occupy. If a cluster holds 2 sibling nodes that
  live at different flow ranks, it spans the full horizontal distance between
  them. Fix: call `g.same_rank([node_a, node_b])` for any cluster whose nodes
  are parallel peers (no internal left-to-right dependency). This collapses the
  cluster to a single rank column.
  Example — Compute Platform with Container Registry + Container Apps:
      g.same_rank(["registry", "container_apps"])  # forces them into one column
  Apply to EVERY cluster whose nodes are siblings, not a pipeline.
```

Also add a recipe block just before `## Hard rules` (~line 576):
```
## Tight cluster recipe
For any cluster with ≤4 nodes that are parallel (not pipelined):
  g.same_rank([list of node ids in that cluster])
This prevents the cluster from stretching horizontally. Skip only if nodes in
the cluster have a real left-to-right dependency between them.
```

### 2. `prettygraph.py` — Add cluster margin, ordering, labelloc
**File:** `backend/src/diagram_mcp/prettygraph.py`

**2a. Add `cluster_padding` field to `Pretty` dataclass** (after line 183, after `grid_rows`):
```python
cluster_padding: str | None = None  # "h,v" pts; None = theme default ("8,5" pro)
```

**2b. Add `_cluster_margin()` helper** (after `_node_margin()` at line 304):
```python
def _cluster_margin(self) -> str:
    if self.cluster_padding is not None:
        return self.cluster_padding
    return "8,5" if self.theme == "pro" else "10,6"
```

**2c. Edit `_cluster_block()` at lines 370–376** — insert a new attributes line:

Current lines 370–377:
```python
lines = [
    f'{"  " * depth}subgraph cluster_{c.id} {{',
    f'{"  " * depth}  style="rounded,filled"; fillcolor="{fill}"; '
    f'color="{stroke}"; penwidth={"1.6" if pro else "1.2"};',
    f'{"  " * depth}  labeljust="l"; fontsize="{self._sizes()["cluster"] - 1}"; '
    f'fontname="{FONT}"; fontcolor="#5a6270";',
    f'{"  " * depth}  label=<{label_html}>;',
]
```

Change to:
```python
labelloc = "b" if depth > 1 else "t"
lines = [
    f'{"  " * depth}subgraph cluster_{c.id} {{',
    f'{"  " * depth}  style="rounded,filled"; fillcolor="{fill}"; '
    f'color="{stroke}"; penwidth={"1.6" if pro else "1.2"};',
    f'{"  " * depth}  labeljust="l"; fontsize="{self._sizes()["cluster"] - 1}"; '
    f'fontname="{FONT}"; fontcolor="#5a6270";',
    f'{"  " * depth}  margin="{self._cluster_margin()}"; ordering="out"; '
    f'labelloc="{labelloc}";'
    + (' nojustify="true";' if pro else ''),
    f'{"  " * depth}  label=<{label_html}>;',
]
```

**Why:**
- `margin="8,5"` tightens the cluster bounding box so it doesn't appear to "bleed" beyond its nodes
- `ordering="out"` ensures nodes within the same rank are ordered by their outgoing edges → consistent, predictable left-to-right ordering inside the cluster
- `labelloc="b"` for nested clusters (depth > 1) moves the label to the bottom to avoid overlapping with the parent cluster's top label
- `nojustify="true"` (pro theme only) prevents label text from stretching the cluster width

### 3. `tools.py` — Add audit heuristic for missing `same_rank`
**File:** `backend/src/diagram_mcp/tools.py`

**Location:** After line 452 (after the `poster_missing_same_rank` block), before the final `if not findings: return` at line 454.

Add:
```python
# Non-poster pretty diagrams: flag when clusters exist but no same_rank is used
# (likely causes wide clusters in rankdir=LR)
if is_slide and cluster_count >= 3 and "poster_grid(" not in code:
    has_any_same_rank = "same_rank(" in code
    if not has_any_same_rank:
        _audit_add(
            findings, "low", "no_same_rank_in_clusters",
            f"Script has {cluster_count} clusters but no same_rank() calls.",
            "In rankdir=LR, clusters with sibling nodes (parallel peers) stretch "
            "horizontally to cover all ranks their nodes occupy. Add "
            "g.same_rank([node_a, node_b]) for nodes in each cluster that are "
            "parallel (not a pipeline). This collapses the cluster to one rank column.",
        )
```

---

## Critical files
- `backend/src/diagram_mcp/prettygraph.py` — lines 183, 304, 365–387
- `backend/src/diagram_mcp/prompts.py` — lines 536, 576
- `backend/src/diagram_mcp/tools.py` — line 452–454

## Reuse existing patterns
- `_node_margin()` at line 299 — exact same pattern as the new `_cluster_margin()` helper
- `_audit_add()` helper already used throughout `audit_diagram_code()` — reuse for the new heuristic
- `same_rank()` method on `Pretty` already exists and works — prompt just needs to tell the LLM to use it within clusters

## Verification
1. Regenerate the CLARA diagram → "Compute Platform" cluster should be 1 column wide instead of spanning 3-4
2. Check `.dot` output: each `subgraph cluster_*` block should contain `margin="8,5"` and `ordering="out"`
3. Run `audit_diagram_code` on an old script with 3+ clusters and no `same_rank` → should return `no_same_rank_in_clusters` finding
4. Visual check: nested cluster labels should not overlap parent cluster labels
