import { useCallback, useEffect, useRef, useState } from "react";
import { CopilotKitProvider, CopilotChatConfigurationProvider, useAgent, UseAgentUpdate } from "@copilotkit/react-core/v2";
import type { Message } from "@ag-ui/client";
import { useConversations } from "./hooks/useConversations";
import { useDiagramWorkspace } from "./hooks/useDiagramWorkspace";
import { useActivityStream } from "./hooks/useActivityStream";
import { DiagramWorkspaceProvider } from "./context/AgentContext";
import type { DiagramKind, UserRole } from "./hooks/agent-utils";
import { RUNTIME_URL } from "./hooks/agent-utils";
import { useBreakpoint } from "./lib/useBreakpoint";
import { usePersistentState, oneOf, numberInRange } from "./lib/usePersistentState";
import AppShell, { CHAT_DEFAULT, CHAT_MAX, CHAT_MIN } from "./app/AppShell";
import Toolbar, { type Pane, type ThemePreference } from "./app/Toolbar";
import StatusStrip from "./app/StatusStrip";
import PropertiesSync from "./app/PropertiesSync";
import ChatColumn from "./app/ChatColumn";
import GateHost from "./gates/GateHost";
import DiagramCanvas from "./components/DiagramCanvas";
import ConversationSidebar from "./components/ConversationSidebar";

const USER_ROLES: UserRole[] = ["viewer", "pm", "lead", "admin"];
const USER_ROLE_OPTIONS = USER_ROLES.map((r) => ({ value: r, label: r[0].toUpperCase() + r.slice(1) }));
const DEFAULT_AGENT_ID = "default"; // matches runtime/src/index.ts's `{ default: agent }` registration

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

  useEffect(() => {
    setStoredThreadId(threadId);
  }, [threadId]);

  return (
    // Same-origin runtimeUrl (plan §A.11) — the Node CopilotKit v2 service
    // (runtime/), not the Python backend directly. `properties` here is only
    // the INITIAL value (CopilotKitCore is constructed once behind a lazy
    // ref) — PropertiesSync below keeps it live via copilotkit.setProperties().
    <CopilotKitProvider
      runtimeUrl={RUNTIME_URL}
      properties={{ file_ids: [], userRole, diagramKind }}
      showDevConsole={false}
    >
      {/* One shared threadId resolution for <CopilotChat>, GateHost, and
          useDiagramWorkspace's useAgent() call — all three read this same
          context rather than three independently-resolved values. */}
      <CopilotChatConfigurationProvider agentId={DEFAULT_AGENT_ID} threadId={threadId}>
        <AppInner
          threadId={threadId}
          setThreadId={setThreadId}
          userRole={userRole}
          setUserRole={setUserRole}
          diagramKind={diagramKind}
          setDiagramKind={setDiagramKind}
        />
      </CopilotChatConfigurationProvider>
    </CopilotKitProvider>
  );
}

interface AppInnerProps {
  threadId: string;
  setThreadId: (id: string) => void;
  userRole: UserRole;
  setUserRole: (r: UserRole) => void;
  diagramKind: DiagramKind;
  setDiagramKind: (k: DiagramKind) => void;
}

function AppInner({
  threadId,
  setThreadId,
  userRole,
  setUserRole,
  diagramKind,
  setDiagramKind,
}: AppInnerProps) {
  const workspace = useDiagramWorkspace({ threadId });
  const activityStream = useActivityStream();
  // Separate from workspace's own OnStateChanged-only subscription: this is
  // what makes AppInner re-render (and therefore read fresh agent.isRunning)
  // when a run starts/stops/errors.
  const { agent } = useAgent({ updates: [UseAgentUpdate.OnRunStatusChanged] });
  const convStore = useConversations();
  const breakpoint = useBreakpoint();

  const [chatWidth, setChatWidth] = usePersistentState("da.ui.chatWidth", CHAT_DEFAULT, isChatWidth);
  const [theme, setTheme] = usePersistentState<ThemePreference>("da.ui.theme", "system", isThemePreference);
  const [railOpen, setRailOpen] = useState(false);
  const [activePane, setActivePane] = usePersistentState<Pane>("da.ui.pane", "chat", isPane);

  useEffect(() => {
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (breakpoint !== "narrow") setRailOpen(false);
  }, [breakpoint]);

  const { fetchAll, remove, rename, loadHistory } = convStore;

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const { restore, resetToNew } = workspace;

  const handleNewConversation = useCallback(() => {
    setThreadId(newThreadId());
    resetToNew();
  }, [setThreadId, resetToNew]);

  const handleSelectConversation = useCallback(
    async (tid: string) => {
      if (tid === threadId) return;
      const hist = await loadHistory(tid);
      setThreadId(tid);
      if (hist) {
        restore(hist.state, hist.wireMessages as unknown as Message[], []);
      } else {
        resetToNew();
      }
    },
    [threadId, loadHistory, setThreadId, restore, resetToNew],
  );

  const handleDeleteConversation = useCallback(
    (tid: string) => {
      remove(tid);
    },
    [remove],
  );

  // After each run finishes, refresh the conversation list (name/preview).
  const prevRunning = useRef(false);
  useEffect(() => {
    if (prevRunning.current && !agent.isRunning) fetchAll();
    prevRunning.current = agent.isRunning;
  }, [agent.isRunning, fetchAll]);

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

  const canvas = (
    <DiagramCanvas
      agentState={workspace.agentState}
      isRunning={agent.isRunning}
      activeSubagent={activityStream.activeSubagent}
      activity={activityStream.activity}
      threadId={threadId}
      userRole={userRole}
    />
  );

  return (
    <DiagramWorkspaceProvider value={workspace}>
      <PropertiesSync file_ids={workspace.fileIds} userRole={userRole} diagramKind={diagramKind} />
      <GateHost />

      <div className="flex h-screen w-screen flex-col bg-app">
        <Toolbar
          breakpoint={breakpoint}
          title={conversationTitle}
          onRenameTitle={handleRenameTitle}
          currentStep={workspace.agentState.current_step}
          iteration={workspace.agentState.iteration}
          isRunning={agent.isRunning}
          onStop={() => agent.abortRun()}
          error={activityStream.error?.message ?? null}
          errorCode={activityStream.error?.code}
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

        <AppShell
          breakpoint={breakpoint}
          rail={rail}
          chat={<ChatColumn />}
          canvas={canvas}
          chatWidth={chatWidth}
          onChatWidthChange={setChatWidth}
          railOpen={railOpen}
          onCloseRail={() => setRailOpen(false)}
          activePane={activePane}
        />

        <StatusStrip
          isRunning={agent.isRunning}
          activity={activityStream.activity}
          error={activityStream.error?.message ?? null}
          modelCalls={workspace.agentState.run_metrics?.model_calls}
        />
      </div>
    </DiagramWorkspaceProvider>
  );
}
