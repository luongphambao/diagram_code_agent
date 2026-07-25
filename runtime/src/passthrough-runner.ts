import {
  AgentRunner,
  type AgentRunnerConnectRequest,
  type AgentRunnerIsRunningRequest,
  type AgentRunnerRunRequest,
  type AgentRunnerStopRequest,
} from "@copilotkit/runtime/v2";
import type { AbstractAgent, BaseEvent } from "@ag-ui/client";
import { Observable } from "rxjs";
import { CONFIG } from "./config.js";

interface ConversationHistoryResponse {
  name: string;
  messages: unknown[];
  state: Record<string, unknown>;
}

/**
 * `InMemoryAgentRunner` (the built-in default) keeps a module-global
 * `Map<threadId, {subject: ReplaySubject<BaseEvent>(Infinity), historicRuns}>`
 * that never evicts (verified in
 * CopilotKit/packages/runtime/src/v2/runtime/runner/in-memory.ts). Our
 * STATE_SNAPSHOT carries base64 png/pdf/pptx/xlsx — several MB per run — so
 * that store grows without bound across a session.
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

  /**
   * Replays a thread's history as one MESSAGES_SNAPSHOT + one STATE_SNAPSHOT,
   * fetched from the Python backend's existing `GET /conversations/{id}/history`
   * (backend/src/routers/conversations.py) — not from any event log this
   * runner keeps itself (it keeps none; see the class doc comment).
   *
   * This is NOT optional polish — found live (Stage 3 Playwright verification
   * against the real backend): `copilotkit.connectAgent()`
   * (@copilotkit/core/src/core/run-handler.ts:281-283) unconditionally does
   * `agent.setMessages([]); agent.setState({})` on every "fresh restore" (any
   * thread switch), on the assumption that the runner's `connect()` stream
   * will replay history to repopulate them. `<CopilotChat>` calls
   * `connectAgent()` itself whenever `hasExplicitThreadId` is true — i.e. on
   * every thread switch in this app. Returning `EMPTY` here (the original
   * design, reasoning that Python already persists history so the runner
   * doesn't need to) meant every conversation switch silently wiped the chat
   * to blank: CopilotKit's OWN clear ran, and nothing ever repopulated it.
   */
  connect(request: AgentRunnerConnectRequest): Observable<BaseEvent> {
    return new Observable<BaseEvent>((subscriber) => {
      const headers: Record<string, string> = { ...(request.headers ?? {}) };
      const url = `${CONFIG.backendUrl}/conversations/${encodeURIComponent(request.threadId)}/history`;

      fetch(url, { headers })
        .then(async (res) => {
          if (res.status === 404) {
            // A genuinely new thread (never run) — nothing to replay, matches
            // the pre-fix EMPTY behavior for this specific case.
            subscriber.complete();
            return;
          }
          if (!res.ok) {
            throw new Error(`GET ${url} -> HTTP ${res.status}`);
          }
          const history = (await res.json()) as ConversationHistoryResponse;
          if (Array.isArray(history.messages) && history.messages.length > 0) {
            subscriber.next({ type: "MESSAGES_SNAPSHOT", messages: history.messages } as unknown as BaseEvent);
          }
          if (history.state && Object.keys(history.state).length > 0) {
            subscriber.next({ type: "STATE_SNAPSHOT", snapshot: history.state } as unknown as BaseEvent);
          }
          subscriber.complete();
        })
        .catch((error: unknown) => {
          // A transient backend hiccup shouldn't hard-error the whole chat
          // mount — complete with nothing replayed rather than reject.
          console.error(`[runtime] connect() history replay failed for ${request.threadId}:`, error);
          subscriber.complete();
        });

      return () => {};
    });
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
