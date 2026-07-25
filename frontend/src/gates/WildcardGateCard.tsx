/**
 * Stage 3's temporary universal gate handler (plan §F.4's "wildcard catch",
 * brought forward to Stage 3 out of necessity: verified against
 * @copilotkit/core's run-handler.ts that there is no dynamic/per-name HITL
 * respond mechanism — `useHumanInTheLoop` must be registered per literal
 * `name`, and the only real wildcard is a single `name: "*"` registration
 * (confirmed live via `executeWildcardTool` in run-handler.ts). Since the
 * backend can raise any of 13 different gate names, ONE generic card is
 * what makes the full flow (design -> techstack -> blueprint -> review ->
 * PDF follow-up) testable end-to-end before Stage 4 replaces this with the
 * real per-type registry + the rich ported UI from the 12 old approval
 * components.
 *
 * `props.name` is the REAL gate type (verified via useRenderToolCall: the
 * render path passes the raw tool-call name, unlike the HANDLER path which
 * wraps args as `{toolName, args}` — those are two different code paths).
 * `props.args` is the raw card JSON directly — no unwrapping needed.
 */
import { useEffect, useRef } from "react";
import type { ToolCallStatus } from "@copilotkit/core";
import Button from "../ui/Button";
import Card from "../ui/Card";
import Chip from "../ui/Chip";
import Stripe from "../ui/Stripe";

interface GateCardData {
  type?: string;
  question?: string;
  [key: string]: unknown;
}

interface WildcardGateCardProps {
  name: string;
  description: string;
  toolCallId: string;
  args: Partial<GateCardData>;
  status: ToolCallStatus;
  result: string | undefined;
  respond: ((result: unknown) => Promise<void>) | undefined;
}

const GATE_LABELS: Record<string, string> = {
  techstack_approval: "Tech Stack Recommendation",
  blueprint_approval: "Architecture Blueprint",
  result_review: "Diagram Review",
  pdf_report_approval: "PDF Report",
  ppt_proposal_approval: "PPT Proposal",
  wbs_skeleton_approval: "WBS Skeleton",
  wbs_approval: "WBS Plan",
  wbs_excel_approval: "WBS Excel Export",
  delivery_export_approval: "Delivery Export",
  email_approval: "Email",
  meeting_approval: "Meeting",
  slot_picker: "Meeting Slot",
  business_case_approval: "Business Case",
};

export default function WildcardGateCard({ name, args, status, respond }: WildcardGateCardProps) {
  const ref = useRef<HTMLDivElement>(null);
  const isOpen = status === "Executing" && !!respond;

  useEffect(() => {
    if (!isOpen) return;
    ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    ref.current?.focus({ preventScroll: true });
  }, [isOpen]);

  if (status === "InProgress") {
    return (
      <Card className="relative mt-2 max-w-lg overflow-hidden p-4 pl-5 animate-pulse motion-reduce:animate-none">
        <Stripe severity="neutral" />
        <p className="text-xs text-muted">Preparing gate…</p>
      </Card>
    );
  }

  const label = GATE_LABELS[name] ?? name;
  const question = typeof args.question === "string" ? args.question : "Review and approve to continue.";

  if (status === "Complete") {
    return (
      <Card className="relative mt-2 max-w-lg overflow-hidden p-4 pl-5">
        <Stripe severity="ok" />
        <div className="flex items-center gap-2">
          <Chip variant="ok">Resolved</Chip>
          <span className="text-sm font-medium text-fg">{label}</span>
        </div>
      </Card>
    );
  }

  function decide(payload: Record<string, unknown>) {
    void respond?.(payload);
  }

  // result_review uses {satisfied, feedback} rather than {action, approved}
  // (backend/src/session/gate_decisions.py special-cases finalize_diagram).
  const isResultReview = name === "result_review";

  return (
    <Card
      ref={ref}
      tabIndex={-1}
      role="group"
      aria-label={label}
      className="relative mt-2 max-w-lg overflow-hidden p-4 pl-5"
    >
      <Stripe severity="warn" />
      <div className="mb-2 flex items-center gap-2">
        <Chip variant="warn">Approval needed</Chip>
        <span className="text-sm font-semibold text-fg">{label}</span>
      </div>
      <p className="mb-3 text-sm text-secondary">{question}</p>
      <details className="mb-3 text-xs">
        <summary className="cursor-pointer text-muted hover:text-secondary">Details</summary>
        <pre className="mt-2 max-h-64 overflow-auto rounded-sm bg-well p-2 font-mono text-code text-secondary">
          {JSON.stringify(args, null, 2)}
        </pre>
      </details>
      <div className="flex gap-2">
        <Button
          variant="primary"
          size="sm"
          onClick={() =>
            decide(isResultReview ? { satisfied: true } : { action: "approve", approved: true })
          }
        >
          Approve
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            const feedback = window.prompt("What should change?") ?? "";
            decide(
              isResultReview
                ? { satisfied: false, feedback }
                : { action: "reject", approved: false, feedback },
            );
          }}
        >
          Request changes
        </Button>
      </div>
    </Card>
  );
}
