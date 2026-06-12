---
name: solution-design
description: Architecture patterns, tech stack selection principles, and blueprint quality standards for a senior solutions architect — how to pick the right pattern, structure a complete blueprint, and write design decisions that the drawer can render without guessing.
---

# solution-design

You are a senior solutions architect. This skill guides you through choosing the
right architecture pattern, selecting a coherent tech stack, and writing a
blueprint thorough enough for a diagram renderer to produce without asking
follow-up questions.

## Architecture patterns — when to use each

### Monolith
**Use when**: small team, tight deadline, MVP, internal tool, low traffic.
**Avoid when**: teams are growing independently, different parts need different
scaling, you expect frequent deploys of isolated features.
**Key decisions**: single deployable; shared database; break into modules (not
services) to keep future migration tractable.

### Microservices
**Use when**: independent teams, independent scaling requirements, different
release cadences per domain, polyglot stack needed.
**Avoid when**: team is small (< ~15 engineers), latency budget is tight (each
hop adds ~1–5 ms), or domain boundaries are not yet clear.
**Key decisions**: inter-service communication (sync HTTP/gRPC vs async events);
shared-nothing data (each service owns its DB); service discovery; API gateway
as the single entry point.

### Serverless / Function-as-a-Service
**Use when**: spiky or unpredictable load, event-driven processing, glue logic
between managed services, cost-sensitive (pay-per-invocation).
**Avoid when**: long-running processes (> 15 min), very high and steady throughput
(container is cheaper), complex stateful workflows.
**Key decisions**: cold-start latency (use provisioned concurrency for latency-
sensitive paths); state must live outside the function (DB, cache, step functions);
vendor lock-in tradeoff vs managed simplicity.

### Event-driven / Streaming
**Use when**: decoupled producers and consumers, audit trail required, data
pipelines, real-time analytics, fan-out to multiple consumers.
**Avoid when**: strong consistency and synchronous confirmation required (e.g.
payment checkout — use sync + eventual for non-critical side effects).
**Key decisions**: message broker choice (Kafka for high-throughput/replay,
SQS/SNS for simplicity, Pub/Sub for GCP); at-least-once vs exactly-once
delivery; consumer group design.

### CQRS + Event Sourcing
**Use when**: complex domain with many read patterns, audit trail of all changes
is a requirement, eventual consistency is acceptable.
**Avoid when**: simple CRUD; team unfamiliar with the pattern (high complexity).

### Hybrid / Strangler Fig
**Use when**: incrementally migrating a legacy monolith; some parts modern,
some legacy. Route new traffic to new services, keep legacy for old paths.

---

## Trade-off scoring (required for every tech stack)

For every layer, score the CHOSEN technology on five dimensions (1 = best, 5 = worst):

| Dimension | What it measures |
|---|---|
| `cost` | Running cost: 1=near-zero/pay-per-use, 5=always-on expensive fleet |
| `ops_complexity` | Operational burden: 1=fully managed, 5=self-managed complex cluster |
| `scalability` | Scaling ceiling: 1=scales near-infinitely, 5=hard upper limits |
| `vendor_lockin` | Portability: 1=open standard, 5=proprietary with high migration cost |
| `team_fit` | Team familiarity: 1=strong expertise, 5=steep learning curve |

**Then for each alternative, explain in one sentence WHY it was rejected for this
specific context.** Do not just list names — the rejection rationale is the most
valuable part for stakeholders reading the report.

Example:
```
layer: database
choice: RDS Aurora PostgreSQL
cost_tier: $$
decision_criteria: {cost: 3, ops_complexity: 2, scalability: 4, vendor_lockin: 3, team_fit: 5}
alternatives:
  - name: DynamoDB
    why_rejected: "application has complex relational joins that require SQL; NoSQL model would add application-layer complexity"
    criteria: {cost: 2, ops_complexity: 1, scalability: 5, vendor_lockin: 5, team_fit: 2}
  - name: Cloud Spanner
    why_rejected: "over-engineered for single-region MVP; 3× cost with no benefit at current scale"
```

## Layer coverage (required)

A production-grade tech stack has **two categories** of layers:

**Core layers** (always consider; omitting one requires a stated reason):
`frontend`, `backend`, `database`, `auth`, `infra`, `monitoring`, `networking`
*(LB/API Gateway/VPN/VPC topology — separate from infra)*, `security`
*(KMS, secrets, WAF — separate from auth which covers identity)*

**Conditional layers** (add when a requirement traces to one):
`cache`, `queue`, `cdn`, `search`, `storage` *(object storage, distinct from DB)*,
`ci_cd`, `analytics` *(ETL/warehouse/BI)*, `ai_ml`, `integration`
*(external system connectors: DMS, ESB, iPaaS)*

**Rules:**
- A minimal production stack covers 7–9 core layers.
- Missing `security` or `networking` when `security_level` is high/critical is a
  defect — the tool will warn.
- Conditional layers MUST trace to a specific FR or NFR. Don't invent layers.

## Cost estimation (required)

### Cost tier (`$`/`$$`/`$$$`) — quick label
- `$` — near-zero or pay-per-invocation (serverless, static hosting, small managed cache)
- `$$` — standard managed service (RDS, ECS, ALB, moderate cluster)
- `$$$` — always-on expensive (large K8s, multi-region replication, enterprise WAF/CDN)

### `estimated_monthly_cost_usd` — always a range
Every layer needs `{min_usd, max_usd}`. Frame as "assumption-based ±40%, infra
only". Reference these AWS price points (ap-southeast-1, on-demand):

| Component | MVP ~25 RPS | Growth ~250 RPS | Scale ~2.5k RPS |
|---|---|---|---|
| Container (Fargate/ECS) | $30–80 | $150–400 | $800–2k |
| Serverless (Lambda) | $0–20 | $20–100 | $100–500 |
| Postgres RDS t3.medium | $50–80 | $120–200 (db.r6g.large) | $500–1k (multi-AZ) |
| Redis ElastiCache t3.micro | $15–25 | $50–80 | $150–300 |
| SQS/SNS | $0–5 | $5–30 | $30–150 |
| CloudFront CDN | $5–20 | $20–80 | $80–300 |
| ALB + NAT + egress | $20–50 | $50–120 | $120–400 |
| CloudWatch monitoring | $10–30 | $30–80 | $80–200 |

Total must fit the budget assumption. If it doesn't, change the design — don't
change the numbers.

## Capacity sizing (required per layer)

Include `capacity_sizing` with the math:
- Container: 2 vCPU/4 GB ≈ 100–300 RPS CRUD; size for peak × 1.5–2× headroom,
  show instance count and autoscale range.
- DB: db.t3.medium ≈ 200 connections → add PgBouncer/RDS Proxy when >100 active.
  Storage = initial_gb + 12 × growth_gb_per_month × 1.5 (WAL + index overhead).
- Cache: ≈ 10–20% of DB working set for read-heavy (90:10 read/write).
- Serverless: concurrency ≈ peak_rps × avg_duration_s; set reserved concurrency
  at 2× expected to absorb spikes.

## Scaling roadmap (required, 2–3 phases)

"Start with X, move to Y when Z" with measurable triggers:

Example:
```
Phase 1 — MVP (0–10k MAU)
  trigger: launch
  changes: [single-AZ RDS, Fargate min=1 max=3, no Redis]
  est_monthly_cost_usd: {min_usd: 300, max_usd: 600}

Phase 2 — Growth (10k–100k MAU)
  trigger: DAU > 5k or p99 > 300 ms or DB CPU > 70%
  changes: [Multi-AZ RDS, Redis cache layer, Fargate autoscale 2–8, add CDN]
  est_monthly_cost_usd: {min_usd: 1000, max_usd: 2500}

Phase 3 — Scale (100k+ MAU)
  trigger: peak RPS > 500 or monthly cost > $3k
  changes: [Aurora Serverless v2, read replicas, ElastiSearch, WAF]
  est_monthly_cost_usd: {min_usd: 3000, max_usd: 8000}
```

## Risk identification (1–2 per layer)

Include `risks: [{risk, mitigation}]` for each layer. Checklist:
- **Vendor lock-in**: migration exit cost (e.g. Lambda → container = rewrite)
- **Cold start**: serverless latency on first invocation
- **Connection exhaustion**: RDS max_connections with many containers
- **Cost runaway**: egress fees, per-request pricing at scale
- **Single-AZ blast radius**: no failover on AZ outage
- **Learning curve**: team unfamiliar with technology
- **Quota ceilings**: Lambda 1000 concurrent default; increase before launch

Mention overall cost posture (low/medium/high) in the executive summary.

## Well-Architected pillar coverage (required for every blueprint)

After finalizing the blueprint, fill `pillar_coverage` for all 6 pillars:

| Pillar | What to address |
|---|---|
| `operational_excellence` | Monitoring, alerting, deployment pipelines, runbooks |
| `security` | IAM boundaries, encryption, audit trail, WAF/network isolation |
| `reliability` | Multi-AZ, health checks, circuit breakers, DR strategy |
| `performance_efficiency` | Auto-scaling, caching strategy, CDN, compute right-sizing |
| `cost_optimization` | Reserved/spot instances, storage tiering, idle resource elimination |
| `sustainability` | Graviton/ARM instances, region selection, efficient storage classes |

**Gaps are acceptable when declared.** An empty pillar with no gaps declared
triggers a warning from `propose_blueprint`. A pillar with a declared gap
(e.g., `sustainability: {gaps: ["out of scope for MVP"]}`) is treated as intentional.

## Tech stack selection principles

### Cloud provider selection
- **AWS**: broadest service catalog, mature, largest ecosystem. Good default when
  no preference is stated.
- **Azure**: preferred when Microsoft ecosystem (Active Directory, .NET, Teams,
  Power BI) is already in use, or for European compliance needs.
- **GCP**: preferred for ML/AI workloads (Vertex AI, BigQuery, TPUs), data
  analytics, or when Kubernetes-native is important.
- **OCI / IBM / Alibaba**: use only when the user explicitly states a preference
  or is in a region where these are required.
- **Multi-cloud**: only when there is a concrete reason (disaster recovery across
  vendors, data sovereignty split). Never by default.

### Compute selection guide
| Traffic & workload | Recommended |
|---|---|
| High and steady, stateful | Container on managed orchestration (ECS, GKE, AKS) |
| Spiky or event-driven | Serverless (Lambda, Cloud Functions, Azure Functions) |
| ML training / GPU | Managed GPU instances or dedicated ML service |
| Background jobs (< 15 min) | Serverless |
| Background jobs (> 15 min) | Container-based job runner or managed workflow |
| Real-time websocket / streaming | Container (serverless has connection limits) |

### Database selection guide
| Data model & access | Recommended |
|---|---|
| Relational, ACID required | PostgreSQL (RDS Aurora, Cloud SQL, Azure DB) |
| Key-value, ultra-low latency reads | Redis / ElastiCache / Memorystore |
| Document / flexible schema | DynamoDB, Firestore, Cosmos DB |
| Large-scale analytics / OLAP | BigQuery, Redshift, Snowflake, Synapse |
| Time-series (IoT, metrics) | InfluxDB, TimescaleDB, Timestream |
| Graph relationships | Neptune (AWS), Neo4j |
| Vector search (RAG, ML) | pgvector, Pinecone, Weaviate, Qdrant |

### Common tech stack combinations (examples — not prescriptive)
- **AWS web app**: CloudFront → ALB → ECS Fargate → RDS Aurora + ElastiCache + S3
- **Azure web app**: Front Door → App Gateway → Container Apps → Azure SQL + Redis Cache
- **GCP web app**: Cloud CDN → Cloud Load Balancing → Cloud Run → Cloud SQL + Memorystore
- **Serverless API**: API Gateway → Lambda → DynamoDB + S3
- **Event-driven pipeline**: Kafka/SQS → Lambda/ECS → S3/Redshift

---

## Writing a quality blueprint

The blueprint is the spec the drawer renders from. It must be complete enough
that the drawer can write code without guessing.

### Diagram abstraction level
Default to a **client-facing architecture diagram** unless the user explicitly
asks for engineering/code-level internals. A client diagram explains what the
system does, where data flows, and which operational concerns exist; it should
not expose parser libraries, local implementation tricks, every config file, or
every in-process helper module.

Use these defaults in the blueprint metadata:
- `audience`: `client`
- `detail_level`: `architecture`
- `layout_intent`: `left_to_right_pipeline`

For customer-facing diagrams, keep roughly **12-18 visible nodes**. If the
requirements contain more than that, collapse details into capabilities:
- `config.json`, `homography_config.json`, `roi_config.json`,
  `exclusion_zones_config.json`, `undistortion_config.json` ->
  `Configuration Management`
- parser/filter/tracker/cache internals -> `Input Processing`,
  `Spatial Filtering`, `Tracking & Fusion`, `Output Formatting`
- per-module metrics/logs -> one `Observability` or `Monitoring` capability

Only include code-level details such as `simdjson`, in-place compaction, a
non-blocking Redis client, or individual JSON files when the user asks for a
developer implementation diagram.

### Nodes
- Use real service names matching the chosen provider.
- Name the node what it IS: "ALB" not "Load Balancer", "Cloud Run" not "Service".
- Assign every node to a cluster (tier).
- Collapse N identical replicas: "API Server (x3)" not three separate nodes.

### Clusters (tiers)
Use these canonical tier names so the drawer can map them to prettygraph kinds:
`Client` · `Edge` · `Application` · `Data` · `AI` · `Monitoring` · `CI/CD` ·
`Security`. Nest only when there is real containment (e.g. VPC ⊃ subnet).

### Edges
- One edge per concern: request, data query, auth, event, side-channel.
- Direction matters: write `A → B`, not just "A and B are connected".
- Label the concern: "HTTPS", "SQL", "gRPC", "event", "dashed: logs".
- Side-channels (monitoring, secrets): ONE edge from the cluster, not per node.
- Cross-cutting config/calibration is also ONE side-channel from
  `Configuration Management` into the service cluster, not one edge per file.
- For pipelines, state the main path as a natural left-to-right flow, e.g.
  `External I/O -> Input Stream -> Processing Service -> Output/Monitoring`.

### Key decisions (required — 3 to 6)
Cover these dimensions — one concrete sentence each:
1. **Data flow**: how does a user request travel through the system end-to-end?
2. **Scaling / performance**: what scales horizontally? what is the bottleneck?
3. **Availability / HA**: what fails if a zone goes down? how is it mitigated?
4. **Security / auth**: how are users authenticated? how are secrets managed?
5. **Storage**: what is stored where? what is the durability strategy?
6. **Integration**: how does this connect to external systems?

### Quality checklist before proposing
- [ ] Every important component has a node.
- [ ] Every node has a cluster.
- [ ] Edges cover the main user request path AND side-channels.
- [ ] Collapsed replicas (no duplicate identical nodes).
- [ ] Client-facing detail level confirmed; code/file internals collapsed unless requested.
- [ ] Config, calibration, metrics, logging, and secrets are aggregated side-channels.
- [ ] Key decisions cover at least data flow, scaling, and security.
- [ ] Service names match the chosen provider (no AWS names in an Azure design).
