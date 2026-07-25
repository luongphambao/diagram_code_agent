import { useState } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import GateFrame from "../GateFrame";
import KeyValueGrid from "../KeyValueGrid";
import Chip from "../../ui/Chip";
import Button from "../../ui/Button";
import type { GateCardProps } from "../types";

/** Ported from components/EmailApproval.tsx (plan §F). Binary approve/reject
 * only — send_email's GATE_DECISIONS entry offers no HITL v2 trade-off actions. */
export default function EmailCard({ args, status, respond }: GateCardProps) {
  const [decided, setDecided] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  const recipientEmail = typeof args.recipient_email === "string" ? args.recipient_email : "";
  const subject = typeof args.subject === "string" ? args.subject : "";
  const projectName = typeof args.project_name === "string" ? args.project_name : "";
  const recipientName = typeof args.recipient_name === "string" ? args.recipient_name : "";

  function decide(approved: boolean) {
    setDecided(true);
    setDecision(approved ? "approved" : "rejected");
    void respond?.({ action: approved ? "approve" : "reject", approved });
  }

  if (decided && status === ToolCallStatus.Executing) {
    return (
      <GateFrame label="Email" tone="comms" status={status}>
        <p className="text-xs text-muted">{decision === "approved" ? "Sending email…" : "Email send cancelled."}</p>
      </GateFrame>
    );
  }

  return (
    <GateFrame label="Email" tone="comms" status={status} badge={<Chip variant="accent">via Gmail</Chip>}>
      <p className="text-sm text-secondary">{typeof args.question === "string" ? args.question : "Send the generated deliverables?"}</p>
      <KeyValueGrid
        items={[
          { label: "To", value: recipientEmail },
          { label: "Subject", value: subject },
          { label: "Project", value: projectName },
          { label: "Recipient", value: recipientName !== "Team" ? recipientName : "" },
        ]}
      />
      <p className="text-2xs text-muted">The PDF report will be attached and sent from the connected Gmail account.</p>
      <div className="flex gap-2.5">
        <Button variant="primary" size="md" onClick={() => decide(true)} className="flex-1">
          Send Email
        </Button>
        <Button variant="secondary" size="md" onClick={() => decide(false)}>
          Cancel
        </Button>
      </div>
    </GateFrame>
  );
}
