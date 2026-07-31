export function attachGateIdentity(args: unknown, payload: unknown): unknown {
  if (!args || typeof args !== "object" || Array.isArray(args)) return payload;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
  const gateArgs = args as Record<string, unknown>;
  const decision = payload as Record<string, unknown>;
  if (typeof gateArgs.gate_id !== "string" || typeof gateArgs.gate_revision !== "number") {
    return payload;
  }
  return {
    ...decision,
    gate_id: gateArgs.gate_id,
    gate_revision: gateArgs.gate_revision,
  };
}
