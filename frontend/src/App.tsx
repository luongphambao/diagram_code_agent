import { useCallback, useEffect, useRef, useState } from "react";
import { useDiagramAgent } from "./hooks/useDiagramAgent";
import { useConversations } from "./hooks/useConversations";
import ChatSidebar from "./components/ChatSidebar";
import DiagramCanvas from "./components/DiagramCanvas";
import ConversationSidebar from "./components/ConversationSidebar";

const CHAT_MIN = 240;
const CHAT_MAX = 600;
const CHAT_DEFAULT = 380;

function newThreadId() {
  return `thread-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function getStoredThreadId(): string {
  try {
    return localStorage.getItem("diagram_agent_thread_id") || newThreadId();
  } catch {
    return newThreadId();
  }
}

function setStoredThreadId(id: string) {
  try { localStorage.setItem("diagram_agent_thread_id", id); } catch { /* ignore */ }
}

export default function App() {
  const [threadId, setThreadId] = useState<string>(getStoredThreadId);
  const diagramAgent = useDiagramAgent({ threadId });
  const convStore = useConversations();

  const diagramStep = diagramAgent.agentState.current_step;
  const [chatWidth, setChatWidth] = useState(CHAT_DEFAULT);
  const dragging = useRef(false);
  const startX = useRef(0);
  const startW = useRef(CHAT_DEFAULT);

  // Load conversations on mount
  useEffect(() => {
    convStore.fetchAll();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep localStorage in sync whenever threadId changes
  useEffect(() => {
    setStoredThreadId(threadId);
  }, [threadId]);

  // Extract stable function refs — these are created with useCallback([]) inside their
  // respective hooks, so they never change identity across renders.
  const { resetToNew, restore } = diagramAgent;
  const { loadHistory, fetchAll } = convStore;

  const handleNewConversation = useCallback(() => {
    const tid = newThreadId();
    setThreadId(tid);
    resetToNew();
  }, [resetToNew]);

  const handleSelectConversation = useCallback(async (tid: string) => {
    if (tid === threadId) return;
    const hist = await loadHistory(tid);
    setThreadId(tid);
    if (hist) {
      restore(hist.state, hist.chatMessages, hist.wireMessages as never);
    } else {
      resetToNew();
    }
  }, [threadId, loadHistory, restore, resetToNew]);

  // After each agent run finishes, refresh the conversation list so the sidebar
  // shows the latest name/preview. Use the stable `fetchAll` ref to avoid
  // running this effect on every render (convStore object changes every render).
  const prevRunning = useRef(false);
  useEffect(() => {
    if (prevRunning.current && !diagramAgent.isRunning) {
      fetchAll();
    }
    prevRunning.current = diagramAgent.isRunning;
  }, [diagramAgent.isRunning, fetchAll]);

  const onDragStart = useCallback((e: React.MouseEvent) => {
    dragging.current = true;
    startX.current = e.clientX;
    startW.current = chatWidth;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      const delta = ev.clientX - startX.current;
      setChatWidth(Math.min(CHAT_MAX, Math.max(CHAT_MIN, startW.current + delta)));
    };
    const onUp = () => {
      dragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [chatWidth]);

  const activeStep = diagramStep;
  const activeIsRunning = diagramAgent.isRunning;

  return (
    <div className="flex h-screen w-screen flex-col" style={{ background: "#0b0e14" }}>
      {/* Header */}
      <header className="flex items-center gap-3 border-b border-white/8 px-6 py-3.5">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-600/20">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="text-blue-400">
              <rect x="3" y="3" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
              <rect x="14" y="3" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
              <rect x="3" y="14" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
              <path d="M17.5 14v7M14 17.5h7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M10 6.5h4M6.5 10v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </div>
          <h1 className="text-sm font-bold tracking-tight text-white">Diagram Agent</h1>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-2.5 py-0.5 text-[11px] font-medium text-blue-400">
            AG-UI
          </span>
          {activeStep && activeStep !== "done" && activeStep !== "cancelled" && (
            <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-[11px] text-slate-600 capitalize">
              {activeStep.replace(/_/g, " ")}
            </span>
          )}
          {(diagramAgent.agentState.iteration ?? 1) > 1 && (
            <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-[11px] text-slate-700">
              v{diagramAgent.agentState.iteration}
            </span>
          )}
        </div>

        <div className="ml-auto flex items-center gap-3">
          {activeIsRunning && (
            <div className="flex items-center gap-1.5 text-[11px] text-slate-600">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400" />
              Processing
            </div>
          )}
          {activeStep === "done" && !activeIsRunning && (
            <div className="flex items-center gap-1.5 text-[11px] text-emerald-600">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              Ready
            </div>
          )}
          {diagramStep === "reviewing" && !diagramAgent.isRunning && (
            <div className="flex items-center gap-1.5 text-[11px] text-blue-500">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-400" />
              Awaiting review
            </div>
          )}
        </div>
      </header>

      {/* Main */}
      <main className="flex flex-1 overflow-hidden">
        {/* Conversation sidebar */}
        <ConversationSidebar
          conversations={convStore.conversations}
          activeThreadId={threadId}
          loading={convStore.loading}
          onSelect={handleSelectConversation}
          onNew={handleNewConversation}
          onRename={convStore.rename}
          onDelete={convStore.remove}
        />

        {/* Chat panel */}
        <div style={{ width: chatWidth, minWidth: chatWidth, maxWidth: chatWidth }} className="flex flex-col overflow-hidden">
          <ChatSidebar
            messages={diagramAgent.chatMessages}
            pendingInterrupt={diagramAgent.pendingInterrupt}
            isRunning={diagramAgent.isRunning}
            pdfBase64={diagramAgent.agentState.pdf_base64}
            activity={diagramAgent.activity}
            activeSubagent={diagramAgent.activeSubagent}
            error={diagramAgent.error}
            onSend={diagramAgent.sendMessage}
            onResolveTechStack={diagramAgent.resolveTechStack}
            onResolveBlueprint={diagramAgent.resolveBlueprint}
            onResolveResult={diagramAgent.resolveResultReview}
            onResolvePdfReport={diagramAgent.resolvePdfReport}
            onResolveEmail={diagramAgent.resolveEmail}
            onResolveMeeting={diagramAgent.resolveMeeting}
            onResolveMeetingSlot={diagramAgent.resolveMeetingSlot}
            iteration={diagramAgent.agentState.iteration}
            uploadedFiles={diagramAgent.uploadedFiles}
            isUploading={diagramAgent.isUploading}
            onUploadFile={diagramAgent.uploadFile}
            onClearFiles={diagramAgent.clearFiles}
          />
        </div>

        {/* Drag handle */}
        <div
          onMouseDown={onDragStart}
          className="relative w-1 flex-shrink-0 cursor-col-resize bg-white/5 hover:bg-blue-500/40 transition-colors group"
          title="Drag to resize"
        >
          <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 flex flex-col items-center justify-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
            <span className="h-1 w-1 rounded-full bg-blue-400" />
            <span className="h-1 w-1 rounded-full bg-blue-400" />
            <span className="h-1 w-1 rounded-full bg-blue-400" />
          </div>
        </div>

        {/* Right panel — diagram preview */}
        <DiagramCanvas
          agentState={diagramAgent.agentState}
          pendingInterrupt={diagramAgent.pendingInterrupt}
          isRunning={diagramAgent.isRunning}
          activeSubagent={diagramAgent.activeSubagent}
          activity={diagramAgent.activity}
        />
      </main>
    </div>
  );
}
