import { afterEach, describe, expect, it, vi } from "vitest";
import { firstValueFrom, toArray } from "rxjs";
import type { AbstractAgent, BaseEvent } from "@ag-ui/client";
import { DiagramHttpAgent } from "../diagram-agent.js";
import { PassthroughRunner } from "../passthrough-runner.js";

/**
 * Verifies the two properties PassthroughRunner exists for (plan §A.2/§A.5,
 * risk R2): it forwards every event through unmodified (confirmed at the
 * source level in @ag-ui/client's dispatcher — onEvent fires unconditionally
 * before any type-specific handler), and it retains nothing across runs
 * (unlike InMemoryAgentRunner's module-global ReplaySubject(Infinity) store).
 */

function fakeEvents(): BaseEvent[] {
  return [
    { type: "RUN_STARTED" } as unknown as BaseEvent,
    { type: "TEXT_MESSAGE_START", messageId: "m1" } as unknown as BaseEvent,
    { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "hi" } as unknown as BaseEvent,
    { type: "RUN_FINISHED" } as unknown as BaseEvent,
  ];
}

function mockAgent(events: BaseEvent[]): AbstractAgent {
  const agent = new DiagramHttpAgent({ url: "http://backend:8001/agui" });
  // Real instances have real `subscribe`/`runAgent` that hit the network;
  // override per-instance (own-property shadowing) so this test exercises
  // PassthroughRunner's plumbing without any I/O.
  let onEvent: ((p: { event: BaseEvent }) => void) | undefined;
  agent.subscribe = vi.fn((subscriber) => {
    onEvent = subscriber.onEvent as typeof onEvent;
    return { unsubscribe: vi.fn() };
  }) as AbstractAgent["subscribe"];
  agent.runAgent = vi.fn(async () => {
    for (const event of events) onEvent?.({ event });
    return {} as never;
  }) as AbstractAgent["runAgent"];
  agent.abortRun = vi.fn();
  return agent as unknown as AbstractAgent;
}

describe("PassthroughRunner", () => {
  it("forwards every event emitted by the agent, in order, then completes", async () => {
    const runner = new PassthroughRunner();
    const events = fakeEvents();
    const agent = mockAgent(events);

    const received = await firstValueFrom(
      runner
        .run({ threadId: "t1", agent, input: { threadId: "t1", runId: "r1", messages: [] } as never })
        .pipe(toArray()),
    );

    expect(received.map((e) => (e as { type: string }).type)).toEqual([
      "RUN_STARTED",
      "TEXT_MESSAGE_START",
      "TEXT_MESSAGE_CONTENT",
      "RUN_FINISHED",
    ]);
  });

  it("tracks isRunning during the run and clears it after completion", async () => {
    const runner = new PassthroughRunner();
    const agent = mockAgent(fakeEvents());

    const runPromise = firstValueFrom(
      runner.run({ threadId: "t2", agent, input: { threadId: "t2", runId: "r1", messages: [] } as never }).pipe(toArray()),
    );
    await runPromise;
    // runAgent resolved synchronously in this mock, so by the time the
    // observable completes the thread is no longer tracked as in-flight.
    expect(await runner.isRunning({ threadId: "t2" })).toBe(false);
  });

  it("stop() calls abortRun() on the in-flight agent and returns true", async () => {
    const runner = new PassthroughRunner();
    let resolveRun: () => void = () => {};
    const agent = new DiagramHttpAgent({ url: "http://backend:8001/agui" });
    agent.subscribe = vi.fn(() => ({ unsubscribe: vi.fn() })) as AbstractAgent["subscribe"];
    agent.runAgent = vi.fn(
      () => new Promise((resolve) => { resolveRun = () => resolve({} as never); }),
    ) as AbstractAgent["runAgent"];
    agent.abortRun = vi.fn();

    const sub = runner.run({ threadId: "t3", agent: agent as unknown as AbstractAgent, input: { threadId: "t3", runId: "r1", messages: [] } as never }).subscribe();
    expect(await runner.isRunning({ threadId: "t3" })).toBe(true);

    const stopped = await runner.stop({ threadId: "t3" });
    expect(stopped).toBe(true);
    expect(agent.abortRun).toHaveBeenCalledOnce();

    resolveRun();
    sub.unsubscribe();
  });

  it("stop() on an unknown thread returns false", async () => {
    const runner = new PassthroughRunner();
    expect(await runner.stop({ threadId: "never-ran" })).toBe(false);
  });

  describe("connect()", () => {
    // Found live (Stage 3 Playwright verification against the real backend):
    // @copilotkit/core's connectAgent() unconditionally clears agent
    // messages/state on every "fresh restore" (any thread switch), expecting
    // the runner's connect() stream to replay history and repopulate them.
    // connect() returning EMPTY (the original design) meant every
    // conversation switch silently wiped the chat to blank — CopilotKit's
    // own clear ran, and nothing ever refilled it. This suite locks in the
    // fix: connect() fetches the backend's history REST endpoint and
    // replays it as MESSAGES_SNAPSHOT + STATE_SNAPSHOT — bracketed by
    // RUN_STARTED/RUN_FINISHED, since @ag-ui/client's event-order verifier
    // rejects ANY stream (run or connect) that doesn't open with
    // RUN_STARTED ("AGUIError: First event must be 'RUN_STARTED'") — found
    // on the first attempt at this same fix, which emitted the snapshots
    // unbracketed.

    const originalFetch = global.fetch;
    afterEach(() => {
      global.fetch = originalFetch;
    });

    function eventTypes(events: unknown[]): string[] {
      return events.map((e) => (e as { type: string }).type);
    }

    it("replays history as RUN_STARTED, MESSAGES_SNAPSHOT, STATE_SNAPSHOT, RUN_FINISHED on a 200 response", async () => {
      const messages = [{ id: "u1", role: "user", content: "hello" }];
      const state = { current_step: "done" };
      global.fetch = vi.fn(
        async () =>
          new Response(JSON.stringify({ name: "t", messages, state }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
      ) as unknown as typeof fetch;

      const runner = new PassthroughRunner();
      const received = await firstValueFrom(runner.connect({ threadId: "thread-1" }).pipe(toArray()));

      expect(eventTypes(received)).toEqual([
        "RUN_STARTED",
        "MESSAGES_SNAPSHOT",
        "STATE_SNAPSHOT",
        "RUN_FINISHED",
      ]);
      expect(received[1]).toEqual({ type: "MESSAGES_SNAPSHOT", messages });
      expect(received[2]).toEqual({ type: "STATE_SNAPSHOT", snapshot: state });
    });

    it("still opens/closes with RUN_STARTED/RUN_FINISHED on a 404 (genuinely new thread)", async () => {
      global.fetch = vi.fn(async () => new Response("not found", { status: 404 })) as unknown as typeof fetch;

      const runner = new PassthroughRunner();
      const received = await firstValueFrom(runner.connect({ threadId: "brand-new" }).pipe(toArray()));

      expect(eventTypes(received)).toEqual(["RUN_STARTED", "RUN_FINISHED"]);
    });

    it("still opens/closes with RUN_STARTED/RUN_FINISHED (does not throw) when the backend is unreachable", async () => {
      global.fetch = vi.fn(async () => {
        throw new Error("ECONNREFUSED");
      }) as unknown as typeof fetch;

      const runner = new PassthroughRunner();
      const received = await firstValueFrom(runner.connect({ threadId: "t1" }).pipe(toArray()));

      expect(eventTypes(received)).toEqual(["RUN_STARTED", "RUN_FINISHED"]);
    });

    it("forwards the connect request's headers to the history fetch", async () => {
      const fetchMock = vi.fn(
        async () => new Response(JSON.stringify({ name: "t", messages: [], state: {} }), { status: 200 }),
      );
      global.fetch = fetchMock as unknown as typeof fetch;

      const runner = new PassthroughRunner();
      await firstValueFrom(
        runner
          .connect({ threadId: "t1", headers: { authorization: "Bearer xyz" } })
          .pipe(toArray()),
      );

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/conversations/t1/history"),
        expect.objectContaining({ headers: { authorization: "Bearer xyz" } }),
      );
    });
  });
});
