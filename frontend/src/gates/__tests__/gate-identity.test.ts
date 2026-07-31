import { describe, expect, it } from "vitest";
import { attachGateIdentity } from "../gateIdentity";

describe("gate resume identity", () => {
  it("copies the server-issued identity into the decision payload", () => {
    expect(
      attachGateIdentity(
        { gate_id: "gate-1", gate_revision: 3 },
        { action: "approve", approved: true },
      ),
    ).toEqual({
      action: "approve",
      approved: true,
      gate_id: "gate-1",
      gate_revision: 3,
    });
  });

  it("does not mutate legacy decisions when the card has no identity", () => {
    expect(attachGateIdentity({}, { satisfied: true })).toEqual({ satisfied: true });
  });
});
