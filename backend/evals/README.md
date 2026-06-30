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
| `evals/diagram` | L1+L3 | yes (LLM/vision) | structural F1 + vision rubric — **opt-in**, not in the CI gate |
| `evals/deck` vision | L3 | yes (LLM/vision) | `deck_vision_judge` slide rubric (readability/hierarchy/brand/coherence) — **opt-in**, not in the CI gate |

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

# diagram suite (needs OPENAI/vision key) — opt-in, not in the gate
uv run python -m evals.diagram.run_eval
```

A metric regresses when its mean drops below `baseline - tolerance` (default 0.02).
After an intentional quality change, re-run with `--update-baseline` and commit the
updated `baseline.json` in the same change as the prompt/model edit.
