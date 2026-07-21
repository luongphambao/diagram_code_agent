# Diagram Code Agent

Diagram Code Agent turns plain-English system requirements into architecture diagrams. It runs a staged AI workflow, writes Python `diagrams` code, renders a PNG, exports editable `.drawio`, and lets users approve or reject important steps through a React UI.

## What It Does

- Reads typed requirements or uploaded PDF/DOCX/MD/TXT documents.
- Runs live web search (Tavily, ≤3 calls/session) to verify current pricing, versions, and reference architectures before proposing the tech stack.
- Proposes a technology stack and waits for user approval.
- Proposes an architecture blueprint and waits for user approval.
- Generates diagram code with local icon/logo support.
- Renders diagram artifacts: `diagram.py`, `out.png`, `out.dot`, `out.drawio`.
- Runs a deterministic native layout/repair pass (edge bundling, layer reordering, crossing-reduction scoring) before every export — see [Diagram Quality Engine](#diagram-quality-engine).
- Supports BPMN/swimlane process diagrams (auto-detected), a dense `poster` layout mode, and `upgrade_drawio` to restyle a user-supplied `.drawio` file.
- Optionally generates a Work Breakdown Structure (phases, modules, effort, timeline) and exports it to an Excel workbook — see [Work Breakdown Structure (WBS)](#work-breakdown-structure-wbs).
- Optionally generates a HITL-approved PDF report as `out.pdf`.
- Optionally generates a HITL-approved PowerPoint proposal deck (`out.pptx`), storyboarded from the same requirements/decisions/WBS data.
- Optionally emails the report via Gmail through Composio (HITL-gated).
- Optionally books a client meeting via Google Calendar through Composio (HITL-gated).
- Optionally exports an Architecture Decision Record pack (`export_adr_pack`) or diffs the design against a real repo/Terraform/k8s state (`reality_sync`).
- Streams chat, tool activity, approvals, and final state through AG-UI/SSE.
- Persists conversations with Postgres when `DATABASE_URL` is configured.

## Example Output

Six recent end-to-end runs (diagram + editable `.drawio`, `example/*.drawio`). Names are genericized — no client/project names.

| | |
|---|---|
| ![AI financial analysis & reference-check platform](example/ai-financial-analysis-reference-check.png)<br>**AI Financial Analysis, Evidence & Reference-Check Platform** — on-prem multiagent architecture with private LLM serving, vector/knowledge graph, and industry-benchmark governance.<br>[`.drawio`](example/ai-financial-analysis-reference-check.drawio) | ![Financial-statement credit recommendation](example/bctc-credit-recommendation-multiagent.png)<br>**Financial-Statement Credit Recommendation** — IDP extraction → multiagent ratio analysis → evidence-backed credit recommendation, with deterministic rule engine and cross-checking.<br>[`.drawio`](example/bctc-credit-recommendation-multiagent.drawio) |
| ![GCP IDP + RPA finance automation](example/gcp-idp-rpa-finance-automation.png)<br>**GCP IDP + RPA Finance Automation** — end-to-end document AI and RPA orchestration on Google Cloud integrating ERP, DMS, TMS, banking, and e-invoicing systems.<br>[`.drawio`](example/gcp-idp-rpa-finance-automation.drawio) | ![Azure browser copilot + RPA orchestration](example/azure-browser-copilot-rpa-orchestration.png)<br>**Azure Browser Copilot + RPA Orchestration** — multi-agent planner/navigator/validator control plane driving a browser copilot and Power Automate RPA.<br>[`.drawio`](example/azure-browser-copilot-rpa-orchestration.drawio) |
| ![Document migration reference architecture](example/document-migration-reference-architecture.png)<br>**Document Migration Reference Architecture** — AWS control plane for enterprise document sources, OCR/normalization, search, retention, and customer-owned storage connectors.<br>[`.drawio`](example/document-migration-reference-architecture.drawio) | ![Driver operations FMS platform](example/driver-operations-fms-platform.png)<br>**Driver Operations FMS Platform** — mobile telemetry intake, secure API edge, FMS platform services, operational data, and external dispatch integrations.<br>[`.drawio`](example/driver-operations-fms-platform.drawio) |

## Tech Stack

- Backend: Python 3.11, FastAPI, Deep Agents, LangGraph, LangChain, OpenAI / Mimo, Graphviz, `diagrams`.
- Frontend: Vite, React 19, TypeScript, Tailwind CSS 4, AG-UI client.
- Storage: Postgres for durable sessions via Docker Compose; in-memory fallback for local dev.
- Assets: local `resources/icons` icon pack plus generated icon manifests.
- Integrations: Composio (Gmail, Google Calendar), Tavily (live web search), LangSmith (tracing).

## AI Agent Architecture

The backend uses one Deep Agent as the main orchestrator. The agent receives requirements, plans the diagram, calls tools to render/export artifacts, and pauses at human approval gates before moving to the next stage.

```text
User / Browser
    |
    | chat, uploads, approvals
    v
Frontend (React + AG-UI client)
    |
    | POST /agui over SSE, POST /upload
    v
FastAPI Server (backend/src/diagram_mcp/server.py)
    |
    | streams events, translates approvals to LangGraph Command(resume=...)
    v
Deep Agent (backend/src/diagram_mcp/agent.py)
    |
    +-- Main planner
    |   +-- analyze_architecture_requirements
    |   +-- propose_diagram_brief
    |   +-- web_research             # optional live Tavily search (≤3/session)
    |   +-- propose_tech_stack       # HITL approval gate
    |   +-- propose_blueprint        # HITL approval gate
    |   +-- finalize_diagram         # HITL review gate
    |   +-- generate_pdf_report      # optional HITL PDF gate
    |   +-- send_email  # optional HITL email gate (Composio Gmail)
    |   +-- propose_meeting_slots    # optional — Calendar free-slot picker
    |   +-- create_client_meeting    # optional HITL gate (Composio Google Calendar)
    |
    +-- Icon Resolver subagent
    |   +-- search_diagrams_nodes
    |   +-- resolve_icons
    |   +-- search_icons
    |   +-- fetch_logo
    |
    +-- Drawer subagent
    |   +-- writes diagram.py
    |   +-- render_diagram
    |   +-- export_drawio
    |
    +-- Critic subagent
    |   +-- inspect_diagram
    |   +-- submit_critique
    |
    +-- Filesystem backend
    |   +-- backend/agent_space/workspace/
    |   +-- backend/agent_space/memories/AGENTS.md
    |
    +-- Persistence
        +-- Postgres checkpointer/store when DATABASE_URL is set
        +-- in-memory fallback for local dev
```

### Agent Flow

1. User describes system requirements or uploads requirement documents.
2. Server extracts document text and sends prompt/context to the Deep Agent.
3. Agent runs `analyze_architecture_requirements` and `propose_diagram_brief`.
4. Agent optionally calls `web_research` (≤3 times) to verify current pricing, versions, or reference architectures before proposing the stack.
5. Agent proposes a technology stack with `propose_tech_stack` — HITL gate.
6. Frontend shows tech-stack approval card; user approves or rejects with feedback.
7. Agent proposes architecture blueprint with `propose_blueprint` — HITL gate.
8. Frontend shows blueprint card; user approves or asks for revisions.
9. Icon resolver subagent batch-resolves all node classes and icon paths.
10. Drawer subagent writes diagram code, runs the render-refine loop, and exports `.drawio`.
11. Critic subagent reviews the rendered PNG and returns PASS or REVISE with findings.
12. Agent calls `finalize_diagram` — HITL gate; frontend shows final review card and diagram artifacts.
13. If the user asks for a report, agent calls `generate_pdf_report` — frontend shows a PDF approval card before `out.pdf` is created.
14. If the user asks to email the report, agent calls `send_email` — frontend shows an email approval card before sending via Gmail through Composio.
15. If the user asks to schedule a meeting, agent queries Google Calendar with `propose_meeting_slots`, user picks a slot, then `create_client_meeting` books it — HITL gate.
16. If the user asks for an effort/project estimate, agent calls `propose_wbs_skeleton` then `propose_wbs` (both HITL gates) using the already-approved brief/stack/blueprint, then `export_wbs_excel` writes the estimation workbook. See [Work Breakdown Structure (WBS)](#work-breakdown-structure-wbs).

### Human-in-the-loop Gates

These tools are configured as approval gates:

- `propose_tech_stack`: confirms stack choices before diagram design.
- `propose_blueprint`: confirms architecture structure before code generation.
- `finalize_diagram`: confirms final rendered result before completion.
- `generate_pdf_report`: confirms report settings before creating `out.pdf`.
- `propose_deck_plan`: confirms the proposal-deck storyboard before rendering `out.pptx`.
- `generate_ppt_proposal`: confirms deck settings before creating `out.pptx`.
- `send_email`: confirms recipient and subject before sending the PDF via Gmail.
- `create_client_meeting`: confirms meeting details before booking the Google Calendar event.
- `propose_wbs_skeleton`: confirms the phase/module breakdown before effort estimation.
- `propose_wbs`: confirms estimated effort, timeline, and team plan before export.

When the user rejects a gate, the frontend sends feedback to the server. The server resumes the LangGraph run with `Command(resume=...)`, and the agent revises the current step.

### Agent Tools

Planning / approval (main agent):
- `analyze_architecture_requirements`: deterministic advisor that reads requirements and returns app type, scale, security, and suggested patterns.
- `propose_diagram_brief`: records objective, stakeholders, requirements, and constraints before design starts.
- `web_research`: live Tavily search (≤3 calls/session) to verify current pricing, latest versions/EOL, and reference architectures at the tech-stack step.
- `propose_tech_stack`: proposes the technology stack — pauses for HITL approval.
- `propose_blueprint`: proposes the full architecture blueprint — pauses for HITL approval.
- `finalize_diagram`: submits the rendered diagram for final user review — HITL gate.
- `generate_pdf_report`: creates a multi-page PDF report — pauses for HITL approval.
- `propose_deck_plan`: proposes the proposal-deck storyboard — pauses for HITL approval.
- `generate_ppt_proposal`: renders the approved storyboard to `out.pptx` — pauses for HITL approval.
- `send_email`: emails `out.pdf` via Gmail through Composio — pauses for HITL approval.
- `propose_meeting_slots`: queries Google Calendar for free slots and shows a picker (mid-run interrupt, not a gate).
- `create_client_meeting`: books the selected slot and creates a Calendar event — HITL gate.
- `propose_wbs_skeleton`: proposes phases/modules for a project estimate — pauses for HITL approval.
- `propose_wbs`: proposes effort, timeline, and team plan built on the approved skeleton — pauses for HITL approval.
- `export_wbs_excel`: writes the approved WBS to an Excel workbook; also used to re-export without re-planning on a WBS follow-up request.
- `export_adr_pack`: renders architecture decisions to an `adr_pack.md` Architecture Decision Record pack.
- `reality_sync`: read-only diff of the proposed design against a real repo/Terraform/Kubernetes state.
- `upgrade_drawio`: restyles a user-supplied `.drawio` file into a refined two-page typographic preset.

Icon resolution subagent:
- `search_diagrams_nodes`: batch-searches the built-in `diagrams` node catalog.
- `resolve_icons`: batch-resolves custom icon paths.
- `search_icons`: fallback search in the local icon pack.
- `search_drawio_shapes`: looks up draw.io shape names.
- `fetch_logo`: resolves vendor logos from local icons, Iconify, or favicon fallback.

Drawing subagent:
- `plan_style_sizes`: sets canvas size and style for the chosen output mode.
- `fit_labels`: adjusts label lengths to fit the layout.
- `declare_poster_grid`: declares multi-column logo grid for poster mode.
- `audit_diagram_code`: static analysis of generated diagram code before rendering.
- `render_diagram`: executes generated Python `diagrams` code, runs the native layout/repair pass, and returns PNG/DOT output.
- `export_drawio`: converts Graphviz DOT output into editable `.drawio`.
- `inspect_render_quality`: reads the native engineer report (`engineer_report.json`) — arrow clarity score, edge crossings, bundled edges — capped at 2 inspections per export. See [Diagram Quality Engine](#diagram-quality-engine).

Critic subagent:
- `inspect_diagram`: reads the rendered PNG and checks layout quality.
- `submit_critique`: records verdict (PASS or REVISE with findings) for the main agent.

WBS planner subagent:
- Reads the approved `diagram_brief.json`, `tech_stack.json`, and `blueprint.json`.
- Decomposes the solution into phases → modules → features, estimates dev effort, and derives BA/QC/PM effort from dev via fixed ratios.
- Plans timeline, team composition, and milestones, then hands off to `propose_wbs_skeleton` / `propose_wbs` on the main agent.

PPT generator subagent:
- `plan_deck`: reads `blueprint.json`/`diagram_brief.json`/`tech_stack.json`/`solution_model.json` and writes `deck_plan.json`, a fixed storyboard with every slide grounded in the canonical solution model (requirements, decisions, components, WBS effort, risks).
- `resolve_tech_stack_icons`: fetches per-technology logos, grouped by layer, for the tech-stack slide.
- `create_pptx`: renders `out.pptx` from `deck_plan.json`.

### Tool Call Flow

The intended tool order is:

1. `analyze_architecture_requirements`
2. `propose_diagram_brief`
3. `web_research` *(optional — ≤3 calls/session, only at this step, to verify pricing/versions/reference architectures)*
4. `propose_tech_stack` *(HITL gate)*
5. `propose_blueprint` *(HITL gate)*
6. `task(subagent_type="icon_resolver", ...)` — batch-resolves all node classes and icon paths
7. `task(subagent_type="drawer", ...)` — writes diagram code, render-refine loop, exports drawio
8. `task(subagent_type="critic", ...)` — reviews rendered diagram against blueprint
9. `finalize_diagram` *(HITL gate)*
10. `generate_pdf_report` *(optional HITL gate — only when the user asks for a PDF report)*
11. `send_email` *(optional HITL gate — only when the user asks to email the report)*
12. `propose_meeting_slots` *(optional — queries Google Calendar and shows slot picker)*
13. `create_client_meeting` *(optional HITL gate — books the selected slot)*

`generate_pdf_report` pauses for HITL approval before writing `out.pdf`.
`send_email` pauses for HITL approval before sending the PDF via Gmail.
`create_client_meeting` pauses for HITL approval before creating the calendar event.

Example PDF tool call:

```json
{
  "title": "Architecture Blueprint",
  "subtitle": "Solution Report",
  "brand": "Customer or Product Name",
  "include_sections": ["cover", "solution", "techstack", "blueprint", "diagram"]
}
```

### Memory and Skills

- Memory file: `backend/agent_space/memories/AGENTS.md`.
- Skills directory: `backend/skills/`.
- Diagram generation skills: `diagrams-as-code` and `pro-style`.
- Runtime workspace: `backend/agent_space/workspace/`.

## Work Breakdown Structure (WBS)

On top of the diagram, the agent can turn an already-approved solution (brief + tech stack + blueprint) into a project estimate — phases, modules, effort, timeline, and team — exported as an Excel workbook.

- Trigger: only when the user explicitly asks for an estimate (e.g. "estimate effort", "work breakdown", "man-day", or the Vietnamese equivalents "ước lượng", "phân rã công việc"). It never runs unprompted.
- Flow: `wbs_planner` subagent reads `diagram_brief.json` / `tech_stack.json` / `blueprint.json`, decomposes the solution into phases → modules → features, and estimates dev effort; BA/QC/PM effort is derived from dev effort via fixed ratios. The main agent then calls `propose_wbs_skeleton` (HITL) → `propose_wbs` (HITL) → `export_wbs_excel`.
- Follow-up handling: if the user asks for a WBS again in a later message and a solution/WBS already exists on disk, the server skips clearing stage markers so upstream artifacts survive, and — if `wbs.json` already exists — the agent re-exports directly with `export_wbs_excel` instead of re-running the planner.
- Optional sync: `export_to_delivery(system, dry_run=True)` previews (dry-run) pushing the WBS to an external delivery tool (Jira/Linear/Confluence).
- Artifacts: `wbs_skeleton.json`, `wbs.json`, and the exported `.xlsx` workbook under the run's workspace.

### Sample WBS Workbook

Exported from the [AI Financial Analysis, Evidence & Reference-Check Platform](#example-output) run above ([`.xlsx`](example/ai-financial-analysis-reference-check-wbs.xlsx)). Every sheet is generated — nothing is hand-filled.

**1. Effort** — effort and cost rolled up by module and role (BE/FE/Requirement/Testing/PM).
![WBS sheet: Effort](example/wbs-sheet-1-effort.png)

**2. WBS** — full work breakdown: phase → module → feature, with per-feature effort and remarks.
![WBS sheet: WBS](example/wbs-sheet-2-wbs.png)

**3. Delivery Plan** — sprint-level Gantt, resource plan, and delivery milestones.
![WBS sheet: Delivery Plan](example/wbs-sheet-3-delivery-plan.png)

**4. Master Data** — configurable effort ratios (PM/BA/QC on dev) and role rates used to derive the estimate.
![WBS sheet: Master Data](example/wbs-sheet-4-master-data.png)

## Diagram Quality Engine

Every render/export runs a deterministic, zero-LLM-token layout and repair pass before the file is written.

- `analyze_layout` (`backend/src/prettygraph/native/layout_plan.py`): reorders layer bands along the dominant edge flow, bundles repetitive hub fan-out edges that share a label into one representative edge, and picks an aspect-aware grid column count.
- `auto_repair` (`backend/src/prettygraph/native/repair.py`): builds up to 6 candidate layout variants — including an "unplanned" baseline that's always kept as a floor — scores each with the structural validator, and keeps the best-scoring candidate.
- Scoring surfaces as `arrow_clarity_score`, `visible_edge_count`, `bundled_edge_count`, `crossings_per_edge`, and `long_edge_ratio` in `engineer_report.json`.
- The drawer subagent can inspect this report with `inspect_render_quality` (capped at 2 inspections per export) and is distinct from the vision-based `critic` subagent — this pass is structural/geometric, not a rendered-image review.

## Email Delivery (Composio Gmail)

The agent can email the generated `out.pdf` via Gmail through the [Composio](https://composio.dev) integration. This is an optional HITL-gated step — the agent pauses for user confirmation before sending.

### Prerequisites

1. Create a free Composio account at [app.composio.dev](https://app.composio.dev) and grab your API key.
2. Add `COMPOSIO_API_KEY=your_key_here` to `backend/.env`.
3. Connect a Gmail account (one-time OAuth flow):

```bash
cd backend
uv run composio add gmail
# Opens browser — complete the Google OAuth consent and authorise the Gmail scope.
```

4. After authorising, find the **connected account ID** that Composio creates:

```bash
cd backend
uv run python setup_gmail_composio.py
```

Copy the Gmail connected account `id` whose status is `ACTIVE` (format: `ca_XXXXXXXXXX`). Do not use an `EXPIRED` connected account ID.

5. Set the API key and active Gmail connected account ID in `backend/.env`:

```bash
COMPOSIO_API_KEY=ak_...
GMAIL_CONNECTED_ACCOUNT_ID=ca_YOUR_ACTIVE_GMAIL_ACCOUNT_ID
```

> **Toolkit version note:** Composio requires a specific toolkit version (not `"latest"`) for manual execution. The current pinned version is `20260612_00` in `backend/src/integrations/email.py`. If you get a "Toolkit version not specified" error after a Composio update, run the snippet below to find the latest version and update the `version=` field:
>
> ```python
> import composio, os; from dotenv import load_dotenv; load_dotenv()
> c = composio.Composio(api_key=os.environ["COMPOSIO_API_KEY"])
> print(c.toolkits.get("GMAIL").meta.version)
> ```

### How It Works

When the user asks to email the report (e.g. *"send the PDF to john@example.com"*):

1. Agent calls `send_email` with `recipient_email`, `subject`, `project_name`, etc.
2. The tool is a HITL gate — the frontend shows an approval card with the recipient and subject.
3. On approval, the tool reads `out.pdf` from the workspace, uploads it to Composio file storage, then sends the email via `GMAIL_SEND_EMAIL`.
4. A professional HTML email with the PDF attached is delivered to the recipient.

### Environment Variable Summary

```bash
# backend/.env
COMPOSIO_API_KEY=your_composio_api_key_here   # required for Gmail + Calendar via Composio
GMAIL_CONNECTED_ACCOUNT_ID=ca_xxxxx           # required for Gmail send_email; must be ACTIVE in Composio
```

### Troubleshooting

| Error                                                | Fix                                                                                                                           |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `COMPOSIO_API_KEY environment variable is not set` | Add `COMPOSIO_API_KEY` to `backend/.env`                                                                                  |
| `no Gmail connected account id`                    | Add `GMAIL_CONNECTED_ACCOUNT_ID` to `backend/.env`                                                                        |
| `No connected account found` or `EXPIRED` account  | Reconnect Gmail in Composio, run `uv run python setup_gmail_composio.py`, then update `GMAIL_CONNECTED_ACCOUNT_ID`       |
| `Toolkit version not specified`                    | Update the `version=` parameter in `backend/src/integrations/email.py` with the latest version from `c.toolkits.get("GMAIL").meta.version` |
| `out.pdf not found in workspace`                   | Call `generate_pdf_report` first to produce `out.pdf` before emailing                                                     |

## Meeting Scheduling (Composio Google Calendar + Google Meet)

The agent can check a connected Google Calendar for free time, let the user pick a slot, and create the client meeting with an auto-generated Google Meet link — all via Composio, no shell access needed. A separate, optional set of read-only Google Meet tools can pull back the transcript/recording/participants of a past call once it's finished.

### Booking flow (Google Calendar)

1. Connect Google Calendar (one-time OAuth flow):

```bash
cd backend
uv run composio add googlecalendar
# Opens browser — complete the Google OAuth consent and authorise the Calendar scope.
```

2. Find the connected account ID the same way as Gmail (`setup_gmail_composio.py`, or `client.client.connected_accounts.list()` filtered on `toolkit.slug == "googlecalendar"` and `status == "ACTIVE"`), then set it in `backend/.env`:

```bash
GOOGLE_CALENDAR_CONNECTED_ACCOUNT_ID=ca_YOUR_ACTIVE_CALENDAR_ACCOUNT_ID
```

3. When the user asks to schedule a call with a client, the agent calls `propose_meeting_slots` (queries `GOOGLECALENDAR_FIND_FREE_SLOTS`, then pauses so the frontend shows a slot picker), then `create_client_meeting` (calls `GOOGLECALENDAR_CREATE_EVENT` with `create_meeting_room=true` — this is what generates the Google Meet link — and pauses as a HITL approval gate before the event is actually created). The confirmation card and chat both surface the resulting calendar link and Meet link.

### Read-only Google Meet tools (past meetings)

Google Meet is a separate Composio toolkit from Calendar and needs its own connected account:

```bash
cd backend
uv run composio add googlemeet
# Requires the meetings.space.created scope; readonly access to conference
# records/transcripts/recordings/participants is granted alongside it.
```

Find the connected account ID (same lookup pattern, filtering on `toolkit.slug == "googlemeet"`) and set it in `backend/.env`:

```bash
GOOGLE_MEET_CONNECTED_ACCOUNT_ID=ca_YOUR_ACTIVE_MEET_ACCOUNT_ID
```

Once set, the agent can use, in order:

- `list_meeting_records` (`GOOGLEMEET_LIST_CONFERENCE_RECORDS`) — find a finished call and get its conference record name.
- `get_meeting_transcript` (`GOOGLEMEET_GET_TRANSCRIPTS_BY_CONFERENCE_RECORD_ID` + `GOOGLEMEET_LIST_TRANSCRIPT_ENTRIES`) — full transcript, for summarizing into requirements/WBS notes.
- `get_meeting_recordings` (`GOOGLEMEET_GET_RECORDINGS_BY_CONFERENCE_RECORD_ID`) — Drive links to the recording, if enabled.
- `list_meeting_participants` (`GOOGLEMEET_LIST_PARTICIPANTS`) — who actually attended.

These are read-only lookups (no HITL gate). Transcript/recording data requires transcription/recording to have been turned on for that call, and a Workspace edition that supports it (Business Standard/Plus, Enterprise, Education Plus) — the tools return a plain "not available" message otherwise, they don't error.

> **Toolkit version note:** like Gmail, both toolkits are pinned to a specific version (not `"latest"`) in `backend/src/integrations/calendar.py` and `backend/src/integrations/meet.py`. Refresh the same way as the Gmail note above, substituting `c.toolkits.get("GOOGLECALENDAR").meta.version` / `c.toolkits.get("GOOGLEMEET").meta.version`.

### Environment Variable Summary

```bash
# backend/.env
GOOGLE_CALENDAR_CONNECTED_ACCOUNT_ID=ca_xxxxx  # required for propose_meeting_slots / create_client_meeting
GOOGLE_MEET_CONNECTED_ACCOUNT_ID=ca_xxxxx      # required only for the read-only Meet lookup tools
```

To verify the whole Composio setup (Gmail + Calendar + Meet) actually works end-to-end,
alongside diagram/PDF/WBS/PPT generation, run the live full-pipeline smoke test:
`cd backend && uv run python -m evals.e2e.run_full_flow` — see `backend/evals/README.md`.
It sends a real email and books a real calendar event/Meet, so run it deliberately,
not on every commit.

## LangGraph Details

Deep Agents compiles the agent into a LangGraph graph. The application uses LangGraph for streamed execution, thread-scoped checkpoints, human approval interrupts, and run resumption.

### Graph Runtime

- Agent builder: `create_deep_agent(...)` in `backend/src/diagram_mcp/agent.py`.
- Compiled graph entrypoint: `AGENT.astream(...)` in `backend/src/diagram_mcp/server.py`.
- Thread identity: `configurable.thread_id`.
- Recursion limit: `RECURSION_LIMIT = 160`.
- Run metadata: `run_name="diagram-agent"`, tag `diagram-agent`, metadata `thread_id` and `run_id`.

Each browser conversation gets its own LangGraph `thread_id`, so checkpointed state, pending approvals, and message history stay isolated per conversation.

### Streaming Modes

The server streams the graph with:

```python
stream_mode=["messages", "updates", "custom"]
```

- `messages`: assistant tokens and model messages.
- `updates`: graph node/tool updates, including tool calls and HITL events.
- `custom`: subagent activity forwarded through `get_stream_writer()`.

The FastAPI server converts these LangGraph stream events into AG-UI/SSE events consumed by the React frontend.

### Checkpointing and Store

When `DATABASE_URL` is set, LangGraph persistence uses Postgres:

- `AsyncPostgresSaver`: durable checkpointer for graph state and pending interrupts.
- `AsyncPostgresStore`: durable store for cross-run data.
- Shared `AsyncConnectionPool`: also reused by the app's conversation metadata table.

When `DATABASE_URL` is not set, local development falls back to:

- `MemorySaver`
- `InMemoryStore`

In-memory mode is useful for quick testing, but conversations and pending approval state are lost after server restart.

### Human Approval Interrupts

The main graph configures `interrupt_on` for these tools:

```python
interrupt_on = {
    "propose_tech_stack": {"allowed_decisions": ["approve", "reject"]},
    "propose_blueprint": {"allowed_decisions": ["approve", "reject"]},
    "finalize_diagram": {"allowed_decisions": ["approve", "reject"]},
    "generate_pdf_report": {"allowed_decisions": ["approve", "reject"]},
}
```

When one of these tools is reached, LangGraph pauses the run and stores the pending interrupt in the checkpoint. The server reads that pending interrupt with `AGENT.aget_state(config)`, maps it into a frontend approval card, and waits for user input.

### Resume Flow

When the user approves or rejects a card, the frontend sends a tool response back to `/agui`. The server resumes the same LangGraph thread with:

```python
Command(resume={"decisions": [decision]})
```

- Approve: graph continues to the next stage.
- Reject: graph receives user feedback and revises the current proposal or diagram.

Because the resume uses the same `thread_id`, LangGraph continues from the exact paused checkpoint instead of starting a new run.

### Subagent Streaming

Drawer and critic subagents are precompiled Deep Agents. Their internal graph events are wrapped by `_StreamingSubAgentRunnable`, which forwards subagent tool activity to the outer graph stream through `get_stream_writer()`.

This makes nested work visible in the UI, including:

- icon search
- logo fetch
- diagram rendering
- draw.io export
- critic inspection

### Conversation Metadata

LangGraph owns graph checkpoints and store tables. The app also keeps a separate `conversations` table in `backend/src/diagram_mcp/conversations.py` for UI-friendly metadata:

- conversation name
- last message
- chat messages
- UI state snapshot
- approval outcomes

This split keeps LangGraph state durable while still allowing the frontend to list, rename, delete, and restore conversations.

## Repository Layout

```text
diagram_code_agent/
+-- backend/
|   +-- pyproject.toml
|   +-- Dockerfile
|   +-- .env.example
|   +-- src/diagram_mcp/
|   |   +-- server.py              # FastAPI AG-UI server, upload API, conversation API
|   |   +-- agent.py               # Deep Agent factory, model, persistence
|   |   +-- tools.py               # diagram render/export/icon tools
|   |   +-- backends.py            # filesystem backend and resource paths
|   |   +-- gv_to_drawio.py        # Graphviz DOT to draw.io exporter
|   |   +-- logo_fetch.py          # logo/icon resolver
|   |   +-- requirements_reader.py # upload parsing
|   +-- skills/                    # Deep Agent skills
|   +-- evals/                     # diagram evaluation harness
|   +-- scripts/
+-- frontend/
|   +-- package.json
|   +-- Dockerfile
|   +-- .env.example
|   +-- src/
|       +-- App.tsx
|       +-- hooks/
|       +-- components/
+-- resources/
|   +-- icons/
|   +-- icons_manifest.json
|   +-- node_catalog.json
+-- example/                        # sample generated diagrams (.png + .drawio) used in this README
+-- open-swe/                      # bundled/reference Open SWE project
+-- docker-compose.yml
+-- README.md
+-- README.MD
+-- .gitignore
```

## Prerequisites

- Python 3.11 or newer.
- Node.js 18 or newer.
- Graphviz installed on the host when running backend outside Docker.
- At least one LLM API key: `OPENAI_API_KEY` (OpenAI) or `MIMO_API_KEY` (Mimo).
- `TAVILY_API_KEY` for live web search at the tech-stack step (optional but recommended).
- Docker and Docker Compose for easiest full-stack run.

Install Graphviz locally:

```bash
# Debian / Ubuntu
sudo apt-get update
sudo apt-get install -y graphviz

# macOS
brew install graphviz
```

Verify:

```bash
dot -V
```

## Run With Docker Compose

```bash
cp backend/.env.example backend/.env
# edit backend/.env and set OPENAI_API_KEY

docker compose up --build
```

Open:

- Frontend: `http://localhost:5173`
- Backend health: `http://localhost:8001/health`

Docker Compose starts:

- `postgres`: session/checkpoint database.
- `backend`: FastAPI AG-UI server on port `8001`.
- `frontend`: nginx-served Vite build on port `5173`.

## Run Locally

### Backend

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env
# edit .env and set OPENAI_API_KEY

diagram-agent-server
```

Alternative:

```bash
PYTHONPATH=src python -m diagram_mcp.server
```

Health check:

```bash
curl http://localhost:8001/health
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open `http://localhost:5173`.

## Environment Variables

Backend `backend/.env`:

```bash
# --- AI model keys (at least one required) ---
OPENAI_API_KEY=sk-...                    # OpenAI GPT models (required if using OpenAI)
MIMO_API_KEY=sk-sl2w...                  # Mimo model provider (required if using Mimo)
ANTHROPIC_API_KEY=sk-ant-...             # Anthropic Claude models (optional)

# --- Web search (optional but recommended) ---
TAVILY_API_KEY=tvly-dev-...              # Tavily — live fact-checking at tech-stack step (≤3 calls/session)

# --- Observability (optional) ---
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=diagram-agent

# --- Integrations (optional) ---
COMPOSIO_API_KEY=ak_...                  # Composio - required for Gmail email delivery and Google Calendar
GMAIL_CONNECTED_ACCOUNT_ID=ca_...        # Composio Gmail connected account ID; must be ACTIVE
GOOGLE_CALENDAR_CONNECTED_ACCOUNT_ID=ca_... # Composio Google Calendar connected account ID; must be ACTIVE

# --- Server config (optional) ---
DIAGRAM_AGENT_PORT=8001
DATABASE_URL=postgresql://diagram:diagram@localhost:5432/diagram
ALLOWED_ORIGINS=http://localhost:5173

# --- Model overrides (optional) ---
PLAN_MODEL=gpt-4.1-mini                  # Model for the quick plan step; default gpt-4.1-mini
```

Frontend `frontend/.env`:

```bash
VITE_BACKEND_URL=http://localhost:8001
```

`DATABASE_URL` is optional for local development. Without it, backend uses in-memory sessions that disappear after restart.

## Main Backend Endpoints

- `GET /health`: service health.
- `POST /agui`: AG-UI streaming endpoint.
- `POST /upload`: parse uploaded requirements documents.
- `GET /conversations`: list conversations.
- `POST /conversations`: create conversation.
- `GET /conversations/{thread_id}/history`: restore conversation state.

## Generated Files

Runtime artifacts are created under `backend/agent_space/`, including uploaded docs, memory files, workspace files, rendered PNGs, DOT files, `.drawio` exports, and optional `out.pdf` reports. This folder is ignored by Git.

## Troubleshooting

- `dot: command not found`: install Graphviz.
- `401` or model auth error: check `OPENAI_API_KEY` in `backend/.env`.
- Frontend cannot reach backend: check `VITE_BACKEND_URL`, backend port `8001`, and CORS `ALLOWED_ORIGINS`.
- Conversations disappear after restart: configure `DATABASE_URL` or run with Docker Compose.
- Missing Python package: run `pip install -e .` from `backend/`.
- Missing frontend package: run `npm install` from `frontend/`.

## Notes

Root `README.md` already existed in this repository with more detailed operational notes. This `README.MD` was generated from the scanned project structure and current configuration files.
