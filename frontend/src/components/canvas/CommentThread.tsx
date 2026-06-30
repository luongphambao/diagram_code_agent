import { useState } from "react";
import { useComments } from "../../hooks/useComments";

interface CommentThreadProps {
  threadId: string;
  userRole: string;
}

export default function CommentThread({ threadId, userRole }: CommentThreadProps) {
  const { comments, loading, add, resolve } = useComments(threadId);
  const [draft, setDraft] = useState("");
  const [anchor, setAnchor] = useState("");

  const submit = async () => {
    const body = draft.trim();
    if (!body) return;
    setDraft("");
    await add(body, { author: userRole || "user", role: userRole, anchor_entity_id: anchor.trim() });
    setAnchor("");
  };

  const open = comments.filter((c) => !c.resolved);
  const done = comments.filter((c) => c.resolved);

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-[#0b0e14]">
      <div className="flex items-center justify-between border-b border-white/8 px-4 py-2">
        <span className="text-xs font-medium text-slate-400">
          Comments {comments.length > 0 && <span className="text-slate-600">· {open.length} open</span>}
        </span>
        {loading && <span className="text-[11px] text-slate-600">loading…</span>}
      </div>

      <div className="flex-1 space-y-2.5 overflow-y-auto p-4">
        {comments.length === 0 && (
          <p className="px-1 py-6 text-center text-xs text-slate-700">No comments yet. Leave a note for the team below.</p>
        )}
        {[...open, ...done].map((c) => (
          <div key={c.id} className={`rounded-xl border px-3 py-2.5 ${
            c.resolved ? "border-white/5 bg-white/2 opacity-60" : "border-white/10 bg-white/4"
          }`}>
            <div className="mb-1 flex items-center gap-2">
              <span className="text-[11px] font-semibold text-slate-300">{c.author || "user"}</span>
              {c.role && <span className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] capitalize text-slate-500">{c.role}</span>}
              {c.anchor_entity_id && <span className="rounded bg-blue-500/10 px-1.5 py-0.5 font-mono text-[10px] text-blue-300">{c.anchor_entity_id}</span>}
              <span className="ml-auto font-mono text-[10px] text-slate-700">{c.id}</span>
            </div>
            <p className="text-xs leading-relaxed text-slate-300">{c.body}</p>
            {!c.resolved ? (
              <button
                onClick={() => resolve(c.id, userRole || "user")}
                className="mt-2 rounded-md border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-300 transition-colors hover:bg-emerald-500/20"
              >
                Resolve
              </button>
            ) : (
              <p className="mt-1.5 text-[10px] text-slate-600">resolved{c.resolved_by ? ` by ${c.resolved_by}` : ""}</p>
            )}
          </div>
        ))}
      </div>

      <div className="border-t border-white/8 p-3">
        <input
          value={anchor}
          onChange={(e) => setAnchor(e.target.value)}
          placeholder="Anchor entity id (optional, e.g. REQ-3)"
          className="mb-2 w-full rounded-lg border border-white/8 bg-white/4 px-2.5 py-1.5 text-[11px] text-slate-300 outline-none placeholder:text-slate-700 focus:border-blue-500/40"
        />
        <div className="flex gap-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(); }}
            placeholder="Add a comment… (⌘/Ctrl+Enter)"
            rows={2}
            className="flex-1 resize-none rounded-lg border border-white/8 bg-white/4 px-2.5 py-1.5 text-xs text-slate-200 outline-none placeholder:text-slate-700 focus:border-blue-500/40"
          />
          <button
            onClick={submit}
            disabled={!draft.trim()}
            className="self-end rounded-lg bg-blue-700 px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-blue-600 disabled:opacity-40"
          >
            Post
          </button>
        </div>
      </div>
    </div>
  );
}
