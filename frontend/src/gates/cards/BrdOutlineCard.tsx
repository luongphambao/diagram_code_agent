import { useState } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import type { DecisionAction } from "../../hooks/agent-utils";
import GateFrame from "../GateFrame";
import DecisionBar from "../DecisionBar";
import Chip from "../../ui/Chip";
import Button from "../../ui/Button";
import type { GateCardProps } from "../types";

type OutlineStatus = "fill" | "keep" | "skip";

interface OutlineItem {
  section_id?: string;
  title?: string;
  level?: number;
  source?: string;
  status?: OutlineStatus;
  notes?: string;
}

const STATUS_CHIP: Record<OutlineStatus, { variant: "accent" | "neutral" | "warn"; label: string }> = {
  fill: { variant: "accent", label: "fill" },
  keep: { variant: "neutral", label: "keep" },
  skip: { variant: "warn", label: "skip" },
};

function normalizeItems(value: unknown): OutlineItem[] {
  if (Array.isArray(value)) return value as OutlineItem[];
  if (value && typeof value === "object") return Object.values(value as Record<string, OutlineItem>);
  return [];
}

/** propose_brd_outline's approval card — the fill/keep/skip decision per
 * template section, before any section content is generated into a .docx. */
export default function BrdOutlineCard({ args, status, respond }: GateCardProps) {
  const [modifications, setModifications] = useState("");
  const [decided, setDecided] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  const allowedDecisions = (args.allowed_decisions as DecisionAction[]) ?? [];
  const useDecisionMenu = allowedDecisions.some((a) => a !== "approve" && a !== "reject");
  const items = normalizeItems(args.items);
  const fillCount = typeof args.fill_count === "number" ? args.fill_count : items.filter((i) => i.status === "fill").length;
  const skipCount = typeof args.skip_count === "number" ? args.skip_count : items.filter((i) => i.status === "skip").length;

  function decide(payload: Record<string, unknown>, approved: boolean) {
    setDecided(true);
    setDecision(approved ? "approved" : "rejected");
    void respond?.(payload);
  }
  const approve = () =>
    decide({ action: "approve", approved: true, modifications: modifications.trim() || undefined }, true);
  const reject = () =>
    decide({ action: "reject", approved: false, modifications: modifications.trim() || undefined }, false);

  if (decided && status === ToolCallStatus.Executing) {
    return (
      <GateFrame label="BRD Outline" tone="decision" status={status}>
        <p className="text-xs text-muted">
          {decision === "approved" ? "Outline approved — continuing…" : "Revision requested — redrafting outline…"}
        </p>
      </GateFrame>
    );
  }

  return (
    <GateFrame
      label="BRD Outline"
      tone="decision"
      status={status}
      badge={
        <div className="flex gap-1">
          <Chip variant="accent" numeric>{fillCount} fill</Chip>
          <Chip variant="warn" numeric>{skipCount} skip</Chip>
        </div>
      }
    >
      <p className="text-sm text-secondary">
        {typeof args.question === "string" ? args.question : "Review the BRD outline and approve or request changes."}
      </p>

      {items.length > 0 && (
        <div className="max-h-72 overflow-y-auto rounded-sm border border-line">
          <div className="divide-y divide-line">
            {items.map((item, i) => {
              const chip = STATUS_CHIP[item.status ?? "fill"] ?? STATUS_CHIP.fill;
              return (
                <div key={item.section_id ?? i} className="flex flex-col gap-0.5 px-3 py-2">
                  <div className="flex items-center gap-2">
                    <Chip variant={chip.variant}>{chip.label}</Chip>
                    <span className="truncate font-mono text-2xs text-muted">{item.section_id}</span>
                  </div>
                  <div className="flex items-baseline gap-2 pl-0.5">
                    <span className="text-xs font-medium text-fg">{item.title ?? item.section_id}</span>
                    {item.source && <span className="text-2xs text-muted">← {item.source}</span>}
                  </div>
                  {item.status === "skip" && item.notes && (
                    <p className="pl-0.5 text-2xs text-warn-text">{item.notes}</p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      <label className="block text-xs font-medium text-muted">
        Changes (if rejecting)
        <textarea
          className="mt-1.5 w-full resize-none rounded-sm border border-line bg-app px-3 py-2.5 text-xs leading-relaxed text-fg placeholder:text-muted focus:border-accent-hi focus:outline-none"
          rows={2}
          placeholder="e.g. Skip the Analysis Models section, fill Assumptions from the tech stack…"
          value={modifications}
          onChange={(e) => setModifications(e.target.value)}
        />
      </label>

      {useDecisionMenu ? (
        <DecisionBar
          allowedDecisions={allowedDecisions}
          approveLabel="Approve Outline"
          onApprove={approve}
          onReject={(t) => decide({ action: "reject", approved: false, modifications: t || undefined }, false)}
          onDecision={(payload) => decide(payload, true)}
        />
      ) : (
        <div className="flex gap-2.5">
          <Button variant="primary" size="md" onClick={approve} className="flex-1">
            Approve Outline
          </Button>
          <Button variant="secondary" size="md" onClick={reject}>
            Reject
          </Button>
        </div>
      )}
    </GateFrame>
  );
}
