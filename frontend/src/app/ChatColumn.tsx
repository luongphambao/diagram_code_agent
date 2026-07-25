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
 * No welcome-screen/toolCallsView slot overrides — CopilotChat's defaults
 * are correct for this app (plan §E lists only the slots worth overriding;
 * the rest render fine as-is). GateHost — the per-gate HITL handlers — is
 * mounted at the CopilotKitProvider level (App.tsx), not here, since HITL
 * registration is global per agentId, not scoped to a chat view instance.
 *
 * The file-upload strip is a sibling ABOVE `<CopilotChat>`, not a slot
 * override of its composer: re-implementing CopilotChat's own send/
 * run-serialization logic just to inject a dropzone would be strictly
 * riskier than leaving its composer untouched and bolting the existing
 * `FileUpload` + `file_ids` flow (plan §B.1 — deliberately NOT CopilotChat's
 * own attachment queue) on as a plain sibling that shares the same
 * workspace context. This was flagged but deliberately deferred at Stage 3
 * ("no slot overrides yet") until the gate registry existed; wiring it now
 * closes that gap — file upload was otherwise unreachable in the rebuilt UI.
 *
 * Deliberately does NOT pass its own `threadId`/`agentId` props — App.tsx
 * wraps this (and GateHost, and useDiagramWorkspace's useAgent() call) in
 * ONE shared <CopilotChatConfigurationProvider>, so there is a single
 * resolved threadId all three read from context rather than three
 * independently-resolved values that could drift.
 */
import { CopilotChat } from "@copilotkit/react-core/v2";
import FileUpload from "../components/FileUpload";
import { useDiagramWorkspaceContext } from "../context/AgentContext";

export default function ChatColumn() {
  const { uploadedFiles, isUploading, uploadFile, clearFiles } = useDiagramWorkspaceContext();

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="border-b border-line px-4 py-2.5">
        <FileUpload uploadedFiles={uploadedFiles} isUploading={isUploading} onUpload={uploadFile} onClear={clearFiles} />
      </div>
      <CopilotChat className="h-full min-h-0 flex-1" />
    </div>
  );
}
