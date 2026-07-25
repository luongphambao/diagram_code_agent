import { useCallback, useEffect, useRef, useState } from "react";
import { useDiagramAgent } from "./hooks/useDiagramAgent";
import { useConversations } from "./hooks/useConversations";
import { AgentProvider } from "./context/AgentContext";
import type { DiagramKind, UserRole } from "./hooks/agent-utils";
import { loadGateHistory, clearGateHistory } from "./hooks/agent-utils";
import { useBreakpoint } from "./lib/useBreakpoint";
import { usePersistentState, oneOf, numberInRange } from "./lib/usePersistentState";
import AppShell, { CHAT_DEFAULT, CHAT_MAX, CHAT_MIN } from "./app/AppShell";
import Toolbar, { type Pane, type ThemePreference } from "./app/Toolbar";
import StatusStrip from "./app/StatusStrip";
import ChatSidebar from "./components/ChatSidebar";
import DiagramCanvas from "./components/DiagramCanvas";
import ConversationSidebar from "./components/ConversationSidebar";

const USER_ROLES: UserRole[] = ["viewer", "pm", "lead", "admin"];
const USER_ROLE_OPTIONS = USER_ROLES.map((r) => ({ value: r, label: r[0].toUpperCase() + r.slice(1) }));

function getStoredRole(): UserRole {
  try {
    const r = localStorage.getItem("diagram_agent_user_role") as UserRole | null;
    return r && USER_ROLES.includes(r) ? r : "lead";
  } catch {
    return "lead";
  }
}

// Typed-diagram foundation (improvement plan §10): explicit type selection
// overrides the backend's Auto-detect classifier. "" is the Auto-detect
// value sent to the backend (routers/chat.py reads it as `diagramKind`).
const DIAGRAM_KINDS: Array<{ value: DiagramKind; label: string }> = [
  { value: "", label: "Auto detect" },
  { value: "architecture", label: "Architecture" },
  { value: "sequence", label: "Sequence" },
  { value: "erd", label: "ERD / Database" },
  { value: "state_machine", label: "State Machine" },
  { value: "bpmn", label: "BPMN / Swimlane" },
  { value: "c4", label: "C4" },
];

function getStoredDiagramKind(): DiagramKind {
  try {
    const k = localStorage.getItem("diagram_agent_diagram_kind") as DiagramKind | null;
    return k && DIAGRAM_KINDS.some((d) => d.value === k) ? k : "";
  } catch {
    return "";
  }
}

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
  try {
    localStorage.setItem("diagram_agent_thread_id", id);
  } catch {
    /* ignore */
  }
}

const isThemePreference = oneOf<ThemePreference>("dark", "light", "system");
const isPane = oneOf<Pane>("chat", "canvas");
const isChatWidth = numberInRange(CHAT_MIN, CHAT_MAX);

export default function App() {
  const [threadId, setThreadId] = useState<string>(getStoredThreadId);
  const [userRole, setUserRole] = useState<UserRole>(getStoredRole);
  const [diagramKind, setDiagramKind] = useState<DiagramKind>(getStoredDiagramKind);
  const diagramAgent = useDiagramAgent({ threadId, userRole, diagramKind });
  const convStore = useConversations();
  const breakpoint = useBreakpoint();

  const [chatWidth, setChatWidth] = usePersistentState("da.ui.chatWidth", CHAT_DEFAULT, isChatWidth);
  const [theme, setTheme] = usePersistentState<ThemePreference>("da.ui.theme", "system", isThemePreference);
  const [railOpen, setRailOpen] = useState(false);
  const [activePane, setActivePane] = usePersistentState<Pane>("da.ui.pane", "chat", isPane);

  // Explicit choice always wins over the OS preference (plan §C.5 layer 3);
  // "system" removes the attribute so the prefers-color-scheme media query
  // in tokens.css decides.
  useEffect(() => {
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // The narrow-mode rail is a drawer; closing it when the viewport widens out
  // of narrow avoids a stale "open" overlay reappearing if the user later
  // shrinks back down.
  useEffect(() => {
    if (breakpoint !== "narrow") setRailOpen(false);
  }, [breakpoint]);

  useEffect(() => {
    try {
      localStorage.setItem("diagram_agent_user_role", userRole);
    } catch {
      /* ignore */
    }
  }, [userRole]);

  useEffect(() => {
    try {
      localStorage.setItem("diagram_agent_diagram_kind", diagramKind);
    } catch {
      /* ignore */
    }
  }, [diagramKind]);

  // Keep localStorage in sync whenever threadId changes
  useEffect(() => {
    setStoredThreadId(threadId);
  }, [threadId]);

  // Extract stable function refs — these are created with useCallback([]) inside their
  // respective hooks, so they never change identity across renders.
  const { resetToNew, restore } = diagramAgent;
  const { loadHistory, fetchAll, remove, rename } = convStore;

  // Load conversations on mount. `fetchAll` is stable, so an empty dep array
  // would also be correct — depending on it explicitly keeps the lint rule honest.
  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const handleNewConversation = useCallback(() => {
    const tid = newThreadId();
    setThreadId(tid);
    resetToNew();
  }, [resetToNew]);

  const handleSelectConversation = useCallback(
    async (tid: string) => {
      if (tid === threadId) return;
      const hist = await loadHistory(tid);
      setThreadId(tid);
      if (hist) {
        restore(hist.state, hist.chatMessages, hist.wireMessages as never, loadGateHistory(tid));
      } else {
        resetToNew();
      }
    },
    [threadId, loadHistory, restore, resetToNew],
  );

  // Conversation deletion also drops its persisted gate-history entry so
  // localStorage doesn't accumulate orphaned per-thread keys.
  const handleDeleteConversation = useCallback(
    (tid: string) => {
      clearGateHistory(tid);
      remove(tid);
    },
    [remove],
  );

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

  const handleRenameTitle = useCallback((name: string) => rename(threadId, name), [rename, threadId]);

  const conversationTitle =
    convStore.conversations.find((c) => c.thread_id === threadId)?.name || "Untitled";

  const rail = (
    <ConversationSidebar
      conversations={convStore.conversations}
      activeThreadId={threadId}
      loading={convStore.loading}
      onSelect={handleSelectConversation}
      onNew={handleNewConversation}
      onRename={convStore.rename}
      onDelete={handleDeleteConversation}
    />
  );

  const chat = <ChatSidebar />;

  const canvas = (
    <DiagramCanvas
      agentState={diagramAgent.agentState}
      pendingInterrupt={diagramAgent.pendingInterrupt}
      isRunning={diagramAgent.isRunning}
      activeSubagent={diagramAgent.activeSubagent}
      activity={diagramAgent.activity}
      threadId={threadId}
      userRole={userRole}
    />
  );

  return (
    <div className="flex h-screen w-screen flex-col bg-app">
      <Toolbar
        breakpoint={breakpoint}
        title={conversationTitle}
        onRenameTitle={handleRenameTitle}
        currentStep={diagramAgent.agentState.current_step}
        iteration={diagramAgent.agentState.iteration}
        isRunning={diagramAgent.isRunning}
        onStop={diagramAgent.abortRun}
        error={diagramAgent.error}
        diagramKind={diagramKind}
        diagramKinds={DIAGRAM_KINDS}
        onDiagramKindChange={(v) => setDiagramKind(v as DiagramKind)}
        userRole={userRole}
        userRoles={USER_ROLE_OPTIONS}
        onUserRoleChange={(v) => setUserRole(v as UserRole)}
        theme={theme}
        onThemeChange={setTheme}
        railOpen={railOpen}
        onToggleRail={() => setRailOpen((v) => !v)}
        activePane={activePane}
        onPaneChange={setActivePane}
      />

      <AgentProvider value={diagramAgent}>
        <AppShell
          breakpoint={breakpoint}
          rail={rail}
          chat={chat}
          canvas={canvas}
          chatWidth={chatWidth}
          onChatWidthChange={setChatWidth}
          railOpen={railOpen}
          onCloseRail={() => setRailOpen(false)}
          activePane={activePane}
        />
      </AgentProvider>

      <StatusStrip
        isRunning={diagramAgent.isRunning}
        activity={diagramAgent.activity}
        error={diagramAgent.error}
        modelCalls={diagramAgent.agentState.run_metrics?.model_calls}
      />
    </div>
  );
}
