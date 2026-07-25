import { describe, expect, it } from "vitest";
import { DiagramHttpAgent } from "../diagram-agent.js";

/**
 * index.ts casts `agent as unknown as AbstractAgent` to work around a type
 * mismatch between @copilotkit/runtime@1.63.2's bundled @ag-ui/client type
 * identity and our direct dependency (same published version, structurally
 * identical, but not nominally unified — CopilotKit's own examples hit the
 * same issue and disable typechecking project-wide for it; we scope it to
 * one cast instead).
 *
 * A cast bypasses the compiler, so if a future @ag-ui/client bump actually
 * changes the runtime API shape (not just the type identity), nothing would
 * catch it at build time — this test is that safety net.
 */
describe("DiagramHttpAgent — real API surface the cast in index.ts relies on", () => {
  const agent = new DiagramHttpAgent({ url: "http://backend:8001/agui" });

  it("has the methods CopilotRuntime's agent-runner path calls", () => {
    expect(typeof agent.runAgent).toBe("function");
    expect(typeof agent.abortRun).toBe("function");
    expect(typeof agent.setMessages).toBe("function");
    expect(typeof agent.setState).toBe("function");
    expect(typeof agent.subscribe).toBe("function");
  });

  it("has the mutable properties handle-run.ts sets before every run", () => {
    agent.setMessages([]);
    agent.setState({});
    agent.threadId = "thread-x";
    expect(agent.threadId).toBe("thread-x");
    expect(Array.isArray(agent.messages)).toBe(true);
  });
});
