import type { ReactNode } from "react";
import type { Breakpoint } from "../lib/useBreakpoint";
import type { Pane } from "./Toolbar";
import Splitter from "./Splitter";

export const CHAT_MIN = 320;
export const CHAT_MAX = 640;
export const CHAT_DEFAULT = 400;

/**
 * Composes the rail / chat / splitter / canvas regions per breakpoint (plan
 * §D.1/§D.4). Takes rendered nodes rather than owning ConversationSidebar/
 * ChatSidebar/DiagramCanvas directly, so the shell stays a pure layout
 * component — App.tsx still owns which hooks feed those children.
 *
 * wide/medium: rail + chat + splitter + canvas side by side (chat is a fixed
 *   width, resizable via the splitter; rail width is owned by the rail
 *   component itself — ConversationSidebar already collapses internally).
 * narrow: rail becomes a fixed-position overlay drawer with a backdrop; chat
 *   and canvas BOTH stay mounted (one gets `hidden`) so switching panes is
 *   instant and a streaming response never restarts.
 */
export default function AppShell({
  breakpoint,
  rail,
  chat,
  canvas,
  chatWidth,
  onChatWidthChange,
  railOpen,
  onCloseRail,
  activePane,
}: {
  breakpoint: Breakpoint;
  rail: ReactNode;
  chat: ReactNode;
  canvas: ReactNode;
  chatWidth: number;
  onChatWidthChange: (w: number) => void;
  railOpen: boolean;
  onCloseRail: () => void;
  activePane: Pane;
}) {
  if (breakpoint === "narrow") {
    return (
      <main className="relative flex flex-1 overflow-hidden">
        {railOpen && (
          <>
            <button
              aria-label="Close conversation list"
              onClick={onCloseRail}
              className="absolute inset-0 z-20 bg-app/70"
            />
            <div className="absolute inset-y-0 left-0 z-30 shadow-sm">{rail}</div>
          </>
        )}
        <div className={`flex min-w-0 flex-1 flex-col overflow-hidden ${activePane === "chat" ? "" : "hidden"}`}>
          {chat}
        </div>
        <div className={`min-w-0 flex-1 overflow-hidden ${activePane === "canvas" ? "" : "hidden"}`}>{canvas}</div>
      </main>
    );
  }

  return (
    <main className="flex flex-1 overflow-hidden">
      {rail}
      <div
        style={{ width: chatWidth, minWidth: chatWidth, maxWidth: chatWidth }}
        className="flex flex-col overflow-hidden"
      >
        {chat}
      </div>
      <Splitter width={chatWidth} min={CHAT_MIN} max={CHAT_MAX} onChange={onChatWidthChange} />
      <div className="min-w-0 flex-1 overflow-hidden">{canvas}</div>
    </main>
  );
}
