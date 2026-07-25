import { useState } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import type { DecisionAction } from "../../hooks/agent-utils";
import GateFrame from "../GateFrame";
import DecisionBar from "../DecisionBar";
import Chip from "../../ui/Chip";
import Button from "../../ui/Button";
import type { GateCardProps } from "../types";

/** Ported from components/WbsExcelApproval.tsx (plan §F). */
export default function WbsExcelCard({ args, status, respond }: GateCardProps) {
  const [decided, setDecided] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  const allowedDecisions = (args.allowed_decisions as DecisionAction[]) ?? [];
  const useDecisionMenu = allowedDecisions.some((a) => a !== "approve" && a !== "reject");
  const totalMandays = args.total_mandays;
  const timelineMonths = args.timeline_months;

  const summaryParts: string[] = [];
  if (typeof totalMandays === "number") summaryParts.push(`${totalMandays} MD`);
  if (typeof timelineMonths === "number") summaryParts.push(`${timelineMonths} months`);

  function decide(approved: boolean) {
    setDecided(true);
    setDecision(approved ? "approved" : "rejected");
    void respond?.({ action: approved ? "approve" : "reject", approved });
  }

  if (decided && status === ToolCallStatus.Executing) {
    return (
      <GateFrame label="WBS Excel Export" tone="export" status={status}>
        <p className="text-xs text-muted">{decision === "approved" ? "Generating Excel file…" : "Export cancelled."}</p>
      </GateFrame>
    );
  }

  return (
    <GateFrame label="WBS Excel Export" tone="export" status={status} badge={<Chip variant="info">.xlsx</Chip>}>
      {summaryParts.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {summaryParts.map((part, i) => (
            <Chip key={i} variant="accent" numeric>
              {part}
            </Chip>
          ))}
        </div>
      )}
      <p className="text-sm text-secondary">{typeof args.question === "string" ? args.question : "Generate the WBS Excel file?"}</p>
      <div className="rounded-sm border border-line bg-well px-3 py-2.5">
        <p className="text-xs leading-relaxed text-muted">
          Clones the BnK template with live BA/QC/PM formulas and a dynamic Delivery Plan grid.
        </p>
      </div>
      {useDecisionMenu ? (
        <DecisionBar
          allowedDecisions={allowedDecisions}
          approveLabel="Generate .xlsx"
          onApprove={() => decide(true)}
          onReject={() => decide(false)}
          onDecision={() => decide(true)}
        />
      ) : (
        <div className="flex gap-2.5">
          <Button variant="primary" size="md" onClick={() => decide(true)} className="flex-1">
            Generate .xlsx
          </Button>
          <Button variant="secondary" size="md" onClick={() => decide(false)}>
            Cancel
          </Button>
        </div>
      )}
    </GateFrame>
  );
}
