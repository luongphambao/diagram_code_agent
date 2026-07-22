/** AG-UI streaming: runs the /agui endpoint through @ag-ui/client's HttpAgent
 * and dispatches state/message updates via an AgentSubscriber. */

import { useCallback, useRef } from "react";
import { HttpAgent } from "@ag-ui/client";
import type { AgentSubscriber, Message, RunAgentInput } from "@ag-ui/client";
import { AgentState, LogEntry, PendingInterrupt, WireMessage, BACKEND_URL } from "./agent-utils";

interface UseAgentStreamOptions {
  threadIdRef: React.MutableRefObject<string>;
  userRoleRef: React.MutableRefObject<string>;
  uploadedFileIds: () => string[];
  agentStateRef: React.MutableRefObject<AgentState>;
  setAgentState: React.Dispatch<React.SetStateAction<AgentState>>;
  setIsRunning: React.Dispatch<React.SetStateAction<boolean>>;
  setActivity: React.Dispatch<React.SetStateAction<string | null>>;
  setActiveSubagent: React.Dispatch<React.SetStateAction<string | null>>;
  setError: React.Dispatch<React.SetStateAction<string | null>>;
  setPendingInterrupt: React.Dispatch<React.SetStateAction<PendingInterrupt | null>>;
  setChatMessages: React.Dispatch<
    React.SetStateAction<Array<{ id: string; role: "user" | "assistant"; content: string }>>
  >;
  wireMessagesRef: React.MutableRefObject<WireMessage[]>;
  lastTcIdRef: React.MutableRefObject<string>;
}

interface ActivityPayload {
  phase: "start" | "end";
  tool: string;
  label?: string;
  detail?: string;
  subagent?: string;
  ok?: boolean;
}

/** Backend reads a flat {threadId, runId, messages, file_ids, userRole} body
 * (backend/src/routers/chat.py:143-147) rather than the AG-UI wire shape
 * (forwardedProps/tools/context as separate top-level fields) — override the
 * request body while keeping HttpAgent's SSE parsing/state-apply pipeline. */
class DiagramHttpAgent extends HttpAgent {
  protected requestInit(input: RunAgentInput): RequestInit {
    const forwarded = (input.forwardedProps ?? {}) as { file_ids?: string[]; userRole?: string };
    return {
      method: "POST",
      headers: { ...this.headers, "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({
        threadId: input.threadId,
        runId: input.runId,
        messages: input.messages,
        file_ids: forwarded.file_ids ?? [],
        userRole: forwarded.userRole ?? "",
      }),
      signal: this.abortController.signal,
    };
  }
}

export function useAgentStream({
  threadIdRef,
  userRoleRef,
  uploadedFileIds,
  agentStateRef,
  setAgentState,
  setIsRunning,
  setActivity,
  setActiveSubagent,
  setError,
  setPendingInterrupt,
  setChatMessages,
  wireMessagesRef,
  lastTcIdRef,
}: UseAgentStreamOptions) {
  const toolStartTimesRef = useRef<Record<string, number>>({});
  const currentAgentRef = useRef<HttpAgent | null>(null);

  const runAgent = useCallback(
    async (messages: WireMessage[]) => {
      setIsRunning(true);
      setError(null);

      const agent = new DiagramHttpAgent({
        url: `${BACKEND_URL}/agui`,
        threadId: threadIdRef.current,
        initialState: agentStateRef.current,
        // HttpAgent invokes this as `this.fetch(...)`, which would call the
        // native fetch unbound from `window` ("Illegal invocation") — wrap it
        // in a closure so it's always called as a free function.
        fetch: (url, init) => fetch(url, init),
      });
      currentAgentRef.current = agent;
      agent.setMessages(messages as unknown as Message[]);

      const textBuffers: Record<string, string> = {};

      const subscriber: AgentSubscriber = {
        onTextMessageStartEvent: ({ event }) => {
          textBuffers[event.messageId] = "";
          setChatMessages((prev) => [
            ...prev,
            { id: event.messageId, role: "assistant", content: "" },
          ]);
        },
        onTextMessageContentEvent: ({ event }) => {
          textBuffers[event.messageId] = (textBuffers[event.messageId] ?? "") + event.delta;
          setChatMessages((prev) =>
            prev.map((m) =>
              m.id === event.messageId ? { ...m, content: m.content + event.delta } : m,
            ),
          );
        },
        onTextMessageEndEvent: ({ event }) => {
          const content = textBuffers[event.messageId] ?? "";
          wireMessagesRef.current = [
            ...wireMessagesRef.current,
            { id: event.messageId, role: "assistant", content },
          ];
        },

        onToolCallEndEvent: ({ event, toolCallArgs }) => {
          lastTcIdRef.current = event.toolCallId;
          setPendingInterrupt({
            toolCallId: event.toolCallId,
            data: toolCallArgs as PendingInterrupt["data"],
          });
        },

        onCustomEvent: ({ event, state }) => {
          if (event.name !== "activity") return;
          const payload = event.value as ActivityPayload;
          const { phase, tool, subagent } = payload;
          const label = payload.label || tool;
          const display = payload.detail ? `${label}: ${payload.detail}` : label;
          const key = `${subagent ?? "main"}:${tool}`;

          const prevLogs: LogEntry[] = Array.isArray((state as AgentState | undefined)?.logs)
            ? [...(state as AgentState).logs!]
            : [];
          let logs = prevLogs;

          if (phase === "start") {
            toolStartTimesRef.current[key] = Date.now();
            setActivity(display);
            if (subagent) setActiveSubagent(subagent);
            logs = [
              ...prevLogs,
              { t: 0, type: "tool_start", tool, label, input: payload.detail ?? "", subagent },
            ];
          } else {
            const started = toolStartTimesRef.current[key];
            const elapsed_s = started
              ? Number(((Date.now() - started) / 1000).toFixed(1))
              : undefined;
            delete toolStartTimesRef.current[key];
            logs = [
              ...prevLogs,
              {
                t: 0,
                type: "tool_end",
                tool,
                label,
                output: payload.detail ?? "",
                error:
                  payload.ok === false ? payload.detail || "Tool returned an error" : undefined,
                elapsed_s,
                subagent,
                ok: payload.ok,
              },
            ];
            if (tool === "task") setActiveSubagent(null);
          }
          return { state: { ...(state as AgentState), logs } };
        },

        onRunErrorEvent: ({ event }) => {
          setError(event.message || "Agent returned an error");
        },

        onStateChanged: ({ state }) => {
          setAgentState(state as AgentState);
        },
      };

      try {
        await agent.runAgent(
          { forwardedProps: { file_ids: uploadedFileIds(), userRole: userRoleRef.current } },
          subscriber,
        );
      } catch (e) {
        const isUserAbort = e instanceof DOMException && e.name === "AbortError";
        if (!isUserAbort) {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        setIsRunning(false);
        setActivity(null);
        setActiveSubagent(null);
        currentAgentRef.current = null;
      }
    },
    [
      threadIdRef,
      userRoleRef,
      uploadedFileIds,
      agentStateRef,
      setAgentState,
      setIsRunning,
      setActivity,
      setActiveSubagent,
      setError,
      setPendingInterrupt,
      setChatMessages,
      wireMessagesRef,
      lastTcIdRef,
    ],
  );

  const abortRun = useCallback(() => {
    currentAgentRef.current?.abortRun();
  }, []);

  return { runAgent, abortRun };
}
