"""Re-export shim — moved to ``memory/stores/evidence.py``."""

from __future__ import annotations

from memory.stores.evidence import (
    EVIDENCE_LOG_NAME,
    Confidence,
    EvidenceRecord,
    SourceType,
    append_evidence,
    new_evidence_record,
    next_seq,
    project_into_csm,
    read_evidence,
)
