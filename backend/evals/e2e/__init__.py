"""Live, opt-in end-to-end smoke test for the full deliverable pipeline.

Not part of ``evals.run_all`` — this drives the real LLM agent and the real
Composio integrations (sends an actual email, creates an actual Google
Calendar event/Meet). Run explicitly:

    uv run python -m evals.e2e.run_full_flow
"""
