"""AG-UI server for the staged diagram deep agent (port 8001).

ONE deep agent runs a staged, human-approved flow:
  understand requirements (+ uploaded docs) → propose_tech_stack [HITL] →
  propose_blueprint [HITL] → render diagram → finalize_diagram [HITL] → done.

The three `propose_*`/`finalize_*` tools are gated with deepagents `interrupt_on`.
This server is the translation layer between the deepagents HITL protocol and the
frontend cards:
  - it streams assistant text (TEXT_MESSAGE_*),
  - on each gate it reads the pending interrupt (a HITLRequest) and emits a
    TOOL_CALL_* "card" the frontend renders (techstack_approval / blueprint_approval
    / result_review),
  - it turns the frontend's approve/reject reply into a `Command(resume=...)`,
  - when the run finishes it emits a STATE_SNAPSHOT with the diagram artifacts.

`POST /upload` extracts text from PDF/DOCX/MD/TXT so requirements can be attached.

Run:  diagram-agent-server   (or  python -m diagram_mcp.server)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

load_dotenv()
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from .agent import RECURSION_LIMIT, build_agent, make_persistence
from . import conversations as conv_db

# The compiled agent is built in the FastAPI lifespan (so the Postgres connection
# pool is opened/closed with the app) and stored here for the request handlers.
AGENT = None
from .backends import AGENT_SPACE, WORKSPACE
from .reporting import DEFAULT_REPORT_SECTIONS, record_report_step
from .requirements_reader import IMAGE_EXT, parse_file
from .tools import GATE_TOOL_NAMES, clear_stage_markers

_DEFAULT_TZ = "Asia/Ho_Chi_Minh"

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("diagram-agent")
# Silence the noisy HTTP client logs — we log the agent's real actions instead.
for _noisy in ("httpx", "httpcore", "openai", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def _configure_tracing() -> bool:
    """Enable LangSmith tracing from env (LANGSMITH_TRACING / legacy LANGCHAIN_TRACING_V2)."""
    on = os.getenv("LANGSMITH_TRACING", os.getenv("LANGCHAIN_TRACING_V2", "")).lower() in ("1", "true", "yes")
    if on:
        # langchain/langgraph read these at run time; default a project name.
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ.setdefault("LANGSMITH_PROJECT", "diagram-code-agent")
        has_key = bool(os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY"))
        logger.info(
            "LangSmith tracing ON  project=%s  api_key=%s",
            os.getenv("LANGSMITH_PROJECT"), "set" if has_key else "MISSING (set LANGSMITH_API_KEY)",
        )
    else:
        logger.info("LangSmith tracing OFF (set LANGSMITH_TRACING=true + LANGSMITH_API_KEY to enable)")
    return on


TRACING_ON = _configure_tracing()

UPLOADS_DIR = AGENT_SPACE / "uploads"

# Human-friendly labels for what the agent is doing (server log + UI activity).
_TOOL_LABELS = {
    "analyze_architecture_requirements": "Analyzing architecture requirements",
    "propose_diagram_brief": "Preparing the diagram brief",
    "propose_tech_stack": "Proposing the technology stack",
    "propose_blueprint": "Designing the architecture blueprint",
    "render_diagram": "Rendering the diagram",
    "export_drawio": "Exporting the editable .drawio",
    "list_saved_diagrams": "Listing saved diagram sessions",
    "resolve_icons": "Resolving icon plan",
    "search_diagrams_nodes": "Searching built-in diagram nodes",
    "search_icons": "Searching the icon library",
    "fetch_logo": "Fetching a logo",
    "audit_diagram_code": "Auditing diagram code",
    "inspect_diagram": "Reviewing the rendered diagram",
    "submit_critique": "Recording the diagram review",
    "finalize_diagram": "Finalizing the diagram",
    "generate_pdf_report": "Generating the PDF report",
    "send_architecture_report_email": "Sending the architecture report email",
    "write_todos": "Planning the steps",
    "task": "Delegating to subagent",
    "ls": "Listing files",
    "read_file": "Reading a file",
    "write_file": "Writing a file",
    "edit_file": "Editing a file",
    "glob": "Searching for files",
    "grep": "Searching file contents",
}

# Maps tool name → which subagent owns it (for activity attribution).
_TOOL_TO_SUBAGENT: dict[str, str] = {
    "search_diagrams_nodes": "icon_resolver",
    "search_icons": "icon_resolver",
    "resolve_icons": "icon_resolver",
    "fetch_logo": "icon_resolver",
    "audit_diagram_code": "drawer",
    "render_diagram": "drawer",
    "export_drawio": "drawer",
    "inspect_diagram": "critic",
    "submit_critique": "critic",
}


def _label(tool: str) -> str:
    return _TOOL_LABELS.get(tool, f"Running {tool}")


def _compact_json(value, *, limit: int = 260) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except Exception:
        text = str(value)
    text = " ".join(text.split())
    return text[:limit] + ("..." if len(text) > limit else "")


def _tool_detail(tool: str, args: dict | None, *, limit: int = 260) -> str:
    """Summarize tool input for UI logs without dumping huge code/prompts."""
    if not isinstance(args, dict) or not args:
        return ""
    if tool == "task":
        sa = args.get("subagent_type") or args.get("subagent") or args.get("name") or "unknown"
        desc = " ".join(str(args.get("description") or args.get("instruction") or args.get("prompt") or "").split())
        return f"{sa}: {desc[:180]}{'...' if len(desc) > 180 else ''}"
    if tool == "render_diagram":
        code = str(args.get("code") or "")
        return f"diagram.py code={len(code)} chars"
    if tool == "audit_diagram_code":
        code = str(args.get("code") or "")
        return f"diagram.py code={len(code)} chars"
    if tool == "search_icons":
        provider = args.get("provider")
        return f"query={args.get('query', '')}" + (f", provider={provider}" if provider else "")
    if tool == "search_diagrams_nodes":
        provider = args.get("provider")
        category = args.get("category")
        bits = [f"query={args.get('query', '')}"]
        if provider:
            bits.append(f"provider={provider}")
        if category:
            bits.append(f"category={category}")
        return ", ".join(bits)
    if tool == "analyze_architecture_requirements":
        req = " ".join(str(args.get("requirements", "")).split())
        provider = args.get("provider_preference")
        suffix = f", provider={provider}" if provider else ""
        return f"requirements={req[:160]}{'...' if len(req) > 160 else ''}{suffix}"
    if tool == "resolve_icons":
        icons = args.get("icons") or []
        if isinstance(icons, list):
            labels = [str(x.get("label", "")) for x in icons if isinstance(x, dict)]
            return f"{len(icons)} icons: {', '.join([x for x in labels if x][:8])}"
    if tool == "fetch_logo":
        return f"name={args.get('name', '')}"
    if tool == "propose_blueprint":
        bp = args.get("blueprint") or {}
        if isinstance(bp, dict):
            return (
                f"{bp.get('audience', 'client')}/{bp.get('detail_level', 'architecture')} "
                f"style={bp.get('presentation_style', 'diagram')}, "
                f"pattern={bp.get('pattern', '')}, nodes={len(bp.get('nodes') or [])}, "
                f"clusters={len(bp.get('clusters') or [])}, edges={len(bp.get('edges') or [])}"
            )
    if tool == "propose_diagram_brief":
        brief = args.get("brief") or {}
        if isinstance(brief, dict):
            return (
                f"objective={str(brief.get('objective', ''))[:80]}, "
                f"functional={len(brief.get('functional_requirements') or [])}, "
                f"nonfunctional={len(brief.get('non_functional_requirements') or [])}, "
                f"layout={len(brief.get('layout_constraints') or [])}"
            )
    if tool == "propose_tech_stack":
        stack = args.get("tech_stack") or []
        if isinstance(stack, list):
            layers = [str(x.get("layer", "")) for x in stack if isinstance(x, dict)]
            return f"{len(stack)} layers: {', '.join([x for x in layers if x][:8])}"
    if tool == "generate_pdf_report":
        sections = args.get("include_sections") or DEFAULT_REPORT_SECTIONS
        return f"sections={', '.join(map(str, sections))}"
    if tool == "submit_critique":
        findings = args.get("findings") or []
        if isinstance(findings, list):
            return f"{len(findings)} finding(s)"
    return _compact_json(args, limit=limit)


def _tool_output_detail(content, *, limit: int = 320) -> str:
    text = " ".join(_text_of(content).split())
    return text[:limit] + ("..." if len(text) > limit else "")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the (Postgres) session store, build the agent, close the pool on exit."""
    global AGENT
    checkpointer, store, aclose, pool = await make_persistence()
    AGENT = build_agent(checkpointer=checkpointer, store=store)
    app.state.aclose = aclose
    app.state.pool = pool          # shared raw pool for conversations table
    await conv_db.setup(pool)      # idempotent CREATE TABLE IF NOT EXISTS
    logger.info("Agent ready.")
    try:
        yield
    finally:
        await aclose()
        logger.info("Session pool closed.")


app = FastAPI(title="Diagram Agent", version="3.0.0", lifespan=lifespan)
# CORS: lock down to ALLOWED_ORIGINS (comma-separated) in production; "*" for dev.
_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok", "agent": "diagram_agent"}


# ---------------------------------------------------------------------------
# Conversation management
# ---------------------------------------------------------------------------

class _ConvCreate(BaseModel):
    thread_id: str | None = None
    name: str = "Untitled"

class _ConvRename(BaseModel):
    name: str


@app.get("/conversations", tags=["conversations"])
async def list_conversations(request: Request):
    return await conv_db.list_all(request.app.state.pool)


@app.post("/conversations", tags=["conversations"])
async def create_conversation(body: _ConvCreate, request: Request):
    tid = body.thread_id or f"thread-{uuid.uuid4().hex[:12]}"
    return await conv_db.create(request.app.state.pool, tid, body.name)


@app.patch("/conversations/{thread_id}", tags=["conversations"])
async def rename_conversation(thread_id: str, body: _ConvRename, request: Request):
    await conv_db.rename(request.app.state.pool, thread_id, body.name)
    return {"ok": True}


@app.delete("/conversations/{thread_id}", tags=["conversations"])
async def delete_conversation(thread_id: str, request: Request):
    await conv_db.delete(request.app.state.pool, thread_id)
    return {"ok": True}


@app.get("/conversations/{thread_id}/history", tags=["conversations"])
async def get_conversation_history(thread_id: str, request: Request):
    hist = await conv_db.get_history(request.app.state.pool, thread_id)
    if hist is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return hist


# ---------------------------------------------------------------------------
# Upload — extract requirement documents to text
# ---------------------------------------------------------------------------

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex[:12]
    raw_path = UPLOADS_DIR / f"{file_id}_{file.filename}"
    raw_path.write_bytes(await file.read())

    doc = parse_file(raw_path)
    if doc.kind == "image" and doc.ok:
        # Store image metadata as JSON so _attached_images() can find it.
        import json as _json
        (UPLOADS_DIR / f"{file_id}.img.json").write_text(
            _json.dumps({"b64": doc.image_b64, "mime": doc.image_mime, "filename": file.filename}),
            encoding="utf-8",
        )
        return {
            "file_id": file_id,
            "filename": file.filename,
            "kind": "image",
            "char_count": 0,
            "preview": f"[reference image: {file.filename}]",
            "error": doc.error,
        }
    text = doc.text if doc.ok else ""
    (UPLOADS_DIR / f"{file_id}.md").write_text(text, encoding="utf-8")
    return {
        "file_id": file_id,
        "filename": file.filename,
        "kind": doc.kind,
        "char_count": len(text),
        "preview": text[:300],
        "error": doc.error,
    }


def _attached_text(file_ids: list[str]) -> str:
    parts = []
    for fid in file_ids or []:
        p = UPLOADS_DIR / f"{fid}.md"
        if p.exists():
            t = p.read_text(encoding="utf-8", errors="replace").strip()
            if t:
                parts.append(t)
    return "\n\n---\n\n".join(parts)


def _attached_images(file_ids: list[str]) -> list[dict]:
    """Return image content blocks for any uploaded reference images."""
    blocks = []
    for fid in file_ids or []:
        p = UPLOADS_DIR / f"{fid}.img.json"
        if p.exists():
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
                b64 = meta.get("b64", "")
                mime = meta.get("mime", "image/png")
                fname = meta.get("filename", "reference")
                if b64:
                    blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                        "filename": fname,
                    })
            except Exception:  # noqa: BLE001
                pass
    return blocks


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for p in content:
            if isinstance(p, str):
                out.append(p)
            elif isinstance(p, dict) and ("text" in p or p.get("type") in ("text", "output_text")):
                out.append(p.get("text", ""))
        return "".join(out)
    return ""


def _last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return _text_of(m.get("content", ""))
    return ""


def _last_tool_msg(messages: list[dict]) -> dict | None:
    """Return the last message only when the client is resolving a HITL gate."""
    if messages and messages[-1].get("role") == "tool":
        return messages[-1]
    return None


def _is_pdf_followup(text: str) -> bool:
    """Detect a follow-up asking to package the current diagram as a PDF report."""
    normalized = " ".join(str(text or "").lower().split())
    return any(
        phrase in normalized
        for phrase in (
            "pdf",
            "report",
            "document",
            "doc",
            "tạo pdf",
            "tao pdf",
            "xuất pdf",
            "xuat pdf",
            "tạo báo cáo",
            "tao bao cao",
        )
    )


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception:  # noqa: BLE001
        return None


async def _pending_interrupt(config: dict):
    """Return the pending HITLRequest value, or None."""
    try:
        st = await AGENT.aget_state(config)
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_state failed: %s", exc)
        return None
    for task in getattr(st, "tasks", None) or []:
        for intr in getattr(task, "interrupts", None) or []:
            return getattr(intr, "value", intr)
    for intr in getattr(st, "interrupts", None) or []:
        return getattr(intr, "value", intr)
    return None


def _pending_action_name(val) -> str | None:
    if isinstance(val, dict):
        ars = val.get("action_requests") or []
        if ars:
            return ars[0].get("name")
        # manual interrupt() from propose_meeting_slots
        if val.get("type") == "slot_picker":
            return "propose_meeting_slots"
    return None


def _coerce_list(val) -> list:
    """Coerce an array-typed field into a list.

    Some models (e.g. mimo) emit array-typed fields as plain objects with
    numeric string keys ({"0": ..., "1": ...}) instead of JSON arrays. Calling
    .map() on those objects crashes the frontend, so coerce them here. A dict
    becomes its values; a list is kept; anything else (None, scalar) → [].
    """
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return list(val.values())
    return []


# Array-typed fields shared by blueprint / diagram_brief / architecture_analysis.
_BRIEF_ARRAY_FIELDS = ("analysis_signals", "stakeholders", "functional_requirements",
                       "non_functional_requirements", "layout_constraints", "assumptions")


def _coerce_brief(d) -> dict:
    """Ensure list-typed fields of a brief/analysis dict are always lists."""
    if not isinstance(d, dict):
        return d
    result = dict(d)
    for field in _BRIEF_ARRAY_FIELDS:
        if field in result:
            result[field] = _coerce_list(result[field])
    return result


# Array-typed fields inside the tech-stack `assumptions` object.
_ASSUMPTION_ARRAY_FIELDS = ("confirm_with_customer", "compliance")


def _coerce_assumptions(a):
    """Ensure list-typed fields of the assumptions object are always lists."""
    if not isinstance(a, dict):
        return a
    result = dict(a)
    for field in _ASSUMPTION_ARRAY_FIELDS:
        if field in result:
            result[field] = _coerce_list(result[field])
    return result


def _normalize_blueprint(bp) -> dict:
    """Ensure array fields in a blueprint are always lists.

    Some models (e.g. mimo) may return array-typed fields as plain objects
    with numeric string keys ({"0": {...}, "1": {...}}) instead of lists.
    Calling .map() on those objects crashes the frontend.
    """
    if not isinstance(bp, dict):
        return bp or {}
    result = dict(bp)
    _ARRAY_FIELDS = ("nodes", "clusters", "edges", "key_decisions", "nfr_mapping",
                     "analysis_signals", "stakeholders", "functional_requirements",
                     "non_functional_requirements", "layout_constraints", "assumptions")
    for field in _ARRAY_FIELDS:
        val = result.get(field)
        if isinstance(val, dict):
            result[field] = list(val.values())
        elif val is None:
            result[field] = []
    return result


def _normalize_tech_stack(ts) -> dict:
    """Normalize the model's tech_stack into {layer: {choice, rationale, alternatives, ...}}.

    Tolerates:
    - list of {layer, choice, rationale, ...} (tool call from LLM)
    - dict keyed by layer (older shape)
    - wrapped dict {layers: {...}, assumptions: ..., ...} (new shape stored in workspace)
    """
    _LAYER_FIELDS = ("choice", "rationale", "cost_tier", "decision_criteria", "alternatives",
                     "estimated_monthly_cost_usd", "capacity_sizing", "performance_target", "risks")
    out: dict = {}

    # Unwrap new wrapped shape from workspace replay
    if isinstance(ts, dict) and "layers" in ts:
        ts = ts["layers"]

    if isinstance(ts, list):
        for item in ts:
            if isinstance(item, dict) and item.get("layer"):
                layer_data = {f: item.get(f) for f in _LAYER_FIELDS}
                layer_data["alternatives"] = _coerce_list(layer_data.get("alternatives"))
                layer_data["risks"] = _coerce_list(layer_data.get("risks"))
                out[item["layer"]] = layer_data
    elif isinstance(ts, dict):
        for layer, info in ts.items():
            if isinstance(info, dict):
                layer_data = {f: info.get(f) for f in _LAYER_FIELDS}
                layer_data["alternatives"] = _coerce_list(layer_data.get("alternatives"))
                layer_data["risks"] = _coerce_list(layer_data.get("risks"))
                out[layer] = layer_data
            else:
                # flattened/degenerate value (e.g. a bare string) — show it as the choice
                out[layer] = {"choice": str(info), "rationale": "", "cost_tier": None,
                              "decision_criteria": None, "alternatives": [],
                              "estimated_monthly_cost_usd": None, "capacity_sizing": "",
                              "performance_target": "", "risks": []}
    return out


def _card_for(val, summary: str):
    """Translate an interrupt value → (card_data, current_step, state_delta).

    Handles two interrupt shapes:
      • interrupt_on tools  → val has {"action_requests": [{"name": ..., "args": ...}]}
      • manual interrupt()  → val is the raw dict passed to interrupt(), e.g.
                              {"type": "slot_picker", "slots": [...], ...}
    """
    # --- manual interrupt() from propose_meeting_slots ---
    if isinstance(val, dict) and val.get("type") == "slot_picker":
        return (
            {
                "type": "slot_picker",
                "question": "Pick a time that works for the client meeting:",
                "slots": val.get("slots", []),
                "duration_minutes": val.get("duration_minutes", 60),
                "timezone": val.get("timezone", _DEFAULT_TZ),
                "context": val.get("context", ""),
            },
            "awaiting_slot_selection",
            {},
        )

    ars = (val or {}).get("action_requests") or [{}]
    name = ars[0].get("name")
    args = ars[0].get("args") or {}
    if name == "propose_tech_stack":
        ts = _normalize_tech_stack(args.get("tech_stack"))
        scaling_roadmap = _coerce_list(args.get("scaling_roadmap"))
        assumptions = _coerce_assumptions(args.get("assumptions"))
        card_data = {
            "type": "techstack_approval",
            "tech_stack": ts,
            "question": "Review the recommended tech stack and its sizing assumptions. Approve, or reject with the changes you want.",
            "assumptions": assumptions,
            "scaling_roadmap": scaling_roadmap,
            "estimated_total_monthly_cost_usd": args.get("estimated_total_monthly_cost_usd"),
        }
        state_delta = {
            "tech_stack": ts,
            "tech_assumptions": assumptions,
            "tech_scaling_roadmap": scaling_roadmap,
            "tech_total_cost": args.get("estimated_total_monthly_cost_usd"),
        }
        return (card_data, "awaiting_techstack", state_delta)
    if name == "propose_blueprint":
        bp = _normalize_blueprint(args.get("blueprint", {}))
        return (
            {"type": "blueprint_approval", "blueprint": bp,
             "question": "Review the architecture blueprint. Approve, or request changes."},
            "awaiting_blueprint", {"blueprint": bp},
        )
    if name == "finalize_diagram":
        return (
            {"type": "result_review", "summary": summary,
             "question": "Is the diagram good? Approve to finish, or describe the changes you want."},
            "reviewing", {},
        )
    if name == "generate_pdf_report":
        sections = args.get("include_sections") or DEFAULT_REPORT_SECTIONS
        missing = [s for s in DEFAULT_REPORT_SECTIONS if s not in sections]
        return (
            {
                "type": "pdf_report_approval",
                "question": "Generate the PDF report with these settings?",
                "title": args.get("title", ""),
                "subtitle": args.get("subtitle", ""),
                "brand": args.get("brand", ""),
                "include_sections": sections,
                "missing_sections": missing,
            },
            "awaiting_pdf_report",
            {},
        )
    if name == "send_architecture_report_email":
        return (
            {
                "type": "email_approval",
                "question": f"Send the architecture report PDF to {args.get('recipient_email', '')}?",
                "recipient_email": args.get("recipient_email", ""),
                "subject": args.get("subject", ""),
                "project_name": args.get("project_name", ""),
                "subtitle": args.get("subtitle", ""),
                "recipient_name": args.get("recipient_name", "Team"),
            },
            "awaiting_email_approval",
            {},
        )
    if name == "create_client_meeting":
        start_iso = args.get("start_datetime", "")
        end_iso = args.get("end_datetime", "")
        tz_name = args.get("timezone", "Asia/Ho_Chi_Minh")
        # Format human-readable date/time for the card
        display_start = start_iso
        display_end = end_iso
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            _tz = ZoneInfo(tz_name)
            _s = datetime.fromisoformat(start_iso).astimezone(_tz)
            _e = datetime.fromisoformat(end_iso).astimezone(_tz)
            display_start = _s.strftime("%A, %d %b %Y  %H:%M")
            display_end = _e.strftime("%H:%M")
            duration_min = int((_e - _s).total_seconds() / 60)
        except Exception:
            duration_min = 0
        return (
            {
                "type": "meeting_approval",
                "question": f"Schedule a meeting with {args.get('attendee_email', '')}?",
                "title": args.get("title", ""),
                "start_datetime": start_iso,
                "end_datetime": end_iso,
                "display_start": display_start,
                "display_end": display_end,
                "duration_minutes": duration_min,
                "attendee_email": args.get("attendee_email", ""),
                "attendee_name": args.get("attendee_name", "Client"),
                "description": args.get("description", ""),
                "add_google_meet": args.get("add_google_meet", True),
                "timezone": tz_name,
            },
            "awaiting_meeting_approval",
            {},
        )
    return None, None, {}


def _decision_from_payload(payload: dict, pending_name: str | None) -> dict:
    if pending_name == "finalize_diagram":
        ok = bool(payload.get("satisfied", True))
        msg = payload.get("feedback")
    else:
        ok = bool(payload.get("approved", False))
        msg = payload.get("modifications")
    if ok:
        decision: dict = {"type": "approve"}
        # Pass through selected_slot for the slot-picker interrupt
        if "selected_slot" in payload:
            decision["selected_slot"] = payload["selected_slot"]
        return decision
    return {"type": "reject", "message": msg or "Please revise based on the user's feedback."}


async def _summary_and_logs(config: dict) -> tuple[str, list]:
    summary = ""
    logs: list[dict] = []
    try:
        state = await AGENT.aget_state(config)
        messages = state.values.get("messages", [])
    except Exception:  # noqa: BLE001
        return summary, logs
    turn = 0
    pending: dict[str, dict] = {}
    for m in messages:
        if isinstance(m, AIMessage):
            turn += 1
            logs.append({"t": 0, "type": "llm", "turn": turn})
            for tc in (m.tool_calls or []):
                args = tc.get("args", {})
                name = tc.get("name", "tool")
                entry = {
                    "t": 0,
                    "type": "tool_start",
                    "tool": name,
                    "label": _label(name),
                    "input": _tool_detail(name, args, limit=320),
                }
                logs.append(entry)
                pending[tc.get("id", "")] = entry
            txt = _text_of(m.content).strip()
            if txt:
                summary = txt
        elif isinstance(m, ToolMessage):
            entry = pending.get(getattr(m, "tool_call_id", ""))
            if entry is not None:
                out = _text_of(m.content)
                entry["output"] = _tool_output_detail(out)
                if getattr(m, "status", None) == "error":
                    entry["error"] = entry.get("output", "error")
    return summary, logs


def _artifacts() -> dict:
    """Read the diagram artifacts currently in the workspace (if any)."""
    out: dict = {}
    png = WORKSPACE / "out.png"
    if png.exists():
        out["png_base64"] = base64.b64encode(png.read_bytes()).decode("ascii")
    drawio = WORKSPACE / "out.drawio"
    if drawio.exists():
        out["drawio"] = drawio.read_text(encoding="utf-8", errors="replace")
    code = WORKSPACE / "diagram.py"
    if code.exists():
        out["code"] = code.read_text(encoding="utf-8", errors="replace")
    pdf = WORKSPACE / "out.pdf"
    if pdf.exists():
        out["pdf_base64"] = base64.b64encode(pdf.read_bytes()).decode("ascii")
    return out


def _stage_artifacts() -> dict:
    """Read structured planning artifacts currently in the workspace."""
    out: dict = {}
    analysis = _read_json(WORKSPACE / "architecture_analysis.json")
    brief = _read_json(WORKSPACE / "diagram_brief.json")
    ts = _read_json(WORKSPACE / "tech_stack.json")
    bp = _read_json(WORKSPACE / "blueprint.json")
    tool_summary = _read_json(WORKSPACE / "tool_budget_summary.json")
    if analysis:
        out["architecture_analysis"] = _coerce_brief(analysis)
    if brief:
        out["diagram_brief"] = _coerce_brief(brief)
    if ts:
        out["tech_stack"] = _normalize_tech_stack(ts)
    if bp:
        out["blueprint"] = _normalize_blueprint(bp)
    if tool_summary:
        out["tool_budget_summary"] = tool_summary
    return out

def _run_metrics(logs: list[dict]) -> dict:
    tool_counts: dict[str, int] = {}
    model_calls = 0
    for item in logs:
        if item.get("type") == "llm":
            model_calls += 1
        elif item.get("type") == "tool_start":
            tool = item.get("tool") or "tool"
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
    out = {"model_calls": model_calls, "tool_counts": tool_counts}
    tool_summary = _read_json(WORKSPACE / "tool_budget_summary.json")
    if tool_summary:
        out["tool_budget_summary"] = tool_summary
    return out


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


# ---------------------------------------------------------------------------
# AG-UI endpoint
# ---------------------------------------------------------------------------

@app.post("/agui")
async def agui_endpoint(request: Request):
    body = await request.json()
    thread_id = body.get("threadId", "thread-default")
    run_id = body.get("runId", "run-1")
    messages = body.get("messages", [])
    file_ids = body.get("file_ids", [])

    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": RECURSION_LIMIT,
        "run_name": "diagram-agent",
        "tags": ["diagram-agent"],
        "metadata": {"thread_id": thread_id, "run_id": run_id},
    }
    last_tool = _last_tool_msg(messages)

    async def stream():
        _upsert_snap: dict = {}
        yield _sse({"type": "RUN_STARTED", "threadId": thread_id, "runId": run_id})
        try:
            if last_tool is not None:
                # Resume from a HITL gate with the user's approve/reject decision.
                try:
                    payload = json.loads(last_tool.get("content", "{}"))
                except Exception:  # noqa: BLE001
                    payload = {}
                pending_name = _pending_action_name(await _pending_interrupt(config))
                decision = _decision_from_payload(payload, pending_name)
                logger.info("resume %s → %s", pending_name, decision["type"])
                # Track gate outcomes for the learning loop (Tier 5).
                if pending_name in GATE_TOOL_NAMES:
                    note = payload.get("feedback") or payload.get("modifications") or ""
                    record_report_step(
                        WORKSPACE,
                        f"{pending_name}_gate",
                        status=decision["type"],
                        summary=(
                            f"User {'approved' if decision['type'] == 'approve' else 'rejected'} {pending_name}."
                            + (f" Feedback: {note}" if note else "")
                        ),
                        data={"gate": pending_name, "decision": decision["type"], "note": str(note) if note else ""},
                    )
                    await conv_db.record_gate_outcome(
                        request.app.state.pool,
                        thread_id=thread_id,
                        gate=pending_name,
                        decision=decision["type"],
                        note=str(note) if note else "",
                    )
                agen = AGENT.astream(
                    Command(resume={"decisions": [decision]}), config,
                    stream_mode=["messages", "updates", "custom"],
                )
            else:
                # Fresh run.
                desc = _last_user_text(messages)
                preserve_artifacts = _is_pdf_followup(desc) and (WORKSPACE / "out.png").exists()
                if not preserve_artifacts:
                    clear_stage_markers()
                else:
                    desc = (
                        (desc + "\n\n" if desc else "")
                        + "IMPORTANT: A rendered diagram already exists in the workspace "
                        "(`out.png`, `out.drawio`, `diagram.py`) with approved planning "
                        "artifacts. The user is asking for a PDF/report/document. Do NOT "
                        "redesign or re-render the diagram. Call `generate_pdf_report({})` "
                        "now so the PDF approval gate is shown, then complete after `out.pdf` "
                        "is created."
                    )
                attached = _attached_text(file_ids)
                image_blocks = _attached_images(file_ids)
                req_file = WORKSPACE / "requirements.md"
                if attached:
                    # Save the (potentially large) docs to a file the agent reads
                    # ONCE, instead of inlining them into every turn's context.
                    # Wrap in <untrusted_document> so the agent treats it as data,
                    # not as instructions (guards against prompt-injection via uploads).
                    WORKSPACE.mkdir(parents=True, exist_ok=True)
                    req_file.write_text(
                        f"<untrusted_document>\n{attached}\n</untrusted_document>",
                        encoding="utf-8",
                    )
                    desc = (
                        (desc + "\n\n" if desc else "")
                        + "IMPORTANT: the detailed requirement documents are saved to "
                        "`requirements.md` in your working directory — read that file "
                        "first for the full requirements."
                    )
                elif req_file.exists() and not preserve_artifacts:
                    req_file.unlink()  # don't let a previous run's docs leak in

                # Build the HumanMessage. When reference images are attached,
                # include them as image_url content blocks so the model can
                # see the sketch/reference and align the blueprint to it.
                if image_blocks:
                    img_note = (
                        "\n\nReference image(s) are attached above. Use the topology "
                        "and layout shown as a guide when proposing the blueprint; "
                        "the critic may compare the final render against them."
                    )
                    content: list | str = (
                        [{"type": "text", "text": (desc or "") + img_note}]
                        + image_blocks
                    )
                else:
                    content = desc

                logger.info("new run: %r%s%s", (desc or "")[:120],
                            " (+docs→requirements.md)" if attached else "",
                            f" (+{len(image_blocks)} ref-image(s))" if image_blocks else "")
                agen = AGENT.astream(
                    {"messages": [HumanMessage(content=content)]}, config,
                    stream_mode=["messages", "updates", "custom"],
                )

            current_id: str | None = None
            seen_starts: set[str] = set()
            seen_ends: set[str] = set()
            # Delegation tracking: task tool_call_id → delegation record
            _pending_tasks: dict[str, dict] = {}
            _completed_delegations: list[dict] = []
            async for mode, payload in agen:
                if mode == "messages":
                    chunk, _meta = payload
                    if getattr(chunk, "type", "") not in ("ai", "AIMessageChunk"):
                        continue
                    text = _text_of(chunk.content)
                    if not text:
                        continue
                    mid = getattr(chunk, "id", None) or "ai"
                    if mid != current_id:
                        if current_id is not None:
                            yield _sse({"type": "TEXT_MESSAGE_END", "messageId": current_id})
                        current_id = mid
                        yield _sse({"type": "TEXT_MESSAGE_START", "messageId": current_id, "role": "assistant"})
                    yield _sse({"type": "TEXT_MESSAGE_CONTENT", "messageId": current_id, "delta": text})
                elif mode == "updates":
                    # Surface what the agent is doing — tool calls (start) + results (end).
                    # The same message can appear under several node keys; dedupe by id.
                    for _node, upd in (payload or {}).items():
                        if not isinstance(upd, dict):
                            continue
                        msgs_raw = upd.get("messages", []) or []
                        # LangGraph may wrap values in an Overwrite object; unwrap it.
                        if not isinstance(msgs_raw, (list, tuple)):
                            msgs_raw = getattr(msgs_raw, "value", None) or []
                        for m in msgs_raw:
                            if isinstance(m, AIMessage):
                                for tc in (m.tool_calls or []):
                                    tcid = tc.get("id") or ""
                                    if tcid in seen_starts:
                                        continue
                                    seen_starts.add(tcid)
                                    name = tc.get("name", "tool")
                                    args = tc.get("args", {})
                                    detail = _tool_detail(name, args)
                                    subagent = _TOOL_TO_SUBAGENT.get(name)
                                    if name == "task":
                                        # Subagent delegation — extract name + description.
                                        sa_name = args.get("subagent_type") or args.get("subagent") or args.get("name") or "unknown"
                                        desc = args.get("description") or args.get("instruction") or args.get("prompt") or ""
                                        record = {"id": tcid, "subagent": sa_name, "description": desc,
                                                  "status": "running", "result": None,
                                                  "current_detail": detail}
                                        _pending_tasks[tcid] = record
                                        logger.info("→ delegate to %s: %s", sa_name, desc[:80])
                                        yield _sse({"type": "ACTIVITY", "phase": "start", "tool": name,
                                                    "label": f"Delegating to {sa_name}", "subagent": sa_name,
                                                    "detail": detail})
                                        # Emit live STATE_DELTA so the UI sees the new delegation immediately.
                                        all_delegations = _completed_delegations + list(_pending_tasks.values())
                                        yield _sse({"type": "STATE_DELTA", "delta": [
                                            {"op": "replace", "path": "/delegations", "value": all_delegations}
                                        ]})
                                    else:
                                        logger.info("→ %s%s", _label(name),
                                                    f" [{subagent}]" if subagent else "")
                                        evt: dict = {"type": "ACTIVITY", "phase": "start",
                                                     "tool": name, "label": _label(name),
                                                     "detail": detail}
                                        if subagent:
                                            evt["subagent"] = subagent
                                        yield _sse(evt)
                            elif isinstance(m, ToolMessage):
                                tcid = getattr(m, "tool_call_id", "") or ""
                                if tcid in seen_ends:
                                    continue
                                seen_ends.add(tcid)
                                name = getattr(m, "name", "tool")
                                ok = getattr(m, "status", None) != "error"
                                subagent = _TOOL_TO_SUBAGENT.get(name)
                                if tcid in _pending_tasks:
                                    # Delegation completed.
                                    result_text = _text_of(m.content)
                                    record = _pending_tasks.pop(tcid)
                                    record["status"] = "completed" if ok else "error"
                                    record["result"] = (result_text[:500] + "…") if len(result_text) > 500 else result_text
                                    _completed_delegations.append(record)
                                    logger.info("← delegate %s done (%s)", record["subagent"], record["status"])
                                    all_delegations = _completed_delegations + list(_pending_tasks.values())
                                    yield _sse({"type": "STATE_DELTA", "delta": [
                                        {"op": "replace", "path": "/delegations", "value": all_delegations}
                                    ]})
                                logger.info("← %s %s%s", name, "ok" if ok else "ERROR",
                                            f" [{subagent}]" if subagent else "")
                                evt2: dict = {"type": "ACTIVITY", "phase": "end", "tool": name,
                                              "ok": ok, "detail": _tool_output_detail(m.content)}
                                if subagent:
                                    evt2["subagent"] = subagent
                                yield _sse(evt2)
                                if name == "generate_pdf_report" and ok:
                                    artifact_delta = [
                                        {"op": "replace", "path": f"/{k}", "value": v}
                                        for k, v in _artifacts().items()
                                    ]
                                    artifact_delta.append({"op": "replace", "path": "/current_step", "value": "done"})
                                    yield _sse({"type": "STATE_DELTA", "delta": artifact_delta})
                elif mode == "custom":
                    # Live per-step activity from within a running subagent.
                    # Emitted by _StreamingSubAgentRunnable via get_stream_writer().
                    sa_name = payload.get("subagent", "")
                    phase = payload.get("phase", "start")
                    tool = payload.get("tool", "tool")
                    ok = payload.get("ok", True)
                    detail = payload.get("detail", "")
                    label = _label(tool)
                    logger.info("  [%s] %s %s", sa_name, "→" if phase == "start" else "←", label)
                    act_evt: dict = {
                        "type": "ACTIVITY", "phase": phase,
                        "tool": tool, "label": label, "subagent": sa_name,
                        "detail": detail,
                    }
                    if phase == "end":
                        act_evt["ok"] = ok
                    yield _sse(act_evt)
                    # Keep the delegation record's current_tool in sync so the UI
                    # spinner shows what the subagent is doing right now.
                    if phase == "start":
                        for _tcid, record in _pending_tasks.items():
                            if record.get("subagent") == sa_name:
                                record["current_tool"] = tool
                                record["current_label"] = label
                                record["current_detail"] = detail
                                yield _sse({"type": "STATE_DELTA", "delta": [
                                    {"op": "replace", "path": "/delegations",
                                     "value": _completed_delegations + list(_pending_tasks.values())}
                                ]})
                                break
                    elif phase == "end":
                        for record in _pending_tasks.values():
                            if record.get("subagent") == sa_name:
                                record.pop("current_tool", None)
                                record.pop("current_label", None)
                                record.pop("current_detail", None)
                                break
            if current_id is not None:
                yield _sse({"type": "TEXT_MESSAGE_END", "messageId": current_id})

            summary, logs = await _summary_and_logs(config)
            run_metrics = _run_metrics(logs)

            # A gate is pending → emit the approval card.
            val = await _pending_interrupt(config)
            if val is not None:
                card, step, delta = _card_for(val, summary)
                if card is not None:
                    logger.info("PAUSED at gate: %s", card["type"])
                    state_delta = [{"op": "replace", "path": "/current_step", "value": step}]
                    for k, v in _stage_artifacts().items():
                        state_delta.append({"op": "replace", "path": f"/{k}", "value": v})
                    state_delta.append({"op": "replace", "path": "/run_metrics", "value": run_metrics})
                    for k, v in delta.items():
                        state_delta.append({"op": "replace", "path": f"/{k}", "value": v})
                    # At the final review gate the diagram is already rendered — send
                    # it now so the user can preview/download while reviewing.
                    for k, v in _artifacts().items():
                        state_delta.append({"op": "replace", "path": f"/{k}", "value": v})
                    yield _sse({"type": "STATE_DELTA", "delta": state_delta})
                    tc_id = f"tc-{run_id}"
                    yield _sse({"type": "TOOL_CALL_START", "toolCallId": tc_id, "toolCallName": card["type"]})
                    yield _sse({"type": "TOOL_CALL_ARGS", "toolCallId": tc_id, "delta": json.dumps(card)})
                    yield _sse({"type": "TOOL_CALL_END", "toolCallId": tc_id})
                    await conv_db.upsert_run(
                        request.app.state.pool,
                        thread_id=thread_id,
                        messages=messages,
                        state={"current_step": step, **_stage_artifacts(), **delta, **_artifacts(),
                               "run_metrics": run_metrics},
                        last_msg=_last_user_text(messages),
                        auto_name=(_last_user_text(messages) or "Untitled")[:50],
                    )
                    yield _sse({"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id})
                    return

            # Collect any remaining delegations (running tasks not yet resolved).
            all_delegations = _completed_delegations + [
                {**r, "status": "running"} for r in _pending_tasks.values()
            ]

            # No gate pending. If a diagram was produced, emit the final snapshot.
            png = WORKSPACE / "out.png"
            if png.exists():
                logger.info("run finished — diagram ready")
                snapshot = {"current_step": "done", "summary": summary, "logs": logs,
                            "run_metrics": run_metrics}
                snapshot.update(_stage_artifacts())
                snapshot.update(_artifacts())
                if all_delegations:
                    snapshot["delegations"] = all_delegations
                _upsert_snap = snapshot
                yield _sse({"type": "STATE_SNAPSHOT", "snapshot": snapshot})
            else:
                # Mid-flow turn (e.g. the agent asked a clarifying question). The
                # chat text already carries it — just sync any structured state.
                snap: dict = {"logs": logs, "run_metrics": run_metrics}
                snap.update(_stage_artifacts())
                if all_delegations:
                    snap["delegations"] = all_delegations
                _upsert_snap = snap
                yield _sse({"type": "STATE_SNAPSHOT", "snapshot": snap})

        except Exception as exc:  # noqa: BLE001
            logger.exception("agent run failed: %s", exc)
            yield _sse({"type": "RUN_ERROR", "message": str(exc), "code": "internal_error"})

        if _upsert_snap:
            await conv_db.upsert_run(
                request.app.state.pool,
                thread_id=thread_id,
                messages=messages,
                state=_upsert_snap,
                last_msg=_last_user_text(messages),
                auto_name=(_last_user_text(messages) or "Untitled")[:50],
            )
        yield _sse({"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def main() -> None:
    port = int(os.getenv("DIAGRAM_AGENT_PORT", "8001"))
    logger.info("Starting diagram agent server on port %d", port)
    uvicorn.run("diagram_mcp.server:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
