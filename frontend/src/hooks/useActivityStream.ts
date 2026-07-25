/**
 * Ports the CUSTOM `activity` event + RUN_ERROR handling from the old
 * useAgentStream.ts (plan §E.1/E.5) onto CopilotKit's `useAgent()` — the only
 * genuinely custom event handling this app needs; CopilotKit has no built-in
 * equivalent since `useRenderActivityMessage` consumes a DIFFERENT mechanism
 * (ACTIVITY_SNAPSHOT/DELTA "activity" ROLE messages) than our backend's
 * CUSTOM-event-with-name="activity" (backend/src/routers/chat.py:65-85).
 *
 * Logs live in local React state here rather than being merged back into
 * `agent.state` (the old subscriber's `return {state}` at
 * useAgentStream.ts:180) — that pattern triggered a full onStateChanged
 * cascade on every single activity tick; keeping them local avoids it.
 */
import { useEffect, useRef, useState } from "react";
import { useAgent, UseAgentUpdate } from "@copilotkit/react-core/v2";
import type { LogEntry } from "./agent-utils";

interface ActivityPayload {
  phase: "start" | "end";
  tool: string;
  label?: string;
  detail?: string;
  subagent?: string;
  ok?: boolean;
}

export interface ActivityStreamState {
  activity: string | null;
  activeSubagent: string | null;
  logs: LogEntry[];
  error: { message: string; code?: string } | null;
}

export function useActivityStream(): ActivityStreamState {
  // Only need run-status transitions to reset per-run state; message/state
  // re-renders are handled separately by useDiagramWorkspace's own useAgent
  // call (multiple useAgent() calls for the same agentId share one
  // underlying AbstractAgent instance — verified against
  // CopilotKit/packages/react-core/src/v2/hooks/use-agent.tsx).
  const { agent, isReady } = useAgent({ updates: [UseAgentUpdate.OnRunStatusChanged] });
  const [activity, setActivity] = useState<string | null>(null);
  const [activeSubagent, setActiveSubagent] = useState<string | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [error, setError] = useState<{ message: string; code?: string } | null>(null);
  const toolStartTimesRef = useRef<Record<string, number>>({});

  useEffect(() => {
    if (!isReady) return;

    const subscription = agent.subscribe({
      onRunInitialized: () => {
        setError(null);
        setLogs([]);
      },
      onCustomEvent: ({ event }) => {
        if (event.name !== "activity") return;
        const payload = event.value as ActivityPayload;
        const { phase, tool, subagent } = payload;
        const label = payload.label || tool;
        const display = payload.detail ? `${label}: ${payload.detail}` : label;
        const key = `${subagent ?? "main"}:${tool}`;

        if (phase === "start") {
          toolStartTimesRef.current[key] = Date.now();
          setActivity(display);
          if (subagent) setActiveSubagent(subagent);
          setLogs((prev) => [
            ...prev,
            { t: 0, type: "tool_start", tool, label, input: payload.detail ?? "", subagent },
          ]);
        } else {
          const started = toolStartTimesRef.current[key];
          const elapsed_s = started ? Number(((Date.now() - started) / 1000).toFixed(1)) : undefined;
          delete toolStartTimesRef.current[key];
          setLogs((prev) => [
            ...prev,
            {
              t: 0,
              type: "tool_end",
              tool,
              label,
              output: payload.detail ?? "",
              error: payload.ok === false ? payload.detail || "Tool returned an error" : undefined,
              elapsed_s,
              subagent,
              ok: payload.ok,
            },
          ]);
          if (tool === "task") setActiveSubagent(null);
        }
      },
      onRunErrorEvent: ({ event }) => {
        setError({ message: event.message || "Agent returned an error", code: (event as { code?: string }).code });
      },
      onRunFinalized: () => {
        setActivity(null);
        setActiveSubagent(null);
      },
    });

    return () => subscription.unsubscribe();
  }, [agent, isReady]);

  return { activity, activeSubagent, logs, error };
}
