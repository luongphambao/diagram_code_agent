import { useState, useRef, useCallback, useEffect } from "react";
import { useAgentStream } from "./useAgentStream";
import { BACKEND_URL } from "./agent-utils";

// Re-export all types so callers keep their existing imports unchanged.
export type {
  AgentState,
  ArchitectureAnalysis,
  Blueprint,
  ChatMessage,
  CostRange,
  DataAssumptions,
  DecisionAction,
  DecisionPayload,
  Delegation,
  DiagramBrief,
  InterruptType,
  LogEntry,
  PendingInterrupt,
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
  DecisionPayload,
  PendingInterrupt,
  UploadedFile,
  WireMessage,
} from "./agent-utils";

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

  const uploadedFileIds = useCallback(
    () => uploadedFiles.map((f) => f.file_id),
    [uploadedFiles]
  );

  const { runAgent } = useAgentStream({
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
    [runAgent]
  );

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

  const resolvePptProposal = useCallback(
    async (approved: boolean, modifications?: string) => {
      await _resolveWithPayload({ approved, modifications: modifications?.trim() || null });
    },
    [_resolveWithPayload]
  );

  const resolveEmail = useCallback(
    async (approved: boolean) => { await _resolveWithPayload({ approved }); },
    [_resolveWithPayload]
  );

  const resolveMeeting = useCallback(
    async (approved: boolean) => { await _resolveWithPayload({ approved }); },
    [_resolveWithPayload]
  );

  const resolveMeetingSlot = useCallback(
    async (approved: boolean, selectedSlot?: { start: string; end: string; display_day: string; display_time: string }) => {
      await _resolveWithPayload({ approved, selected_slot: selectedSlot });
    },
    [_resolveWithPayload]
  );

  const resolveWbsSkeleton = useCallback(
    async (approved: boolean, modifications?: string) => {
      await _resolveWithPayload({ approved, modifications: modifications?.trim() || null });
    },
    [_resolveWithPayload]
  );

  const resolveWbs = useCallback(
    async (approved: boolean, modifications?: string) => {
      await _resolveWithPayload({ approved, modifications: modifications?.trim() || null });
    },
    [_resolveWithPayload]
  );

  const resolveWbsExcel = useCallback(
    async (approved: boolean) => { await _resolveWithPayload({ approved }); },
    [_resolveWithPayload]
  );

  // HITL v2: post a structured trade-off decision (accept_risk, request_evidence, ...).
  const resolveDecision = useCallback(
    async (payload: DecisionPayload) => { await _resolveWithPayload({ ...payload }); },
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
    resolvePptProposal,
    resolveEmail,
    resolveMeeting,
    resolveMeetingSlot,
    resolveWbsSkeleton,
    resolveWbs,
    resolveWbsExcel,
    resolveDecision,
    uploadFile,
    clearFiles,
    restore,
    resetToNew,
    threadId: threadIdRef.current,
  };
}
