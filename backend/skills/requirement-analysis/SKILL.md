---
name: requirement-analysis
description: How to extract a complete, unambiguous architecture brief from a user request — what to clarify before designing, what signals indicate the scope, and how to avoid designing the wrong system.
---

# requirement-analysis

Before proposing any tech stack or blueprint, you must understand what you are
actually building. This skill guides you from a raw user request to a clear,
actionable brief.

## Step 1 — Read and classify the request

Identify the **type of system** the user wants. Common categories:

| Signal in request | System type |
|---|---|
| "users", "signup", "dashboard", "API" | Web application |
| "pipeline", "ETL", "batch", "ingestion" | Data pipeline |
| "real-time", "stream", "events", "IoT" | Event-driven / streaming system |
| "microservices", "services talk to each other" | Distributed service mesh |
| "ML model", "training", "inference", "LLM" | ML/AI platform |
| "mobile app", "push notification" | Mobile backend |
| "internal tool", "admin panel" | Low-traffic back-office app |
| "SaaS", "multi-tenant", "per-customer isolation" | Multi-tenant platform |

The system type drives the architecture pattern and tech stack candidates. State
which type you identified — if it is ambiguous, ask.

## Step 2 — Identify what is missing

These four dimensions determine the architecture. If any are missing or vague,
you need them before designing:

### 2a. Scale & traffic
- How many concurrent users / requests per second at peak?
- Is the load steady or spiky (batch jobs, event storms)?
- Data volume: MB/day, GB/day, TB/day?

**Why it matters**: a system handling 100 users vs 1 000 000 users uses different
compute models (single server vs auto-scaling vs serverless) and different
database choices (SQLite vs RDS vs Spanner).

### 2b. Availability & reliability
- Does downtime cost money (e-commerce) or is it acceptable (internal tool)?
- Is there a stated SLA (99.9%, 99.99%)? State it as a percentage.
- Any disaster recovery requirement (RPO/RTO)? State in minutes.
- Any latency requirement? State as p99 latency in milliseconds.

**Why it matters**: HA requires active-active or active-passive replicas, a
load balancer, multi-AZ/multi-region deployment — adding significant cost and
complexity. A simple internal tool does not need this.

**NFR format requirement**: non-functional requirements MUST be measurable.
If the user does not provide numbers, make an explicit assumption and document it:
- ✓ "99.9% uptime SLA (3 nines, ~8.7 h downtime/year)" — NOT "high availability"
- ✓ "RPO=15 min, RTO=30 min" — NOT "fast recovery"
- ✓ "p99 API latency ≤ 200 ms under 1,000 RPS" — NOT "low latency"
- ✓ "PCI DSS Level 1 compliance required" — NOT "secure"

These measurable NFRs go into `diagram_brief.non_functional_requirements` and
will be matched against `blueprint.nfr_mapping` by the validator. Vague NFRs
that cannot be matched produce warnings.

### 2c. Compliance & security constraints
- Is user data involved? PII, HIPAA, GDPR, PCI?
- Is the system public-facing or internal only?
- Any authentication requirement (SSO, SAML, social login)?
- Data residency requirement (must stay in a specific region / country)?

**Why it matters**: compliance constraints can force specific services (e.g.
only HIPAA-compliant managed databases), encryption at rest/transit, audit logs,
and a dedicated security tier.

### 2d. Integration & dependencies
- Does this connect to any existing systems (CRM, ERP, payment gateway)?
- Any specific third-party services already chosen (Stripe, Twilio, SendGrid)?
- Is there an existing cloud account / vendor preference?

**Why it matters**: integration constraints often force specific protocols
(SOAP, EDI, proprietary SDK) and can rule out certain architectures.

## Step 3 — When to ask vs when to proceed

**Ask 1–3 concise questions** when:
- The system type is ambiguous.
- Scale is entirely unknown and it would change the architecture significantly
  (e.g. serverless vs containerized).
- A compliance constraint might apply (any mention of users, payments, health).

**Proceed without asking** when:
- The request is self-contained and detailed enough.
- The missing dimension would NOT change the pattern (e.g. exact user count is
  unknown but the user said "startup MVP" — design for modest scale, note the
  assumption).
- You can make a safe, stated assumption that the user can correct.

**Never ask more than 3 questions in one turn.** If the requirements are truly
sparse, prioritize the highest-impact unknowns (usually scale + compliance).

### 2e. Sizing assumptions — numbers, not adjectives

A senior SA always derives explicit numbers from the request signals before
proposing a stack. Use this heuristic table:

| Signal | MAU | Peak concurrent | Peak RPS | Budget tier |
|---|---|---|---|---|
| "personal project", "side project" | 0–1k | <50 | <5 | startup (<$200/mo) |
| "MVP", "startup", "small team" | 1–5k | 50–500 | 5–50 | startup ($200–1k/mo) |
| "growing startup", "Series A", "SMB" | 10–100k | 500–5k | 50–500 | smb ($1k–5k/mo) |
| "mid-market", "enterprise dept" | 100k–1M | 5k–50k | 500–2.5k | mid-market ($5k–25k/mo) |
| "enterprise", "global", "millions of users" | 1M+ | 50k+ | 2.5k+ | enterprise ($25k+/mo) |

**Derivation chain — always show the math:**
- DAU ≈ 20–30% MAU (B2C) or 60–80% MAU (B2B)
- Peak concurrent ≈ 5–10% DAU
- Peak RPS ≈ concurrent × (avg actions/min) ÷ 60 (assume 2 actions/min if unknown)
- Team not mentioned → assume 3–6 engineers, mixed skill, basic CI/CD → prefer managed services
- Data: if not stated, assume 10 GB initial + 1 GB/month growth for typical SaaS

## Step 4 — Formalize your understanding

Before calling `propose_tech_stack`, mentally (or in notes) complete this brief:

```
System type      : [e.g. web application — SaaS, multi-tenant]
Core features    : [e.g. user auth, product catalog, checkout, order history]
Budget           : [e.g. startup tier ~$500–2k/mo (derived from "early-stage startup")]
Peak load        : [e.g. ~150 RPS peak (derived: 50k MAU → 12k DAU → 1.2k concurrent × 2 actions/min ÷ 60)]
Data volume      : [e.g. 20 GB initial + 2 GB/month (derived from feature set)]
Team             : [e.g. 4 engineers, mixed, basic CI/CD (not stated — assumed)]
Phase            : [e.g. MVP → growth]
Availability req : [e.g. 99.9% (≤8.8h downtime/yr)]
Compliance       : [e.g. PCI DSS required for payment card data]
Cloud preference : [e.g. AWS (stated by user) / no preference (default to most common)]
Key integrations : [e.g. Stripe for payments, SendGrid for email]
Assumptions      : [anything not validated by the customer — goes in confirm_with_customer]
```

If you cannot fill this in confidently, ask. If you can, proceed to the tech stack.

## Anti-patterns to avoid

- **Designing before understanding**: proposing a microservices architecture for
  what turns out to be a simple CRUD app wasted the user's time.
- **Over-asking**: interrogating the user with 10 questions kills momentum. Ask
  only about dimensions that change the architecture.
- **Assuming AWS by default**: if the user hasn't stated a cloud preference,
  ask or make a brief recommendation with alternatives.
- **Ignoring the "simple MVP" signal**: a request that says "quick prototype",
  "MVP", "just get it running" = prioritize simplicity and cost over HA/scale.
- **Scope creep assumptions**: do not add features the user didn't ask for.
  Design exactly what was requested; note what could be added later.
- **Adjectives instead of numbers**: "'medium traffic' instead of '~150 RPS peak
  (assumed: 50k MAU → 12k DAU → 1.2k concurrent × 2 actions/min ÷ 60)'" is
  junior work. Every sizing claim must have a derivation.
