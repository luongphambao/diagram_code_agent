/**
 * Mounted once inside <CopilotKitProvider> (sibling to the chat surface —
 * HITL hooks operate globally per agentId via the core context, not scoped
 * to a specific chat view instance). Registers the single wildcard
 * `useHumanInTheLoop` that gives Stage 3 full functional gate coverage; see
 * WildcardGateCard.tsx for why a per-name registry isn't possible yet.
 */
import { useCallback } from "react";
import { useAgent } from "@copilotkit/react-core/v2";
import WildcardGateCard from "./WildcardGateCard";
import { useWildcardHumanInTheLoop } from "./useWildcardHumanInTheLoop";
import { useDiagramWorkspaceContext } from "../context/AgentContext";

export default function GateHost() {
  const { agent } = useAgent();
  const { recordResolvedGate } = useDiagramWorkspaceContext();

  const onDecision = useCallback(
    (toolCallId: string, args: unknown, decision: unknown) => {
      recordResolvedGate({
        id: toolCallId,
        data: args as never,
        decision: decision as Record<string, unknown>,
        resolvedAt: Date.now(),
        afterMessageIndex: agent.messages.length,
      });
    },
    [agent, recordResolvedGate],
  );

  useWildcardHumanInTheLoop({
    name: "*",
    description: "Diagram Agent approval gate",
    // `name: "*"` is a genuine wildcard EXECUTION path (verified against
    // @copilotkit/core's run-handler.ts executeWildcardTool), not just a
    // display fallback — respond() here really does resolve the backend's
    // pending interrupt. No `parameters` schema: the card shape varies per
    // gate type and there is nothing to validate against up front.
    //
    // Uses our own useWildcardHumanInTheLoop, NOT the library's
    // useHumanInTheLoop — found live (Stage 3 verification against the real
    // backend) that the library version overwrites `name` with the
    // registration's own static name ("*") on every render, clobbering the
    // real gate type. See useWildcardHumanInTheLoop.ts for the full story.
    render: (props) => (
      <WildcardGateCard
        {...props}
        respond={
          props.respond
            ? (payload) => {
                onDecision(props.toolCallId, props.args, payload);
                return props.respond!(payload);
              }
            : undefined
        }
      />
    ),
  });

  return null;
}
