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
from .requirements_reader import IMAGE_EXT, parse_file
from .tools import GATE_TOOL_NAMES, clear_stage_markers

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
    "propose_tech_stack": "Proposing the technology stack",
    "propose_blueprint": "Designing the architecture blueprint",
    "render_diagram": "Rendering the diagram",
    "export_drawio": "Exporting the editable .drawio",
    "search_icons": "Searching the icon library",
    "fetch_logo": "Fetching a logo",
    "inspect_diagram": "Reviewing the rendered diagram",
    "submit_critique": "Recording the diagram review",
    "finalize_diagram": "Finalizing the diagram",
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
    "search_icons": "drawer",
    "fetch_logo": "drawer",
    "render_diagram": "drawer",
    "export_drawio": "drawer",
    "inspect_diagram": "critic",
    "submit_critique": "critic",
}


def _label(tool: str) -> str:
    return _TOOL_LABELS.get(tool, f"Running {tool}")

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
    tools = [m for m in messages if m.get("role") == "tool"]
    return tools[-1] if tools else None


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
    return None


def _normalize_tech_stack(ts) -> dict:
    """Normalize the model's tech_stack into {layer: {choice, rationale, alternatives}}.

    The tool schema is a list of {layer, choice, rationale, alternatives}, but be
    tolerant of a dict (older/variant model output) too.
    """
    out: dict = {}
    if isinstance(ts, list):
        for item in ts:
            if isinstance(item, dict) and item.get("layer"):
                out[item["layer"]] = {
                    "choice": item.get("choice", ""),
                    "rationale": item.get("rationale", ""),
                    "alternatives": item.get("alternatives", []) or [],
                }
    elif isinstance(ts, dict):
        for layer, info in ts.items():
            if isinstance(info, dict):
                out[layer] = {
                    "choice": info.get("choice", ""),
                    "rationale": info.get("rationale", ""),
                    "alternatives": info.get("alternatives", []) or [],
                }
            else:
                # flattened/degenerate value (e.g. a bare string) — show it as the choice
                out[layer] = {"choice": str(info), "rationale": "", "alternatives": []}
    return out


def _card_for(val, summary: str):
    """Translate a HITLRequest → (card_data, current_step, state_delta)."""
    ars = (val or {}).get("action_requests") or [{}]
    name = ars[0].get("name")
    args = ars[0].get("args") or {}
    if name == "propose_tech_stack":
        ts = _normalize_tech_stack(args.get("tech_stack"))
        return (
            {"type": "techstack_approval", "tech_stack": ts,
             "question": "Review the recommended tech stack. Approve, or reject with the changes you want."},
            "awaiting_techstack", {"tech_stack": ts},
        )
    if name == "propose_blueprint":
        bp = args.get("blueprint", {})
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
    return None, None, {}


def _decision_from_payload(payload: dict, pending_name: str | None) -> dict:
    if pending_name == "finalize_diagram":
        ok = bool(payload.get("satisfied", True))
        msg = payload.get("feedback")
    else:
        ok = bool(payload.get("approved", False))
        msg = payload.get("modifications")
    if ok:
        return {"type": "approve"}
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
                inp = next((str(v) for v in args.values() if isinstance(v, str)), "") or json.dumps(args)[:160]
                entry = {"t": 0, "type": "tool_start", "tool": tc.get("name", "tool"), "input": inp[:160]}
                logs.append(entry)
                pending[tc.get("id", "")] = entry
            txt = _text_of(m.content).strip()
            if txt:
                summary = txt
        elif isinstance(m, ToolMessage):
            entry = pending.get(getattr(m, "tool_call_id", ""))
            if entry is not None:
                out = _text_of(m.content)
                entry["output"] = (out[:160] + "…") if len(out) > 160 else out
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
                clear_stage_markers()
                desc = _last_user_text(messages)
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
                elif req_file.exists():
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
                                    subagent = _TOOL_TO_SUBAGENT.get(name)
                                    if name == "task":
                                        # Subagent delegation — extract name + description.
                                        args = tc.get("args", {})
                                        sa_name = args.get("subagent_type") or args.get("subagent") or args.get("name") or "unknown"
                                        desc = args.get("description") or args.get("instruction") or args.get("prompt") or ""
                                        record = {"id": tcid, "subagent": sa_name, "description": desc,
                                                  "status": "running", "result": None}
                                        _pending_tasks[tcid] = record
                                        logger.info("→ delegate to %s: %s", sa_name, desc[:80])
                                        yield _sse({"type": "ACTIVITY", "phase": "start", "tool": name,
                                                    "label": f"Delegating to {sa_name}", "subagent": sa_name})
                                        # Emit live STATE_DELTA so the UI sees the new delegation immediately.
                                        all_delegations = _completed_delegations + list(_pending_tasks.values())
                                        yield _sse({"type": "STATE_DELTA", "delta": [
                                            {"op": "replace", "path": "/delegations", "value": all_delegations}
                                        ]})
                                    else:
                                        logger.info("→ %s%s", _label(name),
                                                    f" [{subagent}]" if subagent else "")
                                        evt: dict = {"type": "ACTIVITY", "phase": "start",
                                                     "tool": name, "label": _label(name)}
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
                                evt2: dict = {"type": "ACTIVITY", "phase": "end", "tool": name, "ok": ok}
                                if subagent:
                                    evt2["subagent"] = subagent
                                yield _sse(evt2)
                elif mode == "custom":
                    # Live per-step activity from within a running subagent.
                    # Emitted by _StreamingSubAgentRunnable via get_stream_writer().
                    sa_name = payload.get("subagent", "")
                    phase = payload.get("phase", "start")
                    tool = payload.get("tool", "tool")
                    ok = payload.get("ok", True)
                    label = _label(tool)
                    logger.info("  [%s] %s %s", sa_name, "→" if phase == "start" else "←", label)
                    act_evt: dict = {
                        "type": "ACTIVITY", "phase": phase,
                        "tool": tool, "label": label, "subagent": sa_name,
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
                                break
            if current_id is not None:
                yield _sse({"type": "TEXT_MESSAGE_END", "messageId": current_id})

            summary, logs = await _summary_and_logs(config)

            # A gate is pending → emit the approval card.
            val = await _pending_interrupt(config)
            if val is not None:
                card, step, delta = _card_for(val, summary)
                if card is not None:
                    logger.info("PAUSED at gate: %s", card["type"])
                    state_delta = [{"op": "replace", "path": "/current_step", "value": step}]
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
                        state={"current_step": step, **delta, **_artifacts()},
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
                snapshot = {"current_step": "done", "summary": summary, "logs": logs}
                snapshot.update(_artifacts())
                ts = _read_json(WORKSPACE / "tech_stack.json")
                bp = _read_json(WORKSPACE / "blueprint.json")
                if ts:
                    snapshot["tech_stack"] = ts
                if bp:
                    snapshot["blueprint"] = bp
                if all_delegations:
                    snapshot["delegations"] = all_delegations
                _upsert_snap = snapshot
                yield _sse({"type": "STATE_SNAPSHOT", "snapshot": snapshot})
            else:
                # Mid-flow turn (e.g. the agent asked a clarifying question). The
                # chat text already carries it — just sync any structured state.
                snap: dict = {"logs": logs}
                ts = _read_json(WORKSPACE / "tech_stack.json")
                bp = _read_json(WORKSPACE / "blueprint.json")
                if ts:
                    snap["tech_stack"] = ts
                if bp:
                    snap["blueprint"] = bp
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
