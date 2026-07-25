import {
  AgentRunner,
  type AgentRunnerConnectRequest,
  type AgentRunnerIsRunningRequest,
  type AgentRunnerRunRequest,
  type AgentRunnerStopRequest,
} from "@copilotkit/runtime/v2";
import type { AbstractAgent, BaseEvent } from "@ag-ui/client";
import { EMPTY, Observable } from "rxjs";

/**
 * `InMemoryAgentRunner` (the built-in default) keeps a module-global
 * `Map<threadId, {subject: ReplaySubject<BaseEvent>(Infinity), historicRuns}>`
 * that never evicts (verified in
 * CopilotKit/packages/runtime/src/v2/runtime/runner/in-memory.ts). Our
 * STATE_SNAPSHOT carries base64 png/pdf/pptx/xlsx — several MB per run — so
 * that store grows without bound across a session.
 *
 * We don't need server-side reconnect-after-refresh (InMemoryAgentRunner's
 * `connect()` replays historic events for that): the Python backend already
 * persists full conversation history (`GET /conversations/{id}/history`,
 * consumed by frontend/src/hooks/useConversations.ts), so the browser
 * rehydrates from there instead. This runner streams each run's events
 * straight through and retains nothing.
 */
export class PassthroughRunner extends AgentRunner {
  private readonly inflight = new Map<string, AbstractAgent>();

  run(request: AgentRunnerRunRequest): Observable<BaseEvent> {
    return new Observable<BaseEvent>((subscriber) => {
      this.inflight.set(request.threadId, request.agent);

      const subscription = request.agent.subscribe({
        onEvent: ({ event }) => subscriber.next(event),
      });

      request.agent
        .runAgent({ forwardedProps: request.input.forwardedProps })
        .then(() => subscriber.complete())
        .catch((error: unknown) => subscriber.error(error))
        .finally(() => {
          subscription.unsubscribe();
          if (this.inflight.get(request.threadId) === request.agent) {
            this.inflight.delete(request.threadId);
          }
        });

      return () => {
        subscription.unsubscribe();
        if (this.inflight.get(request.threadId) === request.agent) {
          this.inflight.delete(request.threadId);
        }
      };
    });
  }

  /** No server-side replay: conversation history comes from Python, not
   *  from this runner. Anything hitting `/agent/:id/connect` gets an empty
   *  stream rather than an error (see risk R7 in the plan). */
  connect(_request: AgentRunnerConnectRequest): Observable<BaseEvent> {
    return EMPTY;
  }

  async isRunning(request: AgentRunnerIsRunningRequest): Promise<boolean> {
    return this.inflight.has(request.threadId);
  }

  async stop(request: AgentRunnerStopRequest): Promise<boolean> {
    const agent = this.inflight.get(request.threadId);
    if (!agent) return false;
    agent.abortRun();
    return true;
  }
}
