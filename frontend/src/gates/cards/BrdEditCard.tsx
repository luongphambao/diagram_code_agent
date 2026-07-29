import { useState } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import type { DecisionAction } from "../../hooks/agent-utils";
import GateFrame from "../GateFrame";
import DecisionBar from "../DecisionBar";
import Chip from "../../ui/Chip";
import Button from "../../ui/Button";
import type { GateCardProps } from "../types";

type DiffLineType = "equal" | "insert" | "delete";
interface DiffLine {
  type?: DiffLineType;
  text?: string;
}
interface SectionDiff {
  section_id?: string;
  diff?: DiffLine[];
}

const LINE_CLASS: Record<DiffLineType, string> = {
  equal: "text-secondary",
  insert: "bg-ok/10 text-ok-text",
  delete: "bg-danger/10 text-danger-text line-through decoration-danger/50",
};
const LINE_PREFIX: Record<DiffLineType, string> = { equal: "  ", insert: "+ ", delete: "- " };

function normalizeSections(value: unknown): SectionDiff[] {
  if (Array.isArray(value)) return value as SectionDiff[];
  return [];
}
function normalizeFailed(value: unknown): string[] {
  return Array.isArray(value) ? (value as string[]) : [];
}

/** edit_brd_section's approval card — the diff is computed BACKEND-side
 * (session/gate_decisions.py's preview_ops + difflib), never trusted from
 * the model's own description of the edit. This card only renders it. */
export default function BrdEditCard({ args, status, respond }: GateCardProps) {
  const [decided, setDecided] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  const allowedDecisions = (args.allowed_decisions as DecisionAction[]) ?? [];
  const useDecisionMenu = allowedDecisions.some((a) => a !== "approve" && a !== "reject");
  const opCount = typeof args.op_count === "number" ? args.op_count : undefined;
  const sections = normalizeSections(args.sections);
  const failed = normalizeFailed(args.failed);

  function decide(approved: boolean) {
    setDecided(true);
    setDecision(approved ? "approved" : "rejected");
    void respond?.({ action: approved ? "approve" : "reject", approved });
  }

  if (decided && status === ToolCallStatus.Executing) {
    return (
      <GateFrame label="BRD Section Edit" tone="decision" status={status}>
        <p className="text-xs text-muted">{decision === "approved" ? "Applying edit…" : "Edit cancelled."}</p>
      </GateFrame>
    );
  }

  return (
    <GateFrame
      label="BRD Section Edit"
      tone="decision"
      status={status}
      badge={opCount !== undefined ? <Chip variant="accent" numeric>{opCount} op{opCount === 1 ? "" : "s"}</Chip> : undefined}
    >
      <p className="text-sm text-secondary">{typeof args.question === "string" ? args.question : "Review the change(s) below and approve or reject."}</p>

      {sections.length > 0 ? (
        <div className="flex flex-col gap-2.5">
          {sections.map((sec, i) => (
            <div key={sec.section_id ?? i} className="overflow-hidden rounded-sm border border-line">
              <p className="border-b border-line bg-well px-3 py-1.5 font-mono text-2xs font-semibold text-muted">
                {sec.section_id}
              </p>
              <div className="max-h-56 overflow-y-auto px-3 py-2 font-mono text-2xs leading-relaxed">
                {(sec.diff ?? []).map((line, j) => {
                  const t = line.type ?? "equal";
                  return (
                    <div key={j} className={`whitespace-pre-wrap ${LINE_CLASS[t]}`}>
                      {LINE_PREFIX[t]}
                      {line.text}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-sm border border-line bg-well px-3 py-2.5">
          <p className="text-xs leading-relaxed text-muted">
            No preview available for this edit — the referenced section(s) may not resolve. Approving will still attempt the
            edit; a bad section id or stale checksum is rejected without touching the file.
          </p>
        </div>
      )}

      {failed.length > 0 && (
        <div className="rounded-sm border border-warn/30 bg-warn/10 px-3 py-2.5">
          <p className="text-xs font-semibold text-warn-text">
            {failed.length} op{failed.length > 1 ? "s" : ""} could not be previewed
          </p>
          <div className="mt-1 flex flex-col gap-0.5">
            {failed.map((f, i) => (
              <p key={i} className="text-2xs text-warn-text">
                {f}
              </p>
            ))}
          </div>
        </div>
      )}

      {useDecisionMenu ? (
        <DecisionBar
          allowedDecisions={allowedDecisions}
          approveLabel="Apply Changes"
          onApprove={() => decide(true)}
          onReject={() => decide(false)}
          onDecision={() => decide(true)}
        />
      ) : (
        <div className="flex gap-2.5">
          <Button variant="primary" size="md" onClick={() => decide(true)} className="flex-1">
            Apply Changes
          </Button>
          <Button variant="secondary" size="md" onClick={() => decide(false)}>
            Reject
          </Button>
        </div>
      )}
    </GateFrame>
  );
}
