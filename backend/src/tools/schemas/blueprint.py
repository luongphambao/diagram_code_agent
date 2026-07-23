"""Architecture blueprint schemas: nodes, clusters, edges, WAF pillar coverage."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .coercion import CoercingModel
from .process import ProcessBlueprint


class WAFPillar(CoercingModel):
    """Coverage of one AWS Well-Architected Framework pillar in the blueprint."""

    addressed_by: list[str] = Field(
        default_factory=list, description="node IDs or key_decision labels addressing this pillar"
    )
    gaps: list[str] = Field(
        default_factory=list, description="known gaps; declare explicitly rather than leaving empty"
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_shorthand(cls, values):
        if isinstance(values, (str, list)):
            return {"addressed_by": values}
        return values


class PillarCoverage(CoercingModel):
    """Well-Architected Framework 6-pillar coverage."""

    operational_excellence: WAFPillar = Field(default_factory=WAFPillar)
    security: WAFPillar = Field(default_factory=WAFPillar)
    reliability: WAFPillar = Field(default_factory=WAFPillar)
    performance_efficiency: WAFPillar = Field(default_factory=WAFPillar)
    cost_optimization: WAFPillar = Field(default_factory=WAFPillar)
    sustainability: WAFPillar = Field(default_factory=WAFPillar)

    @model_validator(mode="before")
    @classmethod
    def _coerce_shorthand(cls, values):
        return {} if isinstance(values, (str, list)) else values


class NFRMapping(CoercingModel):
    """Maps one non-functional requirement to the mechanism(s) and nodes that satisfy it."""

    nfr: str = Field(description="the NFR text, ideally measurable: e.g. '99.9% uptime SLA'")
    mechanism: str = Field(description="how this NFR is addressed: e.g. 'Multi-AZ RDS + ALB health checks'")
    node_ids: list[str] = Field(
        default_factory=list, description="blueprint node IDs implementing this mechanism"
    )


class BPNode(BaseModel):
    id: str = Field(description="unique snake_case id")
    label: str = Field(description="human-readable component name")
    tech: str = Field("", description="technology for this node")
    cluster: str = Field("", description="id of the cluster this node belongs to")
    type: str = Field("", description="service|database|queue|cache|gateway|external|lb|cdn")

    @model_validator(mode="before")
    @classmethod
    def _coerce_label_aliases(cls, values):
        if isinstance(values, dict) and not values.get("label"):
            for alias in ("title", "name"):
                if values.get(alias):
                    return {**values, "label": values[alias]}
        return values


class BPCluster(BaseModel):
    id: str = Field(description="unique snake_case id")
    label: str = Field(description="tier / group name")
    tier: str = Field("", description="frontend|backend|data|infra|external|security")
    parent: str = Field("", description="id of parent cluster for nesting; empty for top-level zones")
    accent: str = Field(
        "", description="zone color: blue|cyan|teal|violet|indigo|green|amber|rose|slate; empty=auto"
    )
    number: Optional[int] = Field(None, description="step badge number (1,2,3…); null to skip")
    zone: str = Field(
        "",
        description=(
            "topology boundary TYPE for real containment nesting: "
            "cloud|vpc|subnet_public|subnet_private|az|onprem; "
            "empty = logical tier (renders as a tinted section band). "
            "REQUIRES `parent` chaining to take effect: cloud>vpc>(subnet_public|"
            "subnet_private)>az, with compute/data nodes' clusters parented into the "
            "subnet. A `zone` WITHOUT a parent chain (flat sibling) is IGNORED — it "
            "draws no boundary. Only use it when you actually nest the clusters."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_label_aliases(cls, values):
        if isinstance(values, dict) and not values.get("label"):
            for alias in ("title", "name"):
                if values.get(alias):
                    return {**values, "label": values[alias]}
        return values


class BPEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from", description="source node id")
    to: str = Field(description="target node id")
    label: str = Field("", description="operation or protocol label")
    protocol: str = Field("", description="HTTP|gRPC|AMQP|TCP|WebSocket|SQL|Redis")
    flow: str = Field("", description="data|control|serving|registry|monitoring|security; empty=neutral")
    style: str = Field("", description="solid|dashed|dotted; empty=infer from flow")

    @model_validator(mode="before")
    @classmethod
    def _coerce_endpoint_aliases(cls, values):
        if not isinstance(values, dict):
            return values
        out = dict(values)
        if not out.get("from") and not out.get("from_"):
            for alias in ("source", "src", "source_id", "from_id"):
                if out.get(alias):
                    out["from"] = out[alias]
                    break
        if not out.get("to"):
            for alias in ("target", "dst", "target_id", "to_id"):
                if out.get(alias):
                    out["to"] = out[alias]
                    break
        return out


class LegendEntry(BaseModel):
    """One row of the diagram legend mapping a flow category to a human label."""

    label: str = Field(description="human-readable name, e.g. 'Data & Training Flow'")
    flow: str = Field(
        "",
        description="the matching BPEdge.flow key (data|control|serving|registry|"
        "monitoring|security) — its color/style is taken from that flow",
    )


class Blueprint(CoercingModel):
    """A structured architecture blueprint."""

    audience: str = Field(
        "client", description="client|engineer; default client for customer-facing diagrams"
    )
    detail_level: str = Field("architecture", description="architecture|engineering|code")
    layout_intent: str = Field(
        "left_to_right_pipeline",
        description=(
            "e.g. left_to_right_pipeline or top_down_stack — stick to these two for "
            "almost every diagram; they keep edges routing in one clean top-to-bottom "
            "channel. 'grid' (2-column layer bands) exists but is EXPERIMENTAL and "
            "opt-in only — it visibly tangles cross-band edges and wastes space "
            "stretching small bands to match the largest one, so avoid it unless "
            "explicitly asked for a denser/more compact arrangement.\n"
            "5 topology-specific values (use ONLY when the diagram genuinely IS that "
            "topology, not as a style choice): 'hub_spoke' (event bus / message "
            "broker with N producers/consumers — hub node auto-picked by highest "
            "edge count, or set top-level `hub` to a node id); 'hierarchy' (org "
            "tree / Landing Zone OU structure — levels inferred by BFS from nodes "
            "with no incoming edge, sharp tree-edge corners); 'mesh' (multi-account "
            "/ service-mesh peer connectivity — no natural hub or tree); 'sequence' "
            "(a numbered request walkthrough — every edge gets a step number in "
            "declared order, 1..n); 'hybrid' (on-prem <-> cloud / DR — two "
            "top-level site clusters). hub_spoke/hierarchy/mesh ALWAYS render in "
            "the icon preset (no refined-preset layout exists for them, even if "
            "style_preset='refined' is set); sequence/hybrid compose with refined."
        ),
    )
    presentation_style: Literal["slide", "diagram"] = Field(
        "slide",
        description="slide (default): title band + legend; diagram: body-only, use ONLY when user asks for plain/raw diagram",
    )
    density: Literal["standard", "detailed", "poster"] = Field(
        "detailed",
        description=(
            "detailed (DEFAULT): flow-driven LR landscape, ~20-45 nodes, sublabels mandatory, real cross-cluster edges. "
            "poster: dense wall-grid 25-45 nodes in numbered planes; use ONLY when user asks for poster/wall layout. "
            "standard: small systems only (<10 components, ≤3 tiers, 12-18 nodes)."
        ),
    )
    slide_title: str = Field(
        "",
        description="large slide hero title; default to the system/product name when presentation_style=slide",
    )
    slide_kicker: str = Field(
        "",
        description="small hero kicker/subtitle above the slide title",
    )
    brand: str = Field(
        "",
        description="brand text shown in the slide top-right; omit when unknown",
    )
    diagram_title: str = Field(
        "",
        description="caption above the architecture panel inside a slide",
    )
    pattern: str = Field(description="microservices|monolith|serverless|event-driven|hybrid")
    pattern_rationale: str = Field(
        "", description="2-3 sentences: why this architecture pattern fits these requirements"
    )
    key_decisions: list[str] = Field(
        default_factory=list,
        description="3-6 design decisions & trade-offs (data flow, scaling, HA, security, storage, integration), one sentence each",
    )
    c4_level: Literal["context", "container", "component"] = Field(
        "container",
        description=(
            "container (default, full components) | context (5-8 nodes, boundaries+actors "
            "only) | component (single-container internals). Only context/container are "
            "rendered by the native architecture engine; a formal C4-notation diagram "
            "(all three levels, with stereotypes/dashed relationships) is a separate "
            "diagram_kind='c4' request handled by the drawer's diagrams.c4 code path, "
            "not this Blueprint."
        ),
    )
    pillar_coverage: Optional[PillarCoverage] = Field(
        default=None, description="WAF 6-pillar coverage: addressed_by node IDs + known gaps per pillar"
    )
    nfr_mapping: list[NFRMapping] = Field(
        default_factory=list,
        description="each NFR mapped to mechanism and node_ids; use measurable NFRs (SLA%, latency ms)",
    )
    legend: list[LegendEntry] = Field(
        default_factory=list, description="legend rows per flow category; empty=auto-derive from edges"
    )
    hub: str = Field(
        "",
        description=(
            "layout_intent='hub_spoke' ONLY: node id to use as the hub. Empty = "
            "auto-pick the highest-degree node."
        ),
    )
    nodes: list[BPNode] = Field(default_factory=list)
    clusters: list[BPCluster] = Field(default_factory=list)
    edges: list[BPEdge] = Field(default_factory=list)
    process: Optional[ProcessBlueprint] = Field(
        None,
        description=(
            "Set ONLY for a BPMN swimlane process diagram (business process / "
            "workflow with roles x phases) — routes rendering to the native BPMN "
            "builder instead of the architecture nodes/clusters/edges above. "
            "When set, leave nodes/clusters/edges empty; pattern/density/layout_intent "
            "are ignored for process diagrams."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_key_decision_objects(cls, values):
        if not isinstance(values, dict):
            return values
        decisions = values.get("key_decisions")
        if not isinstance(decisions, list):
            return values

        def _text(item) -> str:
            if isinstance(item, str):
                return item
            if not isinstance(item, dict):
                return str(item)
            title = str(item.get("decision") or "").strip()
            rationale = str(item.get("rationale") or "").strip()
            tradeoffs = item.get("tradeoffs")
            if isinstance(tradeoffs, list):
                tradeoffs_text = "; ".join(str(t).strip() for t in tradeoffs if str(t).strip())
            else:
                tradeoffs_text = str(tradeoffs or "").strip()
            parts = [
                p for p in (title, rationale, f"Trade-offs: {tradeoffs_text}" if tradeoffs_text else "") if p
            ]
            return " — ".join(parts) if parts else "Decision"

        return {**values, "key_decisions": [_text(d) for d in decisions]}
