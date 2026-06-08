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
- Is there a stated SLA (99.9%, 99.99%)?
- Any disaster recovery requirement (RPO/RTO)?

**Why it matters**: HA requires active-active or active-passive replicas, a
load balancer, multi-AZ/multi-region deployment — adding significant cost and
complexity. A simple internal tool does not need this.

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

## Step 4 — Formalize your understanding

Before calling `propose_tech_stack`, mentally (or in notes) complete this brief:

```
System type      : [e.g. web application — SaaS, multi-tenant]
Core features    : [e.g. user auth, product catalog, checkout, order history]
Scale estimate   : [e.g. ~500 concurrent users, peaks at checkout events]
Availability req : [e.g. no SLA stated — design for moderate HA, single-region]
Compliance       : [e.g. PCI DSS required for payment card data]
Cloud preference : [e.g. AWS (stated by user) / no preference (default to most common)]
Key integrations : [e.g. Stripe for payments, SendGrid for email]
Assumptions      : [anything you assumed that the user should validate]
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
