# Evals & regression gate

Quality system for the pipeline (docx §4.5). Each suite loads golden cases, scores
with a judge, writes `results.json`, and compares aggregated metrics to a committed
`baseline.json`. The gate enforces the product-plan rule: **no prompt/model change
ships without an eval artifact**.

## Suites

| Suite | Layer | Needs API key? | What it scores |
|-------|-------|----------------|----------------|
| `evals/intake` | L1 | no | fact/assumption/constraint classification + missing-question recall (via `csm_adapter`) |
| `evals/architecture` | L2 | no | cross-artifact validator findings fire on seeded defects (via `solution_validator`) |
| `evals/wbs` | L1/L2 | no | task coverage, dependency validity, critical path, rollup arithmetic (via `wbs_effort`) |
| `evals/deck` | L1/L2 | no | deck storyboard traceability / coverage / consistency / evidence findings fire on seeded defects (via `deck.validate_deck`) |
| `evals/diagram_quality` | L2 | no | diagram linter findings fire on seeded drawio defects: dangling edges, duplicate ids, node overlap, broken parents, style advice — repair contract integrity (via `validate_drawio`) |
| `evals/diagram` | L1+L3 | yes (LLM/vision) | structural F1 + vision rubric — **opt-in**, not in the CI gate |
| `evals/deck` vision | L3 | yes (LLM/vision) | `deck_vision_judge` slide rubric (readability/hierarchy/brand/coherence) — **opt-in**, not in the CI gate |
| `evals/e2e` | full pipeline | yes (LLM + Composio) | drives the real agent end-to-end (diagram → PDF → WBS → PPT → email → Google Calendar/Meet), asserting each deliverable file/tool actually succeeded — **opt-in, live side effects, not in the CI gate** (see below) |

Shared helpers live in `evals/_core.py` (case loading, concurrency, table print,
`compare_to_baseline`). The deterministic matcher (`soft_match`/`f1`) is re-exported
from `evals/diagram/judge.py` so every suite agrees on what "covered" means.

## Run

```bash
cd backend
uv run python -m evals.run_all            # all deterministic suites + report
uv run python -m evals.run_all --gate     # exit non-zero on ANY regression  (CI)
uv run python -m evals.run_all --update-baseline   # accept current as new baseline

# one suite at a time
uv run python -m evals.intake.run_eval --gate
uv run python -m evals.architecture.run_eval
uv run python -m evals.wbs.run_eval
uv run python -m evals.deck.run_eval
uv run python -m evals.diagram_quality.run_eval

# diagram suite (needs OPENAI/vision key) — opt-in, not in the gate
uv run python -m evals.diagram.run_eval

# full-pipeline E2E smoke test (needs OPENAI + Composio keys) — opt-in, not in the gate, LIVE side effects
uv run python -m evals.e2e.run_full_flow
```

A metric regresses when its mean drops below `baseline - tolerance` (default 0.02).
After an intentional quality change, re-run with `--update-baseline` and commit the
updated `baseline.json` in the same change as the prompt/model edit.

## Full-pipeline E2E smoke test (`evals/e2e`)

Unlike the suites above (deterministic golden-case scoring), `evals/e2e/run_full_flow.py`
drives the **real** agent through a real conversation — reading
`example_doc/tom_tat_FMCG_Finance_Automation_Storybook.md` as the input requirements
doc, auto-approving every HITL gate — and asserts each deliverable actually landed:

- `out.png`, `out.pdf`, `wbs_filled.xlsx`, `out.pptx` exist and are well-formed.
- `send_email` / `create_client_meeting` return a success string (not `ERROR:`).
- The 4 read-only Google Meet tools (`list_meeting_records`, `get_meeting_transcript`,
  `get_meeting_recordings`, `list_meeting_participants`) execute successfully (called
  directly, not via the LLM — a freshly created meeting has no conference record yet,
  which is expected and still counts as a pass).

Exit code 0 = every stage passed; use it as a manual CI/CD gate before a release.

**This test has real side effects every time it runs**: it sends a real email and
creates a real Google Calendar event/Meet (recipient defaults to
`bao.luong@bnksolution.com`, override with `--recipient` or `E2E_RECIPIENT_EMAIL`).
It also calls a real LLM (OpenAI, per `config.yaml`), taking a few minutes and
incurring cost. For these reasons it is **intentionally not wired into
`evals/run_all.py` or `.github/workflows/evals.yml`** — run it explicitly when you
want end-to-end confidence, not on every push/PR.
