import { HttpAgent } from "@ag-ui/client";
import type { Message, RunAgentInput } from "@ag-ui/client";
import { CONFIG } from "./config.js";

/** Roles the Python backend understands (backend/src/routers/chat.py:200
 *  reads `body["messages"]` as a flat list and only branches on
 *  role==="user"/"tool" — `system`/`developer` messages have no meaning
 *  there and must never reach the wire). */
const ALLOWED_ROLES = new Set(["user", "assistant", "tool"]);

export interface DiagramForwardedProps {
  file_ids?: string[];
  userRole?: string;
  diagramKind?: string;
}

/** The flat wire shape backend/src/routers/chat.py:195-202 actually reads —
 *  NOT the standard AG-UI `RunAgentInput`. */
export interface DiagramWireBody {
  threadId: string;
  runId: string;
  messages: unknown[];
  file_ids: string[];
  userRole: string;
  diagramKind: string;
}

/**
 * Verified against @ag-ui/core's RunAgentInputSchema (Message is a
 * role-discriminated union): `user.content` is `string | InputContentPart[]`,
 * `assistant` carries `content?: string` + `toolCalls?`, `tool` carries
 * `{content: string, toolCallId}`. Only the fields the backend actually reads
 * are kept — everything else (encryptedValue, name, tool `error`, assistant
 * `toolCalls`) is dropped since chat.py never inspects them and forwarding
 * them would just be unvalidated surface area.
 */
export function sanitizeMessages(messages: readonly Message[]): unknown[] {
  const out: unknown[] = [];
  for (const m of messages) {
    if (!ALLOWED_ROLES.has(m.role)) continue; // drops system/developer
    if (m.role === "tool") {
      out.push({ id: m.id, role: "tool", toolCallId: m.toolCallId, content: m.content ?? "" });
      continue;
    }
    // user | assistant
    const content = (m as { content?: unknown }).content;
    if (m.role === "user" && typeof content !== "string") {
      // A part-array here means CopilotChatInput's attachment queue (or some
      // future content-injecting feature) is active. The Python follow-up
      // heuristics (_last_user_text -> _is_pdf_followup etc., chat.py:314-494)
      // require plain text — throwing here surfaces the regression at the
      // first smoke test instead of silently corrupting backend state via a
      // stringified-JSON "text".
      throw new Error(
        `[runtime] user message ${m.id} has non-string content (${typeof content}). ` +
          "The Python follow-up heuristics require plain text — do not enable " +
          "CopilotChatInput attachments; use POST /upload + file_ids instead.",
      );
    }
    out.push({ id: m.id, role: m.role, content: content ?? "" });
  }
  return out;
}

/** Compares the last `role==="user"` message before/after sanitize (plan
 *  §B.3) and throws on any mutation. Cheap enough to run unconditionally;
 *  gated by CONFIG.assertMessageIntegrity so it can be disabled if a future,
 *  deliberate change needs to bypass it temporarily. */
function assertLastUserMessageUnchanged(original: readonly Message[], sanitized: readonly unknown[]): void {
  if (!CONFIG.assertMessageIntegrity) return;
  const lastOriginal = [...original].reverse().find((m) => m.role === "user");
  const lastSanitized = [...sanitized].reverse().find((m): m is { role: string; content: unknown } => {
    return typeof m === "object" && m !== null && (m as { role?: unknown }).role === "user";
  });
  if (!lastOriginal || !lastSanitized) return;
  const before = (lastOriginal as { content?: unknown }).content;
  if (before !== lastSanitized.content) {
    throw new Error(
      "[runtime] last user message was mutated in transit — this would silently " +
        "corrupt the backend's follow-up-detection heuristics (chat.py:314-494). " +
        `before=${JSON.stringify(before)} after=${JSON.stringify(lastSanitized.content)}`,
    );
  }
}

export class DiagramHttpAgent extends HttpAgent {
  /**
   * backend/src/routers/chat.py:195-202 reads a FLAT body
   * {threadId, runId, messages, file_ids, userRole, diagramKind} — not the
   * standard AG-UI RunAgentInput. Override the request body while keeping
   * HttpAgent's SSE parsing, JSON-Patch state application, and event
   * pipeline (verified: `protected requestInit(input): RequestInit` is the
   * documented override point in @ag-ui/client's HttpAgent).
   */
  protected requestInit(input: RunAgentInput): RequestInit {
    const fw = (input.forwardedProps ?? {}) as DiagramForwardedProps;
    const sanitized = sanitizeMessages(input.messages);
    assertLastUserMessageUnchanged(input.messages, sanitized);

    const body: DiagramWireBody = {
      threadId: input.threadId,
      runId: input.runId,
      messages: sanitized,
      file_ids: fw.file_ids ?? [],
      userRole: fw.userRole ?? "",
      // "" = Auto detect; the backend's keyword classifier decides.
      diagramKind: fw.diagramKind ?? "",
    };

    return {
      method: "POST",
      headers: {
        ...this.headers,
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(body),
      signal: this.abortController.signal,
    };
  }
}
