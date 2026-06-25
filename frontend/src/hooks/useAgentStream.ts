/** SSE streaming: reads the /agui event stream and dispatches state updates. */

import { useCallback, useRef } from "react";
import {
  AgentState,
  PendingInterrupt,
  WireMessage,
  BACKEND_URL,
  applyOps,
} from "./agent-utils";

interface UseAgentStreamOptions {
  threadIdRef: React.MutableRefObject<string>;
  uploadedFileIds: () => string[];
  setAgentState: React.Dispatch<React.SetStateAction<AgentState>>;
  setIsRunning: React.Dispatch<React.SetStateAction<boolean>>;
  setActivity: React.Dispatch<React.SetStateAction<string | null>>;
  setActiveSubagent: React.Dispatch<React.SetStateAction<string | null>>;
  setError: React.Dispatch<React.SetStateAction<string | null>>;
  setPendingInterrupt: React.Dispatch<React.SetStateAction<PendingInterrupt | null>>;
  setChatMessages: React.Dispatch<React.SetStateAction<Array<{ id: string; role: "user" | "assistant"; content: string }>>>;
  wireMessagesRef: React.MutableRefObject<WireMessage[]>;
  lastTcIdRef: React.MutableRefObject<string>;
}

export function useAgentStream({
  threadIdRef,
  uploadedFileIds,
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

  const runAgent = useCallback(async (messages: WireMessage[]) => {
    setIsRunning(true);
    setError(null);
    const runId = `run-${Date.now()}`;

    try {
      const response = await fetch(`${BACKEND_URL}/agui`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          threadId: threadIdRef.current,
          runId,
          messages,
          file_ids: uploadedFileIds(),
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let activeTcId = "";
      let activeTcArgs = "";
      let currentAssistantMsg: WireMessage | null = null;
      const pendingAssistantMsgs: WireMessage[] = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";

        for (const frame of frames) {
          const dataLine = frame.split("\n").filter((l) => l.startsWith("data: ")).pop();
          if (!dataLine) continue;
          const raw = dataLine.slice(6).trim();
          if (!raw) continue;

          let evt: Record<string, unknown>;
          try { evt = JSON.parse(raw); } catch { continue; }

          switch (evt.type as string) {
            case "STATE_SNAPSHOT":
              setAgentState((prev) => ({ ...prev, ...(evt.snapshot as AgentState) }));
              break;

            case "STATE_DELTA": {
              const ops = evt.delta as Array<{ op: string; path: string; value: unknown }>;
              setAgentState((prev) => applyOps(prev as Record<string, unknown>, ops) as AgentState);
              break;
            }

            case "TEXT_MESSAGE_START": {
              const msgId = evt.messageId as string;
              currentAssistantMsg = { id: msgId, role: "assistant", content: "" };
              setChatMessages((prev) => [...prev, { id: msgId, role: "assistant", content: "" }]);
              break;
            }

            case "TEXT_MESSAGE_CONTENT": {
              const msgId = evt.messageId as string;
              const delta = evt.delta as string;
              if (currentAssistantMsg?.id === msgId) {
                currentAssistantMsg.content += delta;
              }
              setChatMessages((prev) =>
                prev.map((m) => m.id === msgId ? { ...m, content: m.content + delta } : m)
              );
              break;
            }

            case "TEXT_MESSAGE_END":
              if (currentAssistantMsg) {
                pendingAssistantMsgs.push({ ...currentAssistantMsg });
                currentAssistantMsg = null;
              }
              break;

            case "TOOL_CALL_START":
              activeTcId = evt.toolCallId as string;
              activeTcArgs = "";
              break;

            case "TOOL_CALL_ARGS":
              activeTcArgs += evt.delta as string;
              break;

            case "TOOL_CALL_END":
              try {
                const data = JSON.parse(activeTcArgs) as PendingInterrupt["data"];
                lastTcIdRef.current = activeTcId;
                setPendingInterrupt({ toolCallId: activeTcId, data });
              } catch { /* malformed */ }
              activeTcId = "";
              activeTcArgs = "";
              break;

            case "ACTIVITY": {
              const phase = evt.phase as string;
              const tool = evt.tool as string;
              const label = (evt.label as string) || tool;
              const detail = evt.detail as string | undefined;
              const subagent = evt.subagent as string | undefined;
              const ok = evt.ok as boolean | undefined;
              const display = detail ? `${label}: ${detail}` : label;
              const key = `${subagent ?? "main"}:${tool}`;
              if (phase === "start") {
                toolStartTimesRef.current[key] = Date.now();
                setActivity(display);
                if (subagent) setActiveSubagent(subagent);
                setAgentState((prev) => ({
                  ...prev,
                  logs: [
                    ...(prev.logs ?? []),
                    { t: 0, type: "tool_start", tool, label, input: detail ?? "", subagent },
                  ],
                }));
              } else if (phase === "end") {
                const started = toolStartTimesRef.current[key];
                const elapsed_s = started ? Number(((Date.now() - started) / 1000).toFixed(1)) : undefined;
                delete toolStartTimesRef.current[key];
                setAgentState((prev) => ({
                  ...prev,
                  logs: [
                    ...(prev.logs ?? []),
                    {
                      t: 0,
                      type: "tool_end",
                      tool,
                      label,
                      output: detail ?? "",
                      error: ok === false ? detail || "Tool returned an error" : undefined,
                      elapsed_s,
                      subagent,
                      ok,
                    },
                  ],
                }));
                if (tool === "task") setActiveSubagent(null);
              }
              break;
            }

            case "RUN_ERROR":
              setError((evt.message as string) || "Agent returned an error");
              break;

            default:
              break;
          }
        }
      }

      if (currentAssistantMsg) {
        pendingAssistantMsgs.push({ ...currentAssistantMsg });
      }
      if (pendingAssistantMsgs.length > 0) {
        wireMessagesRef.current = [...wireMessagesRef.current, ...pendingAssistantMsgs];
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsRunning(false);
      setActivity(null);
      setActiveSubagent(null);
    }
  }, [
    threadIdRef, uploadedFileIds, setAgentState, setIsRunning, setActivity,
    setActiveSubagent, setError, setPendingInterrupt, setChatMessages,
    wireMessagesRef, lastTcIdRef,
  ]);

  return { runAgent };
}
