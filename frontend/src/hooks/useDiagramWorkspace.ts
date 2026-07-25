/**
 * Replaces useDiagramAgent.ts's non-message-transport concerns (plan §E.1):
 * `chatMessages`/`wireMessagesRef`/`pendingInterrupt`/`resolveGate`/`sendMessage`
 * are all gone — CopilotKit's `<CopilotChat>` + `useHumanInTheLoop` own that
 * now. What survives: the `agent.state` mirror for DiagramCanvas, file
 * upload, the resolved-gate history timeline (localStorage), and
 * restore/resetToNew for conversation switching.
 */
import { useCallback, useEffect, useState } from "react";
import { useAgent, UseAgentUpdate } from "@copilotkit/react-core/v2";
import type { Message } from "@ag-ui/client";
import {
  BACKEND_URL,
  loadGateHistory,
  saveGateHistory,
  clearGateHistory,
} from "./agent-utils";
import type { AgentState, ResolvedGate, UploadedFile } from "./agent-utils";

const PRUNE_KEYS = ["png_base64", "pdf_base64", "pptx_base64", "drawio", "code", "iteration"] as const;

export function useDiagramWorkspace({ threadId }: { threadId: string }) {
  const { agent } = useAgent({ updates: [UseAgentUpdate.OnStateChanged] });
  const agentState = agent.state as AgentState;

  const [gateHistory, setGateHistory] = useState<ResolvedGate[]>(() => loadGateHistory(threadId));
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  useEffect(() => {
    saveGateHistory(threadId, gateHistory);
  }, [threadId, gateHistory]);

  // Load-bearing (plan §E.1): the old useDiagramAgent.ts:129-136 pruned
  // agentState down to just the base64 artifacts + iteration right before a
  // FRESH send, so stale stage-artifact panels (tech_stack, blueprint,
  // quality...) don't linger on screen mid-run. It deliberately did NOT do
  // this on a gate-resume (approve/reject) — only `sendMessage` pruned,
  // `resolveGate`/`_resolveWithPayload` never did. `onRunInitialized` fires
  // for BOTH cases here, so gate the prune on the last message actually
  // being a fresh user message (a resume's last message is role "tool").
  useEffect(() => {
    const subscription = agent.subscribe({
      onRunInitialized: ({ messages }) => {
        const last = messages[messages.length - 1];
        if (last?.role !== "user") return;
        const prev = agent.state as AgentState;
        const pruned: AgentState = {};
        for (const key of PRUNE_KEYS) {
          (pruned as Record<string, unknown>)[key] = prev[key];
        }
        agent.setState(pruned);
      },
    });
    return () => subscription.unsubscribe();
  }, [agent]);

  const uploadFile = useCallback(async (file: File) => {
    setIsUploading(true);
    setUploadError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${BACKEND_URL}/upload`, { method: "POST", body: formData });
      if (!res.ok) throw new Error(`Upload failed: HTTP ${res.status}`);
      const data = (await res.json()) as UploadedFile;
      setUploadedFiles((prev) => [...prev, data]);
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsUploading(false);
    }
  }, []);

  const clearFiles = useCallback(() => setUploadedFiles([]), []);
  const fileIds = uploadedFiles.map((f) => f.file_id);

  /** Conversation switch (plan §E.1): restoring a prior thread means syncing
   *  the shared agent instance's messages/state directly rather than local
   *  React state — CopilotChat reads `agent.messages` reactively. */
  const restore = useCallback(
    (savedState: AgentState, savedWireMessages: Message[], savedGateHistory: ResolvedGate[] = []) => {
      agent.setMessages(savedWireMessages);
      agent.setState(savedState);
      setGateHistory(savedGateHistory);
      setUploadedFiles([]);
      setUploadError(null);
    },
    [agent],
  );

  const resetToNew = useCallback(() => {
    agent.setMessages([]);
    agent.setState({});
    setGateHistory([]);
    setUploadedFiles([]);
    setUploadError(null);
  }, [agent]);

  const recordResolvedGate = useCallback((gate: ResolvedGate) => {
    setGateHistory((prev) => [...prev, gate]);
  }, []);

  return {
    agentState,
    gateHistory,
    recordResolvedGate,
    uploadedFiles,
    fileIds,
    isUploading,
    uploadError,
    uploadFile,
    clearFiles,
    restore,
    resetToNew,
  };
}

export function clearWorkspaceGateHistory(threadId: string) {
  clearGateHistory(threadId);
}
