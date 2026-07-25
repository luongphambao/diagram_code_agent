import { describe, expect, it, vi } from "vitest";
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

  it("connect() returns an empty stream — no server-side replay (plan §A.5/R7)", async () => {
    const runner = new PassthroughRunner();
    const received = await firstValueFrom(runner.connect({ threadId: "t1" }).pipe(toArray()), {
      defaultValue: "EMPTY_COMPLETED" as const,
    });
    expect(received).toBe("EMPTY_COMPLETED");
  });
});
