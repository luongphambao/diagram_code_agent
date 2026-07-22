"""Manual smoke test: drive the FULL staged agent flow (upload doc -> propose
tech stack [auto-approve] -> propose blueprint [auto-approve] -> render via
the Modal sandbox -> finalize [auto-approve]) against the REAL running
backend over HTTP, exactly like the real frontend does.

Usage (from inside the backend container, or the host with httpx installed):
    python scripts/full_flow_smoke_test.py <path-to-markdown-or-text-file>

Artifacts land under the usual host-visible ./artifacts/<threadId>/ (see
ARTIFACTS_DIR in docker-compose.yml) since this hits the real /agui endpoint,
not a direct sandbox call.
"""

from __future__ import annotations

import json
import sys
import time

import httpx

BASE_URL = "http://localhost:8001"
# SSE TOOL_CALL_START.toolCallName carries the UI *card* type (session/gate_decisions.py's
# _card_for), not the raw agent tool name — propose_tech_stack shows up as
# "techstack_approval", propose_blueprint as "blueprint_approval", finalize_diagram as
# "result_review". Mapped here to the "approved"/"satisfied" decision key each expects.
GATE_DECISION_KEY = {
    "techstack_approval": "approved",
    "blueprint_approval": "approved",
    "result_review": "satisfied",
}
MAX_TURNS = 12  # safety cap — each turn is one HITL round-trip


def upload(client: httpx.Client, path: str) -> str:
    with open(path, "rb") as f:
        resp = client.post(f"{BASE_URL}/upload", files={"file": f}, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    print(f"Uploaded: file_id={data['file_id']} kind={data['kind']} chars={data['char_count']}")
    return data["file_id"]


def stream_turn(client: httpx.Client, thread_id: str, run_id: str, messages: list[dict], file_ids: list[str]) -> dict:
    """POST /agui, consume the SSE stream, return {'gate': str|None, 'errored': bool}."""
    body = {
        "threadId": thread_id,
        "runId": run_id,
        "messages": messages,
        "file_ids": file_ids,
        "userEmail": "smoke-test@example.com",
        "userRole": "architect",
    }
    gate_seen = None
    errored = False
    with client.stream("POST", f"{BASE_URL}/agui", json=body, timeout=300) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            payload = json.loads(line[len("data:"):].strip())
            etype = payload.get("type")
            if etype == "TOOL_CALL_START" and payload.get("toolCallName") in GATE_DECISION_KEY:
                gate_seen = payload["toolCallName"]
                print(f"  -> gate reached: {gate_seen}")
            elif etype == "TEXT_MESSAGE_CONTENT":
                pass  # streamed assistant text — skip for brevity
            elif etype == "RUN_ERROR":
                errored = True
                print(f"  !! RUN_ERROR: {payload.get('message')}")
            elif etype == "RUN_FINISHED":
                print("  -> RUN_FINISHED")
    return {"gate": gate_seen, "errored": errored}


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: full_flow_smoke_test.py <path-to-doc>")
        sys.exit(1)
    doc_path = sys.argv[1]

    thread_id = f"thread-smoketest-{int(time.time())}"
    run_id = "run-1"

    with httpx.Client() as client:
        file_id = upload(client, doc_path)

        messages = [
            {
                "role": "user",
                "content": (
                    "Design an end-to-end architecture diagram for this FMCG "
                    "Finance & Accounting automation solution (IDP + RPA), covering "
                    "the four process groups (P2P, O2C, R2R, Treasury), the core "
                    "systems it integrates with, and the exception-queue / human "
                    "approval flow. Keep it clean and presentation-ready."
                ),
            }
        ]
        file_ids = [file_id]

        for turn in range(MAX_TURNS):
            print(f"\n=== Turn {turn} ===")
            result = stream_turn(client, thread_id, run_id, messages, file_ids)
            if result["errored"]:
                print("Stopping: run errored.")
                break
            gate = result["gate"]
            if gate is None:
                print("No gate pending — run completed (or produced no further interrupts).")
                break
            decision = {GATE_DECISION_KEY[gate]: True}
            messages = [{"role": "tool", "content": json.dumps(decision)}]
            file_ids = []  # only needed on the first turn

        print(f"\nDone. thread_id={thread_id}")
        print(f"Artifacts (if the workspace is host-mounted): ./artifacts/{thread_id}/")


if __name__ == "__main__":
    main()
