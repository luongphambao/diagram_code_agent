import { useRef, useState } from "react";
import type { Breakpoint } from "../lib/useBreakpoint";
import Button from "../ui/Button";
import Field from "../ui/Field";
import IconButton from "../ui/IconButton";
import Popover from "../ui/Popover";
import Select from "../ui/Select";
import StatusPill, { type StatusVariant } from "../ui/StatusPill";

export type ThemePreference = "dark" | "light" | "system";
export type Pane = "chat" | "canvas";

interface Option<T extends string> {
  value: T;
  label: string;
}

function BrandMark() {
  return (
    <div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-sm bg-well">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="text-accent-text">
        <rect x="3" y="3" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
        <path d="M17.5 14v7M14 17.5h7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M10 6.5h4M6.5 10v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    </div>
  );
}

/** Inline-editable thread title — `useConversations.rename` already existed
 * but was only reachable from the sidebar; this is new surface for it. */
function EditableTitle({ title, onRename }: { title: string; onRename: (name: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const inputRef = useRef<HTMLInputElement>(null);

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        autoFocus
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          setEditing(false);
          const trimmed = draft.trim();
          if (trimmed && trimmed !== title) onRename(trimmed);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") inputRef.current?.blur();
          if (e.key === "Escape") {
            setDraft(title);
            setEditing(false);
          }
        }}
        className="min-w-0 max-w-48 rounded-sm border border-accent-hi/40 bg-well px-1.5 py-0.5 text-sm text-fg outline-none"
        aria-label="Conversation title"
      />
    );
  }

  return (
    <button
      type="button"
      onDoubleClick={() => {
        setDraft(title);
        setEditing(true);
      }}
      title="Double-click to rename"
      className="min-w-0 max-w-48 truncate rounded-sm px-1.5 py-0.5 text-left text-sm text-secondary hover:bg-well hover:text-fg"
    >
      {title || "Untitled"}
    </button>
  );
}

export default function Toolbar({
  breakpoint,
  title,
  onRenameTitle,
  currentStep,
  iteration,
  isRunning,
  onStop,
  error,
  errorCode,
  diagramKind,
  diagramKinds,
  onDiagramKindChange,
  userRole,
  userRoles,
  onUserRoleChange,
  theme,
  onThemeChange,
  railOpen,
  onToggleRail,
  activePane,
  onPaneChange,
}: {
  breakpoint: Breakpoint;
  title: string;
  onRenameTitle: (name: string) => void;
  currentStep?: string;
  iteration?: number;
  isRunning: boolean;
  onStop: () => void;
  error: string | null;
  errorCode?: string;
  diagramKind: string;
  diagramKinds: Option<string>[];
  onDiagramKindChange: (v: string) => void;
  userRole: string;
  userRoles: Option<string>[];
  onUserRoleChange: (v: string) => void;
  theme: ThemePreference;
  onThemeChange: (v: ThemePreference) => void;
  railOpen: boolean;
  onToggleRail: () => void;
  activePane: Pane;
  onPaneChange: (p: Pane) => void;
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsBtnRef = useRef<HTMLButtonElement>(null);

  const statusVariant: StatusVariant = error
    ? "error"
    : isRunning
      ? "running"
      : currentStep === "reviewing" || currentStep?.startsWith("awaiting")
        ? "awaiting"
        : currentStep === "done"
          ? "done"
          : "idle";

  const statusLabel =
    statusVariant === "error"
      ? `Error${errorCode ? ` · ${errorCode}` : ""}`
      : statusVariant === "running"
        ? "Running"
        : statusVariant === "awaiting"
          ? "Awaiting review"
          : statusVariant === "done"
            ? "Ready"
            : "Idle";

  const themeIcon = theme === "dark" ? "☾" : theme === "light" ? "☀" : "◐";
  const nextTheme: ThemePreference = theme === "system" ? "dark" : theme === "dark" ? "light" : "system";

  const controls = (
    <>
      <Field label="Kind">
        <Select
          value={diagramKind}
          onChange={(e) => onDiagramKindChange(e.target.value)}
          aria-label="Diagram type — Auto detect lets the agent classify the request"
        >
          {diagramKinds.map((d) => (
            <option key={d.value || "auto"} value={d.value}>
              {d.label}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Role">
        <Select
          value={userRole}
          onChange={(e) => onUserRoleChange(e.target.value)}
          aria-label="Role used to approve gates"
        >
          {userRoles.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </Select>
      </Field>
    </>
  );

  return (
    <header
      role="toolbar"
      aria-label="Run controls"
      aria-orientation="horizontal"
      className="flex h-14 flex-shrink-0 items-center gap-3 border-b border-line px-4"
    >
      {breakpoint === "narrow" && (
        <IconButton label="Toggle conversation list" onClick={onToggleRail} active={railOpen}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" />
          </svg>
        </IconButton>
      )}

      <BrandMark />
      <h1 className="flex-shrink-0 text-sm font-bold tracking-tight text-fg">Diagram Agent</h1>

      {breakpoint !== "narrow" && (
        <>
          <span className="flex-shrink-0 rounded-xs border border-accent/30 bg-accent/10 px-2 py-0.5 text-2xs font-medium text-accent-text">
            AG-UI
          </span>
          <EditableTitle title={title} onRename={onRenameTitle} />
          {currentStep && currentStep !== "done" && currentStep !== "cancelled" && (
            <span className="label-caps flex-shrink-0 rounded-xs border border-line bg-well px-2 py-0.5 text-2xs text-secondary">
              {currentStep.replace(/_/g, " ")}
            </span>
          )}
          {(iteration ?? 1) > 1 && (
            <span className="tnum flex-shrink-0 rounded-xs border border-line bg-well px-2 py-0.5 text-2xs text-secondary">
              v{iteration}
            </span>
          )}
        </>
      )}

      {breakpoint === "narrow" && (
        <div className="ml-1 flex flex-shrink-0 items-center gap-0.5 rounded-sm border border-line bg-well p-0.5">
          {(["chat", "canvas"] as const).map((p) => (
            <button
              key={p}
              onClick={() => onPaneChange(p)}
              className={`rounded-xs px-2 py-1 text-xs font-medium capitalize transition-colors ${
                activePane === p ? "bg-accent text-on-accent" : "text-secondary"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      )}

      <div className="ml-auto flex flex-shrink-0 items-center gap-3">
        {breakpoint === "wide" && controls}

        {breakpoint === "medium" && (
          <div className="relative">
            <Button ref={settingsBtnRef} variant="ghost" size="sm" onClick={() => setSettingsOpen((v) => !v)}>
              Settings ▾
            </Button>
            <Popover open={settingsOpen} onClose={() => setSettingsOpen(false)} anchorRef={settingsBtnRef}>
              <div className="flex flex-col gap-2">{controls}</div>
            </Popover>
          </div>
        )}

        <IconButton label={`Theme: ${theme}`} onClick={() => onThemeChange(nextTheme)}>
          <span aria-hidden="true">{themeIcon}</span>
        </IconButton>

        <StatusPill variant={statusVariant}>{statusLabel}</StatusPill>
        {isRunning && (
          <Button variant="danger" size="sm" onClick={onStop}>
            Stop
          </Button>
        )}
      </div>
    </header>
  );
}
