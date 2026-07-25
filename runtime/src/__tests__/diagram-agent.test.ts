import { describe, expect, it } from "vitest";
import type { Message, RunAgentInput } from "@ag-ui/client";
import { DiagramHttpAgent, sanitizeMessages } from "../diagram-agent.js";

/** Exposes the protected `requestInit` for testing without changing its
 *  visibility on the real class (it must stay `protected` to override
 *  HttpAgent correctly). */
class TestableDiagramAgent extends DiagramHttpAgent {
  public callRequestInit(input: RunAgentInput): RequestInit {
    return this.requestInit(input);
  }
}

function baseInput(messages: Message[], forwardedProps: Record<string, unknown> = {}): RunAgentInput {
  return {
    threadId: "thread-1",
    runId: "run-1",
    messages,
    tools: [],
    context: [],
    state: {},
    forwardedProps,
  };
}

describe("sanitizeMessages", () => {
  it("drops system and developer roles", () => {
    const messages = [
      { id: "s1", role: "system", content: "you are a helpful assistant" },
      { id: "d1", role: "developer", content: "internal note" },
      { id: "u1", role: "user", content: "hello" },
    ] as unknown as Message[];
    const out = sanitizeMessages(messages);
    expect(out).toEqual([{ id: "u1", role: "user", content: "hello" }]);
  });

  it("preserves toolCallId on tool messages", () => {
    const messages = [
      { id: "t1", role: "tool", toolCallId: "tc-run-1", content: '{"action":"approve"}' },
    ] as unknown as Message[];
    const out = sanitizeMessages(messages);
    expect(out).toEqual([{ id: "t1", role: "tool", toolCallId: "tc-run-1", content: '{"action":"approve"}' }]);
  });

  it("throws on non-string user content instead of silently coercing", () => {
    const messages = [
      { id: "u1", role: "user", content: [{ type: "text", text: "hi" }] },
    ] as unknown as Message[];
    expect(() => sanitizeMessages(messages)).toThrow(/non-string content/);
  });

  it("drops assistant toolCalls/encryptedValue — only content survives", () => {
    const messages = [
      {
        id: "a1",
        role: "assistant",
        content: "designing...",
        toolCalls: [{ id: "tc-1", type: "function", function: { name: "propose_tech_stack", arguments: "{}" } }],
      },
    ] as unknown as Message[];
    const out = sanitizeMessages(messages);
    expect(out).toEqual([{ id: "a1", role: "assistant", content: "designing..." }]);
  });
});

describe("DiagramHttpAgent.requestInit", () => {
  const agent = new TestableDiagramAgent({ url: "http://backend:8001/agui" });

  it("emits exactly the six flat keys backend/src/routers/chat.py:195-202 reads", async () => {
    const input = baseInput(
      [{ id: "u1", role: "user", content: "design a 3-tier web app" } as unknown as Message],
      { file_ids: ["abc123"], userRole: "lead", diagramKind: "architecture" },
    );
    const init = agent.callRequestInit(input);
    const body = JSON.parse(init.body as string);
    expect(Object.keys(body).sort()).toEqual(
      ["diagramKind", "file_ids", "messages", "runId", "threadId", "userRole"].sort(),
    );
    expect(body.threadId).toBe("thread-1");
    expect(body.runId).toBe("run-1");
    expect(body.file_ids).toEqual(["abc123"]);
    expect(body.userRole).toBe("lead");
    expect(body.diagramKind).toBe("architecture");
  });

  it("defaults file_ids/userRole/diagramKind when forwardedProps omit them", async () => {
    const input = baseInput([{ id: "u1", role: "user", content: "x" } as unknown as Message]);
    const body = JSON.parse(agent.callRequestInit(input).body as string);
    expect(body.file_ids).toEqual([]);
    expect(body.userRole).toBe("");
    expect(body.diagramKind).toBe("");
  });

  it("sets method/headers/signal correctly", () => {
    const input = baseInput([{ id: "u1", role: "user", content: "x" } as unknown as Message]);
    const init = agent.callRequestInit(input);
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect((init.headers as Record<string, string>).Accept).toBe("text/event-stream");
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("preserves toolCallId on a resume (tool result) message", () => {
    const input = baseInput([
      { id: "u1", role: "user", content: "design x" } as unknown as Message,
      { id: "tool-1", role: "tool", toolCallId: "tc-run-1", content: '{"action":"approve","approved":true}' } as unknown as Message,
    ]);
    const body = JSON.parse(agent.callRequestInit(input).body as string);
    expect(body.messages[1]).toEqual({
      id: "tool-1",
      role: "tool",
      toolCallId: "tc-run-1",
      content: '{"action":"approve","approved":true}',
    });
  });
});
