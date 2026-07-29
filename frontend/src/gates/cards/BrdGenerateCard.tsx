import { useState } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import type { DecisionAction } from "../../hooks/agent-utils";
import GateFrame from "../GateFrame";
import DecisionBar from "../DecisionBar";
import Chip from "../../ui/Chip";
import Button from "../../ui/Button";
import type { GateCardProps } from "../types";

/** generate_brd_docx's approval card — renders out.brd.docx from the
 * template + the approved outline + drafted section content. A pure
 * "generate this file?" confirm, same shape as WbsExcelCard. */
export default function BrdGenerateCard({ args, status, respond }: GateCardProps) {
  const [decided, setDecided] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  const allowedDecisions = (args.allowed_decisions as DecisionAction[]) ?? [];
  const useDecisionMenu = allowedDecisions.some((a) => a !== "approve" && a !== "reject");
  const sectionCount = args.section_count;
  const fillCount = args.fill_count;

  const summaryParts: string[] = [];
  if (typeof fillCount === "number") summaryParts.push(`${fillCount} sections to fill`);
  if (typeof sectionCount === "number") summaryParts.push(`${sectionCount} total`);

  function decide(approved: boolean) {
    setDecided(true);
    setDecision(approved ? "approved" : "rejected");
    void respond?.({ action: approved ? "approve" : "reject", approved });
  }

  if (decided && status === ToolCallStatus.Executing) {
    return (
      <GateFrame label="BRD Document" tone="export" status={status}>
        <p className="text-xs text-muted">{decision === "approved" ? "Generating out.brd.docx…" : "Generation cancelled."}</p>
      </GateFrame>
    );
  }

  return (
    <GateFrame label="BRD Document" tone="export" status={status} badge={<Chip variant="info">.docx</Chip>}>
      {summaryParts.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {summaryParts.map((part, i) => (
            <Chip key={i} variant="accent" numeric>
              {part}
            </Chip>
          ))}
        </div>
      )}
      <p className="text-sm text-secondary">
        {typeof args.question === "string" ? args.question : "Generate the BRD .docx from the approved outline and drafted content?"}
      </p>
      <div className="rounded-sm border border-line bg-well px-3 py-2.5">
        <p className="text-xs leading-relaxed text-muted">
          Clones the BnK BRD template and fills every approved section. Sections without drafted content are skipped, not
          left blank — you'll see what was skipped in the reply.
        </p>
      </div>
      {useDecisionMenu ? (
        <DecisionBar
          allowedDecisions={allowedDecisions}
          approveLabel="Generate .docx"
          onApprove={() => decide(true)}
          onReject={() => decide(false)}
          onDecision={() => decide(true)}
        />
      ) : (
        <div className="flex gap-2.5">
          <Button variant="primary" size="md" onClick={() => decide(true)} className="flex-1">
            Generate .docx
          </Button>
          <Button variant="secondary" size="md" onClick={() => decide(false)}>
            Cancel
          </Button>
        </div>
      )}
    </GateFrame>
  );
}
