/** Collaboration comments (docx §8.6) — REST over the per-thread comment_log.json.
 *  Runs OUTSIDE the agent SSE stream: the user authors comments directly. */

import { useCallback, useEffect, useState } from "react";
import { BACKEND_URL } from "./agent-utils";

export interface CommentRecord {
  id: string;
  anchor_entity_id: string;
  author: string;
  role: string;
  body: string;
  timestamp: string;
  resolved: boolean;
  resolved_by: string;
  resolved_at: string;
}

export function useComments(threadId: string) {
  const [comments, setComments] = useState<CommentRecord[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!threadId) return;
    setLoading(true);
    try {
      const res = await fetch(`${BACKEND_URL}/comments?threadId=${encodeURIComponent(threadId)}`);
      if (res.ok) {
        const data = await res.json();
        setComments(data.comments ?? []);
      }
    } catch { /* offline / not ready */ }
    finally { setLoading(false); }
  }, [threadId]);

  useEffect(() => { refresh(); }, [refresh]);

  const add = useCallback(async (body: string, opts?: { author?: string; role?: string; anchor_entity_id?: string }) => {
    if (!body.trim() || !threadId) return;
    await fetch(`${BACKEND_URL}/comments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ threadId, body, ...opts }),
    });
    await refresh();
  }, [threadId, refresh]);

  const resolve = useCallback(async (commentId: string, resolvedBy?: string) => {
    if (!threadId) return;
    await fetch(`${BACKEND_URL}/comments/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ threadId, commentId, resolved_by: resolvedBy ?? "" }),
    });
    await refresh();
  }, [threadId, refresh]);

  return { comments, loading, refresh, add, resolve };
}
