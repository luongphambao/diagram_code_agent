"""Persistent memory: agent scratch/global-memory routing lives in
``runtime.backends`` (MEMORY_PATH/GLOBAL_MEMORY_PATH); this package holds the
domain knowledge stores — the Canonical Solution Model and its append-only
audit-trail logs (findings, evidence, decisions, comments).
"""

from __future__ import annotations
