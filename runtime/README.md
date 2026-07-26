# diagram-agent-runtime

A thin Node.js CopilotKit v2 runtime that proxies AG-UI traffic between the
frontend and the Python backend (`backend/`). See the frontend's migration
plan for the full design rationale; this file only covers operational
constraints that matter for deployment.

## Statefulness (single-replica only)

This service is **not stateless**:

- `PassthroughRunner` tracks in-flight runs per `threadId` in an in-memory
  `Map` (for `isRunning`/`stop`).
- `artifact-store.ts` holds a bounded in-memory LRU (512MB cap, 30-minute
  TTL) of offloaded artifact bytes (diagram PNG, PDF report, PPTX proposal,
  WBS Excel), served back at `GET /api/artifacts/:key`.

Neither is shared across processes. Running more than one replica behind a
load balancer without sticky sessions (by `threadId`) will cause:

- `isRunning`/`stop` to report incorrectly for a run handled by a different
  replica.
- `GET /api/artifacts/:key` to 404 if the request lands on a replica that
  didn't generate/cache that artifact.

**Fix if this ever needs to scale out:** sticky sessions keyed on
`threadId` (works today, zero code change), or move `artifact-store.ts` to
a shared backend (Redis) and make `PassthroughRunner`'s tracking map
external too. Neither is implemented — this is a single-replica internal
tool today.

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `BACKEND_URL` | `http://backend:8001` | The Python backend's base URL |
| `PORT` | `3001` | This service's listen port |
| `ALLOWED_ORIGINS` | (unset = allow all) | CORS allow-list, comma-separated |

## Endpoints

- `POST /api/copilotkit/*` — the CopilotKit v2 runtime surface (agent run,
  connect, etc).
- `GET /api/artifacts/:key` — offloaded artifact bytes; 404 once evicted or
  expired.
- `GET /healthz` — liveness check (used by the Dockerfile `HEALTHCHECK` and
  compose).
