import { useEffect, useRef, useState } from "react";
import type { Conversation } from "../hooks/useConversations";

interface Props {
  conversations: Conversation[];
  activeThreadId: string;
  loading: boolean;
  onSelect: (threadId: string) => void;
  onNew: () => void;
  onRename: (threadId: string, name: string) => void;
  onDelete: (threadId: string) => void;
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function ConversationSidebar({
  conversations,
  activeThreadId,
  loading,
  onSelect,
  onNew,
  onRename,
  onDelete,
}: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingId && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editingId]);

  function startEdit(conv: Conversation, e: React.MouseEvent) {
    e.stopPropagation();
    setEditingId(conv.thread_id);
    setEditValue(conv.name);
  }

  function commitEdit(threadId: string) {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== conversations.find((c) => c.thread_id === threadId)?.name) {
      onRename(threadId, trimmed);
    }
    setEditingId(null);
  }

  function handleKeyDown(e: React.KeyboardEvent, threadId: string) {
    if (e.key === "Enter") commitEdit(threadId);
    if (e.key === "Escape") setEditingId(null);
  }

  if (collapsed) {
    return (
      <div
        className="flex flex-col items-center border-r border-white/8 bg-[#0d1017] py-3"
        style={{ width: 40, minWidth: 40 }}
      >
        <button
          onClick={() => setCollapsed(false)}
          className="flex h-7 w-7 items-center justify-center rounded text-slate-500 hover:text-slate-300 hover:bg-white/6 transition-colors"
          title="Expand conversations"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path
              d="M9 18l6-6-6-6"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
        <button
          onClick={onNew}
          className="mt-2 flex h-7 w-7 items-center justify-center rounded text-slate-500 hover:text-blue-400 hover:bg-white/6 transition-colors"
          title="New conversation"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path
              d="M12 5v14M5 12h14"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>
    );
  }

  return (
    <div
      className="flex flex-col border-r border-white/8 bg-[#0d1017]"
      style={{ width: 220, minWidth: 220 }}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/8 px-3 py-2.5">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
          Conversations
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={onNew}
            className="flex h-6 w-6 items-center justify-center rounded text-slate-500 hover:text-blue-400 hover:bg-white/6 transition-colors"
            title="New conversation"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 5v14M5 12h14"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          </button>
          <button
            onClick={() => setCollapsed(true)}
            className="flex h-6 w-6 items-center justify-center rounded text-slate-500 hover:text-slate-300 hover:bg-white/6 transition-colors"
            title="Collapse"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
              <path
                d="M15 18l-6-6 6-6"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto py-1">
        {loading && conversations.length === 0 && (
          <div className="px-3 py-4 text-[11px] text-slate-600">Loading…</div>
        )}
        {!loading && conversations.length === 0 && (
          <div className="px-3 py-4 text-[11px] text-slate-600">No conversations yet.</div>
        )}
        {conversations.map((conv) => {
          const isActive = conv.thread_id === activeThreadId;
          const isEditing = editingId === conv.thread_id;
          const isHovered = hoveredId === conv.thread_id;

          return (
            <div
              key={conv.thread_id}
              onClick={() => !isEditing && onSelect(conv.thread_id)}
              onMouseEnter={() => setHoveredId(conv.thread_id)}
              onMouseLeave={() => setHoveredId(null)}
              onDoubleClick={(e) => startEdit(conv, e)}
              className={`group relative mx-1 my-0.5 flex cursor-pointer flex-col rounded px-2 py-1.5 transition-colors ${
                isActive
                  ? "bg-blue-600/15 text-blue-100"
                  : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
              }`}
            >
              {/* Name row */}
              <div className="flex items-center gap-1 min-w-0">
                {isEditing ? (
                  <input
                    ref={inputRef}
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onBlur={() => commitEdit(conv.thread_id)}
                    onKeyDown={(e) => handleKeyDown(e, conv.thread_id)}
                    onClick={(e) => e.stopPropagation()}
                    className="w-full rounded bg-white/10 px-1 py-0 text-[12px] text-white outline-none ring-1 ring-blue-500/60"
                  />
                ) : (
                  <span
                    className="flex-1 truncate text-[12px] font-medium leading-tight"
                    title={conv.name}
                  >
                    {conv.name}
                  </span>
                )}
                {/* Delete button */}
                {!isEditing && isHovered && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(conv.thread_id);
                    }}
                    className="flex-shrink-0 flex h-4 w-4 items-center justify-center rounded text-slate-600 hover:text-red-400 transition-colors"
                    title="Delete"
                  >
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                      <path
                        d="M18 6L6 18M6 6l12 12"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                      />
                    </svg>
                  </button>
                )}
              </div>

              {/* Preview + timestamp */}
              {!isEditing && (
                <div className="mt-0.5 flex items-center gap-1.5 min-w-0">
                  {conv.last_message && (
                    <span
                      className="flex-1 truncate text-[10px] text-slate-600"
                      title={conv.last_message}
                    >
                      {conv.last_message}
                    </span>
                  )}
                  <span className="flex-shrink-0 text-[10px] text-slate-700">
                    {timeAgo(conv.updated_at)}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
