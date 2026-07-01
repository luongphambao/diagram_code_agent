import { createContext, useContext } from "react";
import type { useDiagramAgent } from "../hooks/useDiagramAgent";

export type AgentContextValue = ReturnType<typeof useDiagramAgent>;

const AgentContext = createContext<AgentContextValue | null>(null);

export const AgentProvider = AgentContext.Provider;

export function useAgentContext(): AgentContextValue {
  const ctx = useContext(AgentContext);
  if (!ctx) {
    throw new Error("useAgentContext must be used within an <AgentProvider>");
  }
  return ctx;
}
