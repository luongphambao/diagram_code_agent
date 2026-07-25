/**
 * The chat surface, on CopilotKit v2 (plan §E). Uses the high-level
 * <CopilotChat> rather than hand-composing useAgent + CopilotChatView:
 * CopilotChat already implements run-serialization (a resume/new-message
 * send while a run is in flight waits for it to settle rather than
 * pre-empting it — a real correctness property against our backend's
 * thread-scoped LangGraph checkpointer, not just UX polish) and stop/error
 * wiring. Re-implementing that ourselves would be strictly riskier than
 * using it, for no benefit — the thing we were originally worried about
 * (CopilotChat's internal `useSuggestions()` call) is verified passive: it
 * only reads existing suggestion state and never triggers a run on its own
 * (see plan §B.1 verification).
 *
 * Markdown streaming, autoscroll, and per-token render performance (defects
 * 1/5/3) are all solved by adoption — no custom code needed for those.
 *
 * No slot overrides yet: Stage 4 adds the branded welcome screen and a
 * custom composer once the gate registry (which the composer's context
 * depends on) exists. GateHost — the wildcard HITL handler — is mounted at
 * the CopilotKitProvider level (App.tsx), not here, since HITL registration
 * is global per agentId, not scoped to a chat view instance.
 */
import { CopilotChat } from "@copilotkit/react-core/v2";

export default function ChatColumn({ threadId }: { threadId: string }) {
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <CopilotChat threadId={threadId} className="h-full min-h-0 flex-1" />
    </div>
  );
}
