import { useState, useRef, useCallback, useEffect } from "react";

function applyOps(
  state: Record<string, unknown>,
  ops: Array<{ op: string; path: string; value: unknown }>
): Record<string, unknown> {
  const next = { ...state };
  for (const op of ops) {
    const key = op.path.slice(1);
    if (op.op === "add" || op.op === "replace") {
      next[key] = op.value;
    } else if (op.op === "remove") {
      delete next[key];
    }
  }
  return next;
}

export interface LogEntry {
  t: number;
  type: "llm" | "tool_start";
  model?: string;
  turn?: number;
  tool?: string;
  input?: string;
  output?: string;
  elapsed_s?: number;
  error?: string;
}

export interface TechStackLayer {
  choice: string;
  rationale: string;
  alternatives: string[];
}

export interface Blueprint {
  pattern: string;
  pattern_rationale?: string;
  key_decisions?: string[];
  nodes: Array<{ id: string; label: string; tech?: string; cluster?: string; type?: string }>;
  clusters: Array<{ id: string; label: string; tier?: string }>;
  edges: Array<{ from: string; to: string; label?: string; protocol?: string }>;
}

export interface Delegation {
  id: string;
  subagent: string;
  description: string;
  status: "running" | "completed" | "error";
  result?: string | null;
  current_tool?: string;
  current_label?: string;
}

export interface AgentState {
  current_step?: string;
  iteration?: number;
  png_base64?: string;
  drawio?: string;
  code?: string;
  summary?: string;
  error?: string;
  logs?: LogEntry[];
  tech_stack?: Record<string, TechStackLayer>;
  blueprint?: Blueprint;
  delegations?: Delegation[];
  activeSubagent?: string;
}

export type InterruptType =
  | "techstack_approval"
  | "blueprint_approval"
  | "result_review";

export interface PendingInterrupt {
  toolCallId: string;
  data: {
    type: InterruptType;
    question: string;
    // techstack_approval
    tech_stack?: Record<string, TechStackLayer>;
    // blueprint_approval
    blueprint?: Blueprint;
    // result_review
    summary?: string;
    iteration?: number;
  };
}

export interface UploadedFile {
  file_id: string;
  filename: string;
  kind: string;
  char_count: number;
  preview?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

interface WireMessage {
  id: string;
  role: string;
  content: string;
  toolCallId?: string;
}

const BACKEND_URL =
  (import.meta.env.VITE_BACKEND_URL as string | undefined) ??
  "http://localhost:8001";

export function useDiagramAgent({ threadId }: { threadId: string }) {
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [agentState, setAgentState] = useState<AgentState>({});
  const [pendingInterrupt, setPendingInterrupt] = useState<PendingInterrupt | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [activity, setActivity] = useState<string | null>(null);
  const [activeSubagent, setActiveSubagent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  const wireMessagesRef = useRef<WireMessage[]>([]);
  const threadIdRef = useRef(threadId);
  const lastTcIdRef = useRef<string>("");

  useEffect(() => {
    threadIdRef.current = threadId;
  }, [threadId]);

  const runAgent = useCallback(async (messages: WireMessage[]) => {
    setIsRunning(true);
    setError(null);
    const runId = `run-${Date.now()}`;
    const fileIds = uploadedFiles.map((f) => f.file_id);

    try {
      const response = await fetch(`${BACKEND_URL}/agui`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          threadId: threadIdRef.current,
          runId,
          messages,
          file_ids: fileIds,
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
              setChatMessages((prev) => [...prev, { id: msgId, role: "assistant", content: "" }]);
              break;
            }

            case "TEXT_MESSAGE_CONTENT": {
              const msgId = evt.messageId as string;
              const delta = evt.delta as string;
              setChatMessages((prev) =>
                prev.map((m) => m.id === msgId ? { ...m, content: m.content + delta } : m)
              );
              break;
            }

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
              const subagent = evt.subagent as string | undefined;
              if (phase === "start") {
                setActivity(label);
                if (subagent) setActiveSubagent(subagent);
                setAgentState((prev) => ({
                  ...prev,
                  logs: [...(prev.logs ?? []), { t: 0, type: "tool_start", tool, input: label }],
                }));
              } else if (phase === "end") {
                // Clear active subagent when its task tool completes.
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
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsRunning(false);
      setActivity(null);
      setActiveSubagent(null);
    }
  }, [uploadedFiles]);

  const sendMessage = useCallback(
    async (content: string) => {
      const msgId = `msg-${Date.now()}`;
      setChatMessages((prev) => [...prev, { id: msgId, role: "user", content }]);
      setAgentState({});
      setPendingInterrupt(null);
      setError(null);

      const updated: WireMessage[] = [
        ...wireMessagesRef.current,
        { id: msgId, role: "user", content },
      ];
      wireMessagesRef.current = updated;
      await runAgent(updated);
    },
    [runAgent]
  );

  // Resolve a HITL gate: append a tool-result message and resume the run.
  const _resolveWithPayload = useCallback(
    async (payload: Record<string, unknown>) => {
      const tcId = lastTcIdRef.current;
      if (!tcId) return;
      setPendingInterrupt(null);

      const toolResult: WireMessage = {
        id: `tool-${Date.now()}`,
        role: "tool",
        content: JSON.stringify(payload),
        toolCallId: tcId,
      };
      const updated: WireMessage[] = [...wireMessagesRef.current, toolResult];
      wireMessagesRef.current = updated;
      await runAgent(updated);
    },
    [runAgent]
  );

  const resolveTechStack = useCallback(
    async (approved: boolean, modifications?: string) => {
      await _resolveWithPayload({ approved, modifications: modifications?.trim() || null });
    },
    [_resolveWithPayload]
  );

  const resolveBlueprint = useCallback(
    async (approved: boolean, modifications?: string) => {
      await _resolveWithPayload({ approved, modifications: modifications?.trim() || null });
    },
    [_resolveWithPayload]
  );

  const resolveResultReview = useCallback(
    async (satisfied: boolean, feedback?: string) => {
      await _resolveWithPayload({ satisfied, feedback: feedback?.trim() || null });
    },
    [_resolveWithPayload]
  );

  const uploadFile = useCallback(async (file: File) => {
    setIsUploading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${BACKEND_URL}/upload`, { method: "POST", body: formData });
      if (!res.ok) throw new Error(`Upload failed: HTTP ${res.status}`);
      const data = (await res.json()) as UploadedFile;
      setUploadedFiles((prev) => [...prev, data]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsUploading(false);
    }
  }, []);

  const clearFiles = useCallback(() => setUploadedFiles([]), []);

  // Restore a past conversation (used when switching conversations in the sidebar).
  const restore = useCallback((
    savedState: AgentState,
    savedChat: ChatMessage[],
    savedWire: WireMessage[],
  ) => {
    setChatMessages(savedChat);
    setAgentState(savedState);
    wireMessagesRef.current = savedWire;
    setPendingInterrupt(null);
    setError(null);
    setActivity(null);
    setActiveSubagent(null);
    setUploadedFiles([]);
  }, []);

  // Clear to blank for a new conversation.
  const resetToNew = useCallback(() => {
    setChatMessages([]);
    setAgentState({});
    wireMessagesRef.current = [];
    setPendingInterrupt(null);
    setError(null);
    setActivity(null);
    setActiveSubagent(null);
    setUploadedFiles([]);
  }, []);

  return {
    chatMessages,
    agentState,
    pendingInterrupt,
    isRunning,
    activity,
    activeSubagent,
    error,
    uploadedFiles,
    isUploading,
    sendMessage,
    resolveTechStack,
    resolveBlueprint,
    resolveResultReview,
    uploadFile,
    clearFiles,
    restore,
    resetToNew,
    threadId: threadIdRef.current,
  };
}
