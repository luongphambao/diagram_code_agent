# Backend architecture (`backend/src`)

This is the package map for the diagram/WBS agent backend, and the ordering
contracts that must not be broken when touching agent assembly. It reflects
the state after the Stage 0–9 structural refactor (see the refactor plan in
`.claude/plans/` for the full staged history) — a **structure-only** pass: no
runtime behavior changed, only where the code lives.

## Package map

```
src/
├── server.py                 entry point (console script `server:main`)
├── config/                   provider resolution + config.yaml loading
│   ├── settings.py           config.yaml load/reload, get_model, per-stage cost budgets
│   └── models.py             resolve_provider, make_llm, vision_in_tools, supports_structured_output
├── agent/                    agent assembly (formerly the agent.py monolith)
│   ├── __init__.py           re-exports build_agent, make_persistence; runs harness side effects
│   ├── builder.py            build_agent — compiles every SubagentSpec + the main agent
│   ├── persistence.py        make_persistence (checkpointer wiring)
│   ├── streaming.py          _StreamingSubAgentRunnable
│   ├── harness.py            _register_tuned_summarization_profiles, _set_general_purpose_enabled
│   ├── middleware/           __init__.py = _middleware() assembler (see ordering contract below)
│   │   ├── context_edits.py  KeepLatestImagesEdit, InjectVisionAsUserEdit, SanitizeToolTextBlocksEdit, OffloadGateArgsEdit
│   │   ├── phase_filter.py   PhaseToolFilterMiddleware, PhasePromptFilterMiddleware, _detect_phase
│   │   ├── drawer_gate.py    DrawerReviseGateMiddleware
│   │   ├── usage.py          UsageLoggingMiddleware
│   │   └── vision.py         VisionErrorFallbackMiddleware
│   └── subagents/            SubagentSpec dataclass + one file per role (wbs_planner, icon_resolver,
│                              drawer, critic, ppt_generator); __init__.py holds SUBAGENT_SPECS registry
├── runtime/                  process/filesystem plumbing
│   ├── safe_path.py, subprocess_utils.py
│   └── sandbox/              render_exec.py (subprocess render), guards.py (static pre-flight audit)
├── memory/                   persistence layout + stores
│   ├── layout.py, io.py      workspace roots, JSON read/write with traversal guards
│   └── stores/                csm.py, csm_adapter.py, csm_diff.py, decisions.py, evidence.py,
│                              finding_store.py, comments.py
├── tools/                    agent-callable tools
│   ├── __init__.py           tool-list aggregator (DIAGRAM_TOOLS, WBS_TOOLS, ...); export names unchanged
│   ├── schemas/               coercion.py, brief.py, tech_stack.py, blueprint.py (Pydantic models)
│   ├── analysis/               architecture.py, blueprint_tools.py, gates.py, reporting_gates.py,
│   │                          research.py, findings.py (tool functions, split out of the former
│   │                          tools/analysis_tools.py monolith)
│   └── rendering_tools.py, icon_tools.py, ...
├── session/                  session_state.py split (labels, sse, followups, normalize, gate_decisions, artifacts)
│   — `AGENT` singleton stays a module attribute of session_state.py itself (see invariant below)
├── domain/                   business logic grouped by subject area (cosmetic grouping, no shims left —
│   │                          every caller imports the canonical `domain.<group>.<module>` path)
│   ├── wbs/                   wbs_effort.py, wbs_excel.py, wbs_normalizer.py, wbs_schema.py, wbs_tools.py
│   ├── deck/                  deck.py, deck_resolver.py, deck_sections.py, deck_visual_qa.py
│   ├── reporting/              reporting.py, ppt_reporting.py, quality_dashboard.py, delivery_export.py,
│   │                          proposal_package.py, adr_export.py, traceability.py, reality_sync.py
│   ├── validation/             solution_validator.py, validate_drawio.py
│   └── diagram/                drawio_catalog.py, gv_to_drawio.py, node_catalog.py, icons.py, aiicons.py,
│                              shapesearch.py, architecture_advisor.py, logo_fetch.py, findings.py
│                              (findings.py = the diagram critic's DiagramFinding schema — distinct from
│                              tools/analysis/findings.py, the HITL findings tool functions)
├── prompts/, routers/, integrations/, rag/, prettygraph/, compliance/, codevis/, document_parsers/, diagram_mcp/
│                              already-cohesive packages, left as-is
├── backends.py, session_state.py  kept at top level, NOT moved into runtime/ or session/ — see invariant below
└── context.py                 SessionContext (small, self-contained)
```

Misc top-level modules that don't belong to any of the five domain groups
stay flat: `calendar_tools.py`, `email_tools.py`, `jira_adapter.py`,
`rag_tools.py`, `requirements_reader.py`, `conversations.py`, `tool_coercion.py`.

## Invariants that must not break

These are the load-bearing constraints the refactor was careful to preserve.
Breaking any of them tends to fail silently (wrong behavior, not an import
error) — the guard tests below exist specifically to catch that.

1. **Middleware / edit ordering** — `agent/middleware/__init__.py::_middleware()`
   is the single assembly point; no middleware self-registers. Order:
   ```
   ContextEditing -> UsageLogging -> ModelCallLimit -> ToolArgCoercion
     (must precede DrawerReviseGate — gate decisions assume well-formed task args)
     -> VisionErrorFallback -> ToolCallLimit(task) -> DrawerReviseGate
     -> PhaseToolFilter + PhasePromptFilter -> LLMToolSelector -> [ModelFallback]
   ```
   Edit order inside `ContextEditingMiddleware`: `KeepLatestImagesEdit` **before**
   `InjectVisionAsUserEdit` (the latter scans for images the former has already
   trimmed to one), then `SanitizeToolTextBlocksEdit`, `OffloadGateArgsEdit`,
   `ClearToolUsesEdit`.
   `exit_behavior`: `ModelCallLimitMiddleware="end"`, task `ToolCallLimitMiddleware="continue"`
   (`"end"` raises `NotImplementedError` with pending parallel tool calls).
   Guard: `tests/test_middleware_order.py`.

2. **Workspace contextvar** — `_current_workspace` is defined exactly once, in
   `backends.py`. Every consumer imports that same object; there is no second
   copy anywhere (a duplicate would silently leak workspace state across
   threads). Guard: `tests/test_workspace_isolation.py`.

3. **`AGENT` singleton** — lives as a real module attribute of `session_state.py`
   (`server.py` does `session_state.AGENT = build_agent(...)`). Readers import
   the module and read `session_state.AGENT`, never `from session_state import
   AGENT` (that copies the reference at import time, before `server.py` has set
   it). `backends.py` and `session_state.py` were deliberately **not** moved
   into `runtime/`/`session/` for this reason — the canonical module and the
   attribute assignment must stay the same object across the whole process.
   Guard: `tests/test_collaboration.py` + a live SSE round-trip.

4. **Import-time side effects** — `_register_tuned_summarization_profiles()`
   and `_set_general_purpose_enabled(False)` (both in `agent/harness.py`) must
   run exactly once, before `build_agent` reads the subagent registry.
   `agent/__init__.py` triggers this on import. Guard:
   `tests/test_general_purpose_disabled.py`.

5. **Prompt-caching-safe phase filtering** — `PhasePromptFilterMiddleware`
   must not change the *prefix* of the system prompt across phases, only strip
   trailing phase-specific spans, or provider-side prompt caching silently
   stops matching. Guard: `tests/test_phase_prompt_filter.py`.

6. **mimo coercion** — `ToolArgCoercionMiddleware` (`tool_coercion.py`) and the
   `before`-validators in `tools/schemas/coercion.py` must stay attached to
   every model that accepts stringified list/dict args from the mimo provider.
   Guard: `tests/test_mimo_coercion.py`, `tests/test_tool_arg_coercion.py`.

7. **Sandbox path re-rooting** — `runtime/sandbox/guards.py` (static
   pre-flight audit) and `render_exec.py` (subprocess exec) must keep
   `virtual_mode`'s write-allowlist and reject `..` traversal exactly as
   before the split from `tools/rendering_tools.py`. Guard: `tests/test_sandbox.py`.

8. **`Path(__file__).resolve().parents[N]` offsets** — several modules resolve
   `backend/` or the repo root relative to their own file depth (config.yaml,
   the drawio catalog, node_catalog.json, the BnK pptx template, the HTML
   report's logo asset). Any future move of these files must recompute `N`;
   grep for `parents\[` before moving a file and re-derive the offset instead
   of assuming it's unchanged.

## Verification checklist (run after any structural change here)

- `python -c "import server"` — the whole import graph resolves.
- `python -c "from agent import build_agent, make_persistence"` — agent
  assembly works.
- `pytest backend/tests` — 344 tests, 1 skipped, all green.
- `uvicorn server:app` boots to `Agent ready.` + `GET /health` returns OK
  (on Linux/Docker — native Windows uvicorn currently fails to start
  independently of this codebase, due to a psycopg/`ProactorEventLoop`
  incompatibility; use `python -c "import server"` + the agent-build check
  above as the local-Windows substitute).
