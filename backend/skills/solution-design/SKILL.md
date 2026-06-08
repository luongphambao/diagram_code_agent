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
- [ ] Key decisions cover at least data flow, scaling, and security.
- [ ] Service names match the chosen provider (no AWS names in an Azure design).
