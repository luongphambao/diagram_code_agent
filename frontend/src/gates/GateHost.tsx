/**
 * Stage 4's real per-gate registry (plan §F), replacing Stage 3's single
 * wildcard fallback. Mounted once inside <CopilotKitProvider> (sibling to
 * the chat surface — HITL hooks operate globally per agentId via the core
 * context, not scoped to a specific chat view instance).
 *
 * Registers 13 named `useHumanInTheLoop` tools, one per real backend gate
 * name (registry.ts's GATE_TYPES) — the library's own name/description
 * overwrite (use-human-in-the-loop.tsx) is CORRECT here, unlike the Stage 3
 * wildcard case, because `tool.name` for a named registration genuinely IS
 * the gate type. Plus one wildcard safety net (plan §F.4) for a gate name
 * with no registry entry at all (e.g. `propose_deck_plan`, whose
 * `_card_for` branch is missing server-side — this makes it surfaceable and
 * diagnosable, not fixed; that's a backend bug).
 */
import { useCallback } from "react";
import { useAgent, useHumanInTheLoop } from "@copilotkit/react-core/v2";
import { ToolCallStatus } from "@copilotkit/core";
import { GATE_TYPES, GATE_REGISTRY, type GateType } from "./registry";
import { parseGatePayload } from "./parseGatePayload";
import GateFrame from "./GateFrame";
import UnknownGateCard from "./UnknownGateCard";
import WildcardGateCard from "./WildcardGateCard";
import { useWildcardHumanInTheLoop } from "./useWildcardHumanInTheLoop";
import { useDiagramWorkspaceContext } from "../context/AgentContext";

type OnDecision = (toolCallId: string, args: unknown, decision: unknown) => void;

function GateRegistrar({ type, onDecision }: { type: GateType; onDecision: OnDecision }) {
  const def = GATE_REGISTRY[type];

  useHumanInTheLoop({
    name: type,
    description: def.label,
    available: false,
    render: (props) => {
      if (props.status === ToolCallStatus.InProgress) {
        return <def.Card toolCallId={props.toolCallId} args={{}} status={props.status} respond={undefined} />;
      }

      const parsed = parseGatePayload(type, props.args);
      const wrappedRespond = props.respond
        ? (payload: unknown) => {
            onDecision(props.toolCallId, props.args, payload);
            return props.respond!(payload);
          }
        : undefined;

      if (!parsed.ok) {
        return (
          <UnknownGateCard label={def.label} reason={parsed.reason} rawArgs={props.args} status={props.status} respond={wrappedRespond} />
        );
      }

      return <def.Card toolCallId={props.toolCallId} args={parsed.data} status={props.status} respond={wrappedRespond} />;
    },
  });

  return null;
}

export default function GateHost() {
  const { agent } = useAgent();
  const { recordResolvedGate } = useDiagramWorkspaceContext();

  const onDecision = useCallback<OnDecision>(
    (toolCallId, args, decision) => {
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
    description: "Diagram Agent approval gate (unregistered gate type)",
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

  return (
    <>
      {GATE_TYPES.map((type) => (
        <GateRegistrar key={type} type={type} onDecision={onDecision} />
      ))}
    </>
  );
}
