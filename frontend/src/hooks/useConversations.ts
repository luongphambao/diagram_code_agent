import { useState, useCallback } from "react";
import type { AgentState } from "./agent-utils";
import { BACKEND_URL } from "./agent-utils";

export interface Conversation {
  thread_id: string;
  name: string;
  created_at: string;
  updated_at: string;
  last_message: string;
}

export interface ConversationHistory {
  name: string;
  messages: Array<{ id: string; role: string; content: string; toolCallId?: string }>;
  state: AgentState;
}

function wireToChat(wire: ConversationHistory["messages"]): ChatMessage[] {
  if (!Array.isArray(wire)) return [];
  return wire
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({ id: m.id, role: m.role as "user" | "assistant", content: m.content }));
}

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${BACKEND_URL}/conversations`);
      if (res.ok) {
        const data = await res.json();
        setConversations(Array.isArray(data) ? data : []);
      }
    } catch {
      /* ignore — backend may not be up yet */
    } finally {
      setLoading(false);
    }
  }, []);

  const rename = useCallback(async (threadId: string, name: string) => {
    try {
      await fetch(`${BACKEND_URL}/conversations/${threadId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      setConversations((prev) => prev.map((c) => (c.thread_id === threadId ? { ...c, name } : c)));
    } catch {
      /* ignore */
    }
  }, []);

  const remove = useCallback(async (threadId: string) => {
    try {
      await fetch(`${BACKEND_URL}/conversations/${threadId}`, { method: "DELETE" });
      setConversations((prev) => prev.filter((c) => c.thread_id !== threadId));
    } catch {
      /* ignore */
    }
  }, []);

  const loadHistory = useCallback(async (threadId: string) => {
    try {
      const res = await fetch(`${BACKEND_URL}/conversations/${threadId}/history`);
      if (!res.ok) return null;
      const hist: ConversationHistory = await res.json();
      return {
        state: hist.state,
        chatMessages: wireToChat(hist.messages),
        wireMessages: hist.messages,
      };
    } catch {
      return null;
    }
  }, []);

  return { conversations, loading, fetchAll, rename, remove, loadHistory };
}
