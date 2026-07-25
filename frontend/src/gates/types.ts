import type { ToolCallStatus } from "@copilotkit/core";

/** The common shape every gate card component receives — a trimmed,
 * status-branch-agnostic view of ReactHumanInTheLoop's render props (only
 * the fields cards actually use; `name`/`description`/`result`/`agentId`
 * are registry/library concerns, not card concerns). */
export interface GateCardProps {
  toolCallId: string;
  args: Record<string, unknown>;
  status: ToolCallStatus;
  respond: ((result: unknown) => Promise<void>) | undefined;
}
