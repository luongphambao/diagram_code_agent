import { useState } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import GateFrame from "../GateFrame";
import Button from "../../ui/Button";
import Chip from "../../ui/Chip";
import type { GateCardProps } from "../types";

/** Ported from components/DiagramFeedback.tsx (plan §F). Uses
 * `{satisfied, feedback}` rather than `{action, approved}` — backend's
 * gate_decisions.py special-cases `finalize_diagram` on that exact shape. */
export default function ResultReviewCard({ args, status, respond }: GateCardProps) {
  const [mode, setMode] = useState<"idle" | "feedback">("idle");
  const [feedback, setFeedback] = useState("");
  const [decided, setDecided] = useState(false);
  const iteration = typeof args.iteration === "number" ? args.iteration : 1;

  function decide(payload: Record<string, unknown>) {
    setDecided(true);
    void respond?.(payload);
  }
  const approve = () => decide({ satisfied: true });
  const requestChanges = () => {
    if (!feedback.trim()) return;
    decide({ satisfied: false, feedback: feedback.trim() });
  };

  if (decided && status === ToolCallStatus.Executing) {
    return (
      <GateFrame label="Diagram Review" tone="decision" status={status}>
        <p className="text-xs text-muted">
          {mode === "feedback" ? "Feedback sent — regenerating diagram…" : "Approved — finishing up…"}
        </p>
      </GateFrame>
    );
  }

  return (
    <GateFrame
      label="Diagram Review"
      tone="decision"
      status={status}
      badge={iteration > 1 ? <Chip variant="neutral">Iteration {iteration}</Chip> : undefined}
    >
      {mode === "idle" ? (
        <>
          <p className="text-sm text-secondary">{typeof args.question === "string" ? args.question : "Is the diagram good?"}</p>
          <p className="text-xs text-muted">Review the diagram on the right, then:</p>
          <div className="flex gap-2.5">
            <Button variant="primary" size="md" onClick={approve} className="flex-1">
              Looks great!
            </Button>
            <Button variant="secondary" size="md" onClick={() => setMode("feedback")} className="flex-1">
              Request changes
            </Button>
          </div>
        </>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <button onClick={() => setMode("idle")} className="text-xs text-muted hover:text-secondary">
              ← Back
            </button>
            <p className="text-xs text-secondary">What should be changed?</p>
          </div>
          <textarea
            className="w-full resize-none rounded-sm border border-line bg-app px-3 py-2.5 text-xs leading-relaxed text-fg placeholder:text-muted focus:border-accent-hi focus:outline-none"
            rows={3}
            placeholder="e.g. Move Redis inside the backend cluster, add a load balancer in front of the API servers..."
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            autoFocus
          />
          <Button variant="primary" size="md" onClick={requestChanges} disabled={!feedback.trim()}>
            Regenerate with changes
          </Button>
        </>
      )}
    </GateFrame>
  );
}
