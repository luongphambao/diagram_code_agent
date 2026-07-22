import { useState, useRef, useCallback, useEffect } from "react";
import { useAgentStream } from "./useAgentStream";
import { BACKEND_URL, loadGateHistory, saveGateHistory } from "./agent-utils";

// Re-export all types so callers keep their existing imports unchanged.
export type {
  AgentState,
  ArchitectureAnalysis,
  Blueprint,
  ChatMessage,
  ComplianceControl,
  ComplianceState,
  CostRange,
  DataAssumptions,
  DecisionAction,
  DecisionPayload,
  Delegation,
  DiagramBrief,
  DriftEntry,
  DriftReport,
  InterruptType,
  QualitySnapshot,
  LogEntry,
  PendingInterrupt,
  ResolvedGate,
  ScalingPhase,
  SolutionAssumptions,
  TeamAssumptions,
  TechAlternative,
  TechRisk,
  TechStackLayer,
  UploadedFile,
  UserScaleAssumptions,
  WbsSummary,
  WireMessage,
} from "./agent-utils";

import type {
  AgentState,
  ChatMessage,
  PendingInterrupt,
  ResolvedGate,
  UploadedFile,
  WireMessage,
} from "./agent-utils";

export function useDiagramAgent({
  threadId,
  userRole = "",
}: {
  threadId: string;
  userRole?: string;
}) {
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [agentState, setAgentState] = useState<AgentState>({});
  const [pendingInterrupt, setPendingInterrupt] = useState<PendingInterrupt | null>(null);
  const [gateHistory, setGateHistory] = useState<ResolvedGate[]>(() => loadGateHistory(threadId));
  const [isRunning, setIsRunning] = useState(false);
  const [activity, setActivity] = useState<string | null>(null);
  const [activeSubagent, setActiveSubagent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  const wireMessagesRef = useRef<WireMessage[]>([]);
  const threadIdRef = useRef(threadId);
  const userRoleRef = useRef(userRole);
  const lastTcIdRef = useRef<string>("");
  const agentStateRef = useRef<AgentState>(agentState);
  const pendingInterruptRef = useRef<PendingInterrupt | null>(null);
  const chatMessagesRef = useRef<ChatMessage[]>(chatMessages);

  useEffect(() => {
    threadIdRef.current = threadId;
  }, [threadId]);

  useEffect(() => {
    userRoleRef.current = userRole;
  }, [userRole]);

  useEffect(() => {
    agentStateRef.current = agentState;
  }, [agentState]);

  useEffect(() => {
    pendingInterruptRef.current = pendingInterrupt;
  }, [pendingInterrupt]);

  useEffect(() => {
    chatMessagesRef.current = chatMessages;
  }, [chatMessages]);

  // Persist the resolved-gate timeline for this thread whenever it changes.
  useEffect(() => {
    saveGateHistory(threadId, gateHistory);
  }, [threadId, gateHistory]);

  const uploadedFileIds = useCallback(() => uploadedFiles.map((f) => f.file_id), [uploadedFiles]);

  const { runAgent, abortRun } = useAgentStream({
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
  });

  const sendMessage = useCallback(
    async (content: string) => {
      const msgId = `msg-${Date.now()}`;
      setChatMessages((prev) => [...prev, { id: msgId, role: "user", content }]);
      setIsRunning(true);
      setAgentState((prev) => ({
        png_base64: prev.png_base64,
        pdf_base64: prev.pdf_base64,
        pptx_base64: prev.pptx_base64,
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
    [runAgent],
  );

  const _resolveWithPayload = useCallback(
    async (payload: Record<string, unknown>) => {
      const tcId = lastTcIdRef.current;
      if (!tcId) return;

      const resolved = pendingInterruptRef.current;
      if (resolved) {
        setGateHistory((prev) => [
          ...prev,
          {
            id: resolved.toolCallId,
            data: resolved.data,
            decision: payload,
            resolvedAt: Date.now(),
            afterMessageIndex: chatMessagesRef.current.length,
          },
        ]);
      }
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
    [runAgent],
  );

  // Every HITL gate (tech-stack, blueprint, WBS, exports, ...) resolves through
  // this single dispatcher — the backend treats them all identically as a tool
  // result keyed by toolCallId, so there's no need for 12 near-duplicate wrappers.
  const resolveGate = useCallback(
    async (payload: Record<string, unknown>) => {
      await _resolveWithPayload(payload);
    },
    [_resolveWithPayload],
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

  const restore = useCallback(
    (
      savedState: AgentState,
      savedChat: ChatMessage[],
      savedWire: WireMessage[],
      savedGateHistory: ResolvedGate[] = [],
    ) => {
      setChatMessages(savedChat);
      setAgentState(savedState);
      wireMessagesRef.current = savedWire;
      setPendingInterrupt(null);
      setGateHistory(savedGateHistory);
      setError(null);
      setActivity(null);
      setActiveSubagent(null);
      setUploadedFiles([]);
    },
    [],
  );

  const resetToNew = useCallback(() => {
    setChatMessages([]);
    setAgentState({});
    wireMessagesRef.current = [];
    setPendingInterrupt(null);
    setGateHistory([]);
    setError(null);
    setActivity(null);
    setActiveSubagent(null);
    setUploadedFiles([]);
  }, []);

  return {
    chatMessages,
    agentState,
    pendingInterrupt,
    gateHistory,
    isRunning,
    activity,
    activeSubagent,
    error,
    uploadedFiles,
    isUploading,
    sendMessage,
    resolveGate,
    abortRun,
    uploadFile,
    clearFiles,
    restore,
    resetToNew,
    threadId: threadIdRef.current,
  };
}
