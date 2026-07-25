import { useState } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import type { DecisionAction } from "../../hooks/agent-utils";
import GateFrame from "../GateFrame";
import DecisionBar from "../DecisionBar";
import Chip from "../../ui/Chip";
import Button from "../../ui/Button";
import type { GateCardProps } from "../types";

/** Ported from components/DeliveryExportApproval.tsx (plan §F). */
export default function DeliveryExportCard({ args, status, respond }: GateCardProps) {
  const [decided, setDecided] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  const allowedDecisions = (args.allowed_decisions as DecisionAction[]) ?? [];
  const useDecisionMenu = allowedDecisions.some((a) => a !== "approve" && a !== "reject");
  const system = typeof args.system === "string" ? args.system : "";
  const sys = (system || "tracker").toUpperCase();
  const live = args.dry_run === false;

  function decide(approved: boolean) {
    setDecided(true);
    setDecision(approved ? "approved" : "rejected");
    void respond?.({ action: approved ? "approve" : "reject", approved });
  }

  if (decided && status === ToolCallStatus.Executing) {
    return (
      <GateFrame label={`Delivery Export · ${sys}`} tone="export" status={status}>
        <p className="text-xs text-muted">
          {decision === "approved" ? (live ? `Syncing work items to ${sys}…` : `Building ${sys} preview…`) : "Export cancelled."}
        </p>
      </GateFrame>
    );
  }

  return (
    <GateFrame label={`Delivery Export · ${sys}`} tone="export" status={status} badge={<Chip variant={live ? "warn" : "info"}>{live ? "LIVE" : "preview"}</Chip>}>
      <p className="text-sm text-secondary">
        {typeof args.question === "string" ? args.question : `Push the WBS work items to ${sys}?`}
      </p>
      <div className="rounded-sm border border-line bg-well px-3 py-2.5">
        <p className="text-xs leading-relaxed text-muted">
          {live
            ? `Each work item maps to one ${sys} issue keyed by its CSM id — re-runs create, update or skip idempotently (never duplicates).`
            : `Writes a reviewable preview only; nothing leaves the process. Re-run with a live sync to push.`}
        </p>
      </div>
      {useDecisionMenu ? (
        <DecisionBar
          allowedDecisions={allowedDecisions}
          approveLabel={live ? `Sync to ${sys}` : "Build preview"}
          onApprove={() => decide(true)}
          onReject={() => decide(false)}
          onDecision={() => decide(true)}
        />
      ) : (
        <div className="flex gap-2.5">
          <Button variant="primary" size="md" onClick={() => decide(true)} className="flex-1">
            {live ? `Sync to ${sys}` : "Build preview"}
          </Button>
          <Button variant="secondary" size="md" onClick={() => decide(false)}>
            Cancel
          </Button>
        </div>
      )}
    </GateFrame>
  );
}
