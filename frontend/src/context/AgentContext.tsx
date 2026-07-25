import { createContext, useContext } from "react";
import type { useDiagramWorkspace } from "../hooks/useDiagramWorkspace";

/**
 * Carries useDiagramWorkspace's return value (plan §E.1 replaced
 * useDiagramAgent — chatMessages/pendingInterrupt/resolveGate/sendMessage
 * are gone; CopilotKit's <CopilotChat> + useHumanInTheLoop own message
 * transport now). GateHost reads `recordResolvedGate` from here so the
 * resolved-gate audit trail stays populated without every gate card needing
 * its own prop-drilled reference to the workspace hook.
 */
export type DiagramWorkspaceContextValue = ReturnType<typeof useDiagramWorkspace>;

const DiagramWorkspaceContext = createContext<DiagramWorkspaceContextValue | null>(null);

export const DiagramWorkspaceProvider = DiagramWorkspaceContext.Provider;

export function useDiagramWorkspaceContext(): DiagramWorkspaceContextValue {
  const ctx = useContext(DiagramWorkspaceContext);
  if (!ctx) {
    throw new Error("useDiagramWorkspaceContext must be used within a <DiagramWorkspaceProvider>");
  }
  return ctx;
}
