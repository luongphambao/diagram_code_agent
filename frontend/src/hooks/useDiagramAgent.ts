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
  type: "llm" | "tool_start" | "tool_end";
  model?: string;
  turn?: number;
  tool?: string;
  label?: string;
  input?: string;
  output?: string;
  elapsed_s?: number;
  error?: string;
  subagent?: string;
  ok?: boolean;
}

export interface TechAlternative {
  name: string;
  why_rejected?: string;
  criteria?: Record<string, number>;
}

export interface CostRange {
  min_usd: number;
  max_usd: number;
}

export interface TechRisk {
  risk: string;
  mitigation?: string;
}

export interface UserScaleAssumptions {
  mau?: number;
  dau?: number;
  peak_concurrent?: number;
  peak_rps?: number;
  growth_rate_yoy_pct?: number;
}

export interface DataAssumptions {
  initial_gb?: number;
  growth_gb_per_month?: number;
  read_write_ratio?: string;
}

export interface TeamAssumptions {
  size?: number;
  skill_level?: string;
  devops_maturity?: string;
}

export interface SolutionAssumptions {
  budget_tier?: string;
  monthly_budget_range_usd?: CostRange;
  users?: UserScaleAssumptions;
  data?: DataAssumptions;
  team?: TeamAssumptions;
  project_phase?: string;
  availability_target?: string;
  latency_target_p99_ms?: number;
  compliance?: string[];
  primary_region?: string;
  confirm_with_customer?: string[];
}

export interface ScalingPhase {
  phase: string;
  trigger?: string;
  changes?: string[];
  est_monthly_cost_usd?: CostRange;
}

export interface TechStackLayer {
  choice: string;
  rationale: string;
  cost_tier?: string;
  decision_criteria?: Record<string, number>;
  alternatives: Array<string | TechAlternative>;
  estimated_monthly_cost_usd?: CostRange;
  capacity_sizing?: string;
  performance_target?: string;
  risks?: TechRisk[];
}

export interface DiagramBrief {
  objective: string;
  application_type?: string;
  scale_level?: string;
  security_level?: string;
  provider_preference?: string;
  analysis_signals?: string[];
  stakeholders?: string[];
  functional_requirements?: string[];
  non_functional_requirements?: string[];
  layout_constraints?: string[];
  assumptions?: string[];
}

export interface ArchitectureAnalysis {
  application_type: string;
  scale_level: string;
  security_level: string;
  provider_preference?: string;
  detected_capabilities: string[];
  constraints: string[];
  suggested_patterns: Array<{
    pattern: string;
    fit: "high" | "medium" | "low";
    score: number;
    reasons: string[];
  }>;
  concerns: string[];
}

export interface Blueprint {
  audience?: string;
  detail_level?: string;
  layout_intent?: string;
  presentation_style?: "slide" | "diagram";
  slide_title?: string;
  slide_kicker?: string;
  brand?: string;
  diagram_title?: string;
  pattern: string;
  pattern_rationale?: string;
  key_decisions?: string[];
  nodes: Array<{ id: string; label: string; tech?: string; cluster?: string; type?: string }>;
  clusters: Array<{ id: string; label: string; tier?: string }>;
  edges: Array<{ from: string; to: string; label?: string; protocol?: string }>;
  pillar_coverage?: Record<string, { addressed_by?: string[]; gaps?: string[] }>;
  nfr_mapping?: Array<{ nfr: string; mechanism?: string; node_ids?: string[] }>;
}

export interface Delegation {
  id: string;
  subagent: string;
  description: string;
  status: "running" | "completed" | "error";
  result?: string | null;
  current_tool?: string;
  current_label?: string;
  current_detail?: string;
}

export interface AgentState {
  current_step?: string;
  iteration?: number;
  png_base64?: string;
  pdf_base64?: string;
  drawio?: string;
  code?: string;
  summary?: string;
  error?: string;
  logs?: LogEntry[];
  architecture_analysis?: ArchitectureAnalysis;
  diagram_brief?: DiagramBrief;
  tech_stack?: Record<string, TechStackLayer>;
  blueprint?: Blueprint;
  delegations?: Delegation[];
  activeSubagent?: string;
}

export type InterruptType =
  | "techstack_approval"
  | "blueprint_approval"
  | "result_review"
  | "pdf_report_approval"
  | "email_approval";

export interface PendingInterrupt {
  toolCallId: string;
  data: {
    type: InterruptType;
    question: string;
    // techstack_approval
    tech_stack?: Record<string, TechStackLayer>;
    assumptions?: SolutionAssumptions;
    scaling_roadmap?: ScalingPhase[];
    estimated_total_monthly_cost_usd?: CostRange;
    // blueprint_approval
    blueprint?: Blueprint;
    // result_review
    summary?: string;
    iteration?: number;
    // pdf_report_approval
    title?: string;
    subtitle?: string;
    brand?: string;
    include_sections?: string[];
    missing_sections?: string[];
    // email_approval
    recipient_email?: string;
    subject?: string;
    project_name?: string;
    recipient_name?: string;
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
  const toolStartTimesRef = useRef<Record<string, number>>({});

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

            case "TEXT_MESSAGE_END": {
              if (currentAssistantMsg) {
                pendingAssistantMsgs.push({ ...currentAssistantMsg });
                currentAssistantMsg = null;
              }
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
      // Flush any in-flight assistant message (e.g. stream cut off before TEXT_MESSAGE_END)
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
  }, [uploadedFiles]);

  const sendMessage = useCallback(
    async (content: string) => {
      const msgId = `msg-${Date.now()}`;
      setChatMessages((prev) => [...prev, { id: msgId, role: "user", content }]);
      // Set isRunning=true in the SAME batch as agentState clear so DiagramCanvas
      // never sees a state where isRunning=false AND png_base64=undefined simultaneously.
      setIsRunning(true);
      setAgentState((prev) => ({
        png_base64: prev.png_base64,
        pdf_base64: prev.pdf_base64,
        drawio: prev.drawio,
        code: prev.code,
        iteration: prev.iteration,
      }));
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

  const resolvePdfReport = useCallback(
    async (approved: boolean, modifications?: string) => {
      await _resolveWithPayload({ approved, modifications: modifications?.trim() || null });
    },
    [_resolveWithPayload]
  );

  const resolveEmail = useCallback(
    async (approved: boolean) => {
      await _resolveWithPayload({ approved });
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
    resolvePdfReport,
    resolveEmail,
    uploadFile,
    clearFiles,
    restore,
    resetToNew,
    threadId: threadIdRef.current,
  };
}
