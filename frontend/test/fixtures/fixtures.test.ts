import { describe, expect, it } from "vitest";
import flowFixture from "./flow-full-design.json";
import integrityFixture from "./message-integrity-cases.json";

/**
 * These fixtures are the contract oracle for every later stage (plan §H) —
 * Stage 2's A/B body diff, Stage 3's live behavioral check, Stage 4's gate
 * registry golden payloads. This test only guards the fixtures themselves:
 * that every SSE frame is well-formed AG-UI wire format and that every
 * TOOL_CALL_ARGS payload double-decodes into a valid gate card. If a later
 * edit to these files breaks that shape, this is what catches it before a
 * stage that depends on it silently reads garbage.
 */

interface SseStep {
  label: string;
  request: { threadId: string; runId: string; messages: unknown[] };
  sseFrames: string[];
}

describe("flow-full-design.json", () => {
  const steps = flowFixture.steps as SseStep[];

  it("has at least one step per HITL gate in the documented flow", () => {
    expect(steps.length).toBe(5);
  });

  it.each(steps.map((s, i) => [i, s] as const))("step %i (%s) frames are well-formed SSE", (_i, step) => {
    expect(step.sseFrames.length).toBeGreaterThan(0);
    for (const frame of step.sseFrames) {
      expect(frame.startsWith("data: ")).toBe(true);
      expect(frame.endsWith("\n\n")).toBe(true);
      const event = JSON.parse(frame.slice(6, -2));
      expect(typeof event.type).toBe("string");
      if (event.type === "TOOL_CALL_ARGS") {
        const card = JSON.parse(event.delta);
        expect(typeof card.type).toBe("string");
        expect(typeof card.question).toBe("string");
      }
    }
  });

  it("every step's request carries at least one message", () => {
    for (const step of steps) {
      expect(step.request.messages.length).toBeGreaterThan(0);
    }
  });

  it("the pdf-followup step's last message is role=user, not a tool resume", () => {
    const msgs = steps[4].request.messages;
    const last = msgs[msgs.length - 1] as { role: string; content: string };
    expect(last.role).toBe("user");
    expect(last.content).toContain("báo cáo");
  });
});

describe("message-integrity-cases.json", () => {
  const cases = integrityFixture.cases as Array<{
    label: string;
    lastUserMessage: string;
    mustNotMatchSubstring?: string;
  }>;

  it("has the four documented branch cases", () => {
    expect(cases.length).toBe(4);
  });

  it("the docker case's lastUserMessage contains the substring it must NOT whole-word-match", () => {
    const dockerCase = cases.find((c) => c.mustNotMatchSubstring === "doc");
    expect(dockerCase).toBeDefined();
    expect(dockerCase!.lastUserMessage).toContain("docker");
  });

  it("preserves Vietnamese diacritics verbatim (no normalization/stripping)", () => {
    const vnCase = cases.find((c) => c.label.startsWith("Vietnamese PDF"));
    expect(vnCase!.lastUserMessage).toBe("tạo báo cáo pdf cho kiến trúc này");
  });
});
