"""Canonical Solution Model (CSM) — the central, ID'd domain model (docx §6, §13.1).

Today each pipeline stage writes a separate JSON file (`diagram_brief.json`,
`blueprint.json`, `wbs.json`, ...) and the validator/traceability sidecars treat
those files as the source of truth. That works, but the artifacts are an *implicit*
contract: a requirement, a component and a WBS task are linked only by fuzzy
soft-match, and nothing carries a stable identity across a change request.

The CSM makes that contract explicit. It is a pure Pydantic model — NO I/O — with:

  * **stable IDs** (`REQ-1`, `COMP-api_gw`, `WBS-1.1`, ...) that do NOT depend on a
    label, so renaming a node never breaks a trace link;
  * **provenance** on every entity (`human` | `deterministic` | `agent`) plus
    `source_refs` so a derived field can answer "where did this come from?";
  * a monotonic **revision** + a content **sha256** so two artifacts can be diffed
    by entity for change-impact.

This module owns ONLY the schema and small helpers. `csm_adapter.py` builds a
`SolutionModel` from the existing artifact files (a projection), so the generation
pipeline does not have to change to start producing a CSM.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, Field

# --- shared vocab ------------------------------------------------------------

Provenance = Literal["human", "deterministic", "agent"]

# Typed relationship edges (docx §6.2). Kept as a Literal so a bad relation fails
# validation rather than silently producing an untyped edge.
Relation = Literal[
    "satisfies",  # REQ -> COMP / WBS
    "constrains",  # CON -> DEC / COMP / WBS
    "assumes",  # ASM -> ESTIMATE / DEC
    "supports",  # EVD -> DEC / CLAIM
    "implements",  # WBS -> COMP / CTRL / REQ
    "mitigates",  # CTRL / WBS -> RISK
    "visualizes",  # DIAGRAM / SLIDE -> COMP / FLOW / DEC
    "claims",  # SLIDE / REPORT -> DEC / EVD / REQ
    "supersedes",  # revision N+1 -> revision N
    "accepts",  # HUMAN_DECISION -> RISK / DEC / ASM
]

# Stable ID prefixes, one per entity kind.
ID_PREFIX = {
    "requirement": "REQ",
    "constraint": "CON",
    "assumption": "ASM",
    "decision": "DEC",
    "component": "COMP",
    "cluster": "CLUSTER",
    "risk": "RISK",
    "work_item": "WBS",
    "evidence": "EVD",
    "deliverable": "ART",
    "slide": "SLIDE",
    "control": "CTRL",
}


def slug(value: str) -> str:
    """Lowercase, ascii-ish slug for building label-independent IDs from a key."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (value or "").strip().lower()).strip("_")
    return s or "x"


def mint_id(kind: str, key: str | int) -> str:
    """`mint_id("component", "api_gw")` -> "COMP-api_gw"; `mint_id("requirement", 3)` -> "REQ-3"."""
    prefix = ID_PREFIX.get(kind, kind.upper())
    if isinstance(key, int):
        return f"{prefix}-{key}"
    return f"{prefix}-{slug(str(key))}"


# --- entities ----------------------------------------------------------------


class SourceRef(BaseModel):
    """Where a fact/entity came from — a document span, the user, or a derivation."""

    kind: Literal["document", "user", "derived", "web"] = "derived"
    ref: str = ""  # filename, url, or short locator
    quote: str = ""  # optional verbatim span the entity is grounded in


class _Entity(BaseModel):
    """Common fields every CSM entity carries."""

    id: str
    provenance: Provenance = "deterministic"
    source_refs: list[SourceRef] = Field(default_factory=list)


class Requirement(_Entity):
    kind: Literal["business", "functional", "nfr", "compliance"] = "functional"
    statement: str
    status: Literal["confirmed", "pending", "deferred"] = "pending"
    priority: Literal["must", "should", "could"] = "should"


class Constraint(_Entity):
    statement: str
    kind: Literal["budget", "cloud", "region", "deadline", "compliance", "other"] = "other"


class Assumption(_Entity):
    statement: str
    owner: str = ""
    status: Literal["pending", "confirmed", "rejected"] = "pending"
    confidence_tier: Literal["must_confirm", "should_confirm", "nice_to_confirm"] = "should_confirm"


class DecisionOption(BaseModel):
    id: str
    title: str
    trade_offs: str = ""


class Decision(_Entity):
    title: str
    options: list[DecisionOption] = Field(default_factory=list)
    selected_option_id: Optional[str] = None
    rationale: str = ""
    assumption_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    risk_ids: list[str] = Field(default_factory=list)
    status: Literal["proposed", "approved", "deferred"] = "proposed"
    approver: Optional[str] = None


class Component(_Entity):
    """An architecture entity: a component, a cluster, an integration or a data flow."""

    name: str
    kind: Literal["component", "cluster", "integration", "data_flow"] = "component"
    cluster: str = ""  # parent cluster id, if any
    purpose: str = ""


class Risk(_Entity):
    statement: str
    probability: Literal["low", "medium", "high", ""] = ""
    impact: Literal["low", "medium", "high", ""] = ""
    mitigation: str = ""
    owner: str = ""


class WorkItem(_Entity):
    name: str
    effort_mandays: float = 0.0
    parent: str = ""  # parent WBS id, for the phase/module tree
    predecessors: list[str] = Field(default_factory=list)  # ref_code(s) that must finish first
    pert_expected_md: float = 0.0  # 3-point scheduling duration; 0 when no PERT estimate
    owner: Optional[str] = None
    definition_of_done: list[str] = Field(default_factory=list)
    assigned_sprint: Optional[int] = None


class Evidence(_Entity):
    """A grounded claim with its source (docx §4.9).

    Web research returns answers + URLs that today live only in chat history. An
    Evidence record makes a recommendation auditable: *which* claim rests on *which*
    source, fetched *when*, how fresh, and *which* CSM entities it supports — so a
    proposal can show the "why" behind a version/pricing/compliance statement.

    `supports_entity_ids` are projected into `supports` trace links by
    `evidence.project_into_csm`; `supersedes_evidence_id` chains a refreshed record
    to the one it replaces without deleting the old (the log is append-only).
    """

    claim: str
    source_url: str = ""
    source_type: Literal["web", "documentation", "vendor", "benchmark", "standard", "other"] = "web"
    fetched_at: str = ""  # ISO 8601; injected by the recording tool
    freshness_date: str = ""  # the date the source itself reflects, if known
    quote_or_excerpt: str = ""
    confidence: Literal["low", "medium", "high"] = "medium"
    supports_entity_ids: list[str] = Field(default_factory=list)
    supersedes_evidence_id: Optional[str] = None


class Control(_Entity):
    """A security/compliance control mapped to a standard (docx §4.4, §13.2, §4 P2).

    A compliance pack declares the controls a given standard requires (encryption,
    audit logging, access review, ...). `apply_pack` mints these as Control entities;
    `mitigates` trace links connect a control to the RISK it addresses and `implements`
    links connect the WBS work that delivers it. A control with no `evidence_ids` and
    no implementing work is an *evidence gap* the validator flags before a client claim
    like "SOC 2 ready" can ship.
    """

    statement: str
    kind: Literal[
        "encryption",
        "authentication",
        "authorization",
        "audit_logging",
        "data_retention",
        "backup_dr",
        "monitoring",
        "access_review",
        "other",
    ] = "other"
    standard_ref: str = ""  # e.g. "SOC2-CC6.1", "PCI-3.4"; pack-defined locator
    status: Literal["required", "implemented", "waived"] = "required"
    implemented_by_ids: list[str] = Field(default_factory=list)  # COMP/WBS ids
    evidence_ids: list[str] = Field(default_factory=list)


class Deliverable(_Entity):
    """A rendered output artifact (a deck, a report, or one slide) projected from the
    CSM (docx §6.1: `deliverables[] -> ART-### / SLIDE-###`, §6.3 artifact manifest).

    A deck/slide is NOT a source of truth — it is a *view*. `source_entity_ids` are
    the CSM entities the artifact claims/visualizes; `deck.project_into_csm` turns
    them into `visualizes`/`claims` trace links so a slide can never claim a component
    that does not exist (docx §4.4). `quality_checks` carries the deck QA scores
    (factual/visual/coherence) for the artifact manifest.
    """

    kind: Literal["pptx", "pdf", "slide", "report"] = "slide"
    title: str = ""
    solution_revision: int = 0
    source_entity_ids: list[str] = Field(default_factory=list)
    quality_checks: dict[str, Any] = Field(default_factory=dict)


class TraceLink(BaseModel):
    from_id: str
    to_id: str
    relation: Relation
    confidence: Optional[float] = None
    provenance: Provenance = "deterministic"


# --- the model ---------------------------------------------------------------


class SolutionModel(BaseModel):
    """The canonical, ID'd solution. Artifacts are projections of / traced to this."""

    revision: int = 1
    created_at: Optional[str] = None  # injected; excluded from the content hash

    requirements: list[Requirement] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    work_items: list[WorkItem] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    controls: list[Control] = Field(default_factory=list)
    deliverables: list[Deliverable] = Field(default_factory=list)
    trace_links: list[TraceLink] = Field(default_factory=list)

    # -- access helpers --
    def all_entities(self) -> Iterable[_Entity]:
        yield from self.requirements
        yield from self.constraints
        yield from self.assumptions
        yield from self.decisions
        yield from self.components
        yield from self.risks
        yield from self.work_items
        yield from self.evidence
        yield from self.controls
        yield from self.deliverables

    def by_id(self, entity_id: str) -> Optional[_Entity]:
        for e in self.all_entities():
            if e.id == entity_id:
                return e
        return None

    def ids(self) -> set[str]:
        return {e.id for e in self.all_entities()}

    # -- content hash / revision --
    def content_hash(self) -> str:
        """sha256 over the entity content, EXCLUDING volatile fields (created_at,
        revision). Two runs over the same artifacts produce the same hash, so a
        change-impact diff can tell "same content" from "real change"."""
        payload = self.model_dump(exclude={"created_at", "revision"})
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        data = self.model_dump()
        data["sha256"] = self.content_hash()
        return json.dumps(data, indent=2, ensure_ascii=False)

    # -- epistemic split (docx §4.2): show what is known vs. needs a human --
    def epistemic_summary(self) -> dict[str, list[dict]]:
        """Group entities into the intake buckets the UI/HITL surfaces up front:
        known facts (confirmed requirements), assumptions needing confirmation,
        open decisions, and hard constraints. A v0 derived purely from entity status
        — the deeper fact/assumption classifier at intake builds on this shape."""
        pending_asms = [a for a in self.assumptions if a.status == "pending"]
        return {
            "known_facts": [
                {"id": r.id, "statement": r.statement} for r in self.requirements if r.status == "confirmed"
            ],
            "assumptions_needing_confirmation": [
                {"id": a.id, "statement": a.statement, "owner": a.owner, "tier": a.confidence_tier}
                for a in pending_asms
            ],
            "assumptions_by_tier": {
                "must_confirm": sum(1 for a in pending_asms if a.confidence_tier == "must_confirm"),
                "should_confirm": sum(1 for a in pending_asms if a.confidence_tier == "should_confirm"),
                "nice_to_confirm": sum(1 for a in pending_asms if a.confidence_tier == "nice_to_confirm"),
            },
            "open_decisions": [
                {"id": d.id, "title": d.title} for d in self.decisions if d.status in ("proposed", "deferred")
            ],
            "constraints": [{"id": c.id, "statement": c.statement, "kind": c.kind} for c in self.constraints],
            "grounded_claims": [
                {"id": e.id, "claim": e.claim, "source_url": e.source_url, "confidence": e.confidence}
                for e in self.evidence
            ],
            "controls": [
                {
                    "id": c.id,
                    "statement": c.statement,
                    "kind": c.kind,
                    "standard_ref": c.standard_ref,
                    "status": c.status,
                    "grounded": bool(c.evidence_ids),
                }
                for c in self.controls
            ],
            "deliverables": [
                {"id": d.id, "kind": d.kind, "title": d.title, "quality_checks": d.quality_checks}
                for d in self.deliverables
            ],
        }
