import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { Message, RunAgentInput } from "@ag-ui/client";
import { DiagramHttpAgent } from "../diagram-agent.js";

/**
 * The highest-value test in the whole migration (plan §B.4/§H.1): guards
 * backend/src/session/followups.py's phrase-matching heuristics
 * (_is_pdf_followup, _is_business_case_followup, etc. — chat.py:314-494)
 * against any future CopilotKit upgrade that starts mutating messages in
 * transit. A miss here means the backend silently wipes
 * tech_stack.json/blueprint.json/wbs.json for what the user meant as a
 * follow-up, or vice versa treats a fresh request as a follow-up.
 *
 * Reads the same fixture Stage 0 authored (frontend/test/fixtures/
 * message-integrity-cases.json) rather than duplicating the case table, so
 * the two can never drift apart.
 */

class TestableDiagramAgent extends DiagramHttpAgent {
  public callRequestInit(input: RunAgentInput): RequestInit {
    return this.requestInit(input);
  }
}

interface IntegrityCase {
  label: string;
  priorMessages: Array<{ id: string; role: string; content: string }>;
  lastUserMessage: string;
  mustNotMatchSubstring?: string;
}

const FIXTURE_PATH = fileURLToPath(
  new URL("../../../frontend/test/fixtures/message-integrity-cases.json", import.meta.url),
);
const fixture = JSON.parse(readFileSync(FIXTURE_PATH, "utf-8")) as { cases: IntegrityCase[] };

describe("message-integrity fixture sanity", () => {
  it("loaded the four documented cases", () => {
    expect(fixture.cases.length).toBe(4);
  });
});

describe.each(fixture.cases)("case: $label", (testCase) => {
  const agent = new TestableDiagramAgent({ url: "http://backend:8001/agui" });

  it("delivers lastUserMessage to the wire byte-identical", () => {
    const messages = [
      ...testCase.priorMessages,
      { id: "msg-last", role: "user", content: testCase.lastUserMessage },
    ] as unknown as Message[];
    const input: RunAgentInput = {
      threadId: "thread-fixture",
      runId: "run-fixture",
      messages,
      tools: [],
      context: [],
      state: {},
      forwardedProps: {},
    };
    const body = JSON.parse(agent.callRequestInit(input).body as string);
    const wireMessages = body.messages as Array<{ role: string; content: string }>;
    const lastUser = [...wireMessages].reverse().find((m) => m.role === "user");
    expect(lastUser).toBeDefined();
    // The core assertion: byte-identical, including diacritics.
    expect(lastUser!.content).toBe(testCase.lastUserMessage);
  });

  if (testCase.mustNotMatchSubstring) {
    it(`documents that '${testCase.mustNotMatchSubstring}' must NOT whole-word-match (substring only)`, () => {
      // This test documents the contract the wire delivery must not break —
      // the actual whole-word regex lives in Python (followups.py), so this
      // only re-asserts (in JS, mirroring \b-anchored semantics) that a bare
      // substring check would be wrong, as a guard against ever
      // "simplifying" the runtime into doing its own phrase detection.
      const normalized = testCase.lastUserMessage.toLowerCase();
      const wholeWordPattern = new RegExp(`\\b${testCase.mustNotMatchSubstring}\\b`);
      const substringMatches = normalized.includes(testCase.mustNotMatchSubstring!);
      const wholeWordMatches = wholeWordPattern.test(normalized);
      expect(substringMatches).toBe(true); // the substring IS present (e.g. "docker" contains "doc")
      expect(wholeWordMatches).toBe(false); // but must not match as a whole word
    });
  }
});
