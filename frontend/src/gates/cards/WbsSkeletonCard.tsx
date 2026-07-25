import { useState } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import type { DecisionAction } from "../../hooks/agent-utils";
import GateFrame from "../GateFrame";
import DecisionBar from "../DecisionBar";
import Chip from "../../ui/Chip";
import Button from "../../ui/Button";
import type { GateCardProps } from "../types";

type SkeletonModule = { code?: string; name?: string };
type SkeletonPhase = { code?: string; name?: string; modules?: SkeletonModule[] };

/** Same defensive normalisation as the old WbsSkeletonApproval.tsx: the
 * model sometimes emits `phases` as a JSON/Python-repr string or a
 * numeric-keyed dict; a bare Array.isArray guard would then render an
 * empty skeleton. */
function normalizePhases(value: unknown): SkeletonPhase[] {
  let v = value;
  if (typeof v === "string") {
    const s = v.trim();
    if (!s || (s[0] !== "[" && s[0] !== "{")) return [];
    try {
      v = JSON.parse(s);
    } catch {
      try {
        v = JSON.parse(s.replace(/'/g, '"'));
      } catch {
        return [];
      }
    }
  }
  if (Array.isArray(v)) return v as SkeletonPhase[];
  if (v && typeof v === "object") return Object.values(v as Record<string, SkeletonPhase>);
  return [];
}

/** Ported from components/WbsSkeletonApproval.tsx (plan §F). */
export default function WbsSkeletonCard({ args, status, respond }: GateCardProps) {
  const [modifications, setModifications] = useState("");
  const [decided, setDecided] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  const allowedDecisions = (args.allowed_decisions as DecisionAction[]) ?? [];
  const useDecisionMenu = allowedDecisions.some((a) => a !== "approve" && a !== "reject");
  const projectName = typeof args.project_name === "string" ? args.project_name : "";
  const projectCode = typeof args.project_code === "string" ? args.project_code : "";
  const phaseTree = normalizePhases(args.phases);

  function decide(payload: Record<string, unknown>, approved: boolean) {
    setDecided(true);
    setDecision(approved ? "approved" : "rejected");
    void respond?.(payload);
  }
  const approve = () => decide({ action: "approve", approved: true, modifications: modifications.trim() || undefined }, true);
  const reject = () => decide({ action: "reject", approved: false, modifications: modifications.trim() || undefined }, false);

  if (decided && status === ToolCallStatus.Executing) {
    return (
      <GateFrame label="WBS Skeleton" tone="decision" status={status}>
        <p className="text-xs text-muted">{decision === "approved" ? "WBS structure approved — continuing…" : "Revision requested — regenerating…"}</p>
      </GateFrame>
    );
  }

  return (
    <GateFrame label="WBS Skeleton" tone="decision" status={status}>
      {(projectName || projectCode) && (
        <div className="flex flex-wrap gap-1.5">
          {projectName && <Chip variant="accent">{projectName}</Chip>}
          {projectCode && <Chip variant="neutral">{projectCode}</Chip>}
        </div>
      )}
      <p className="text-sm text-secondary">{typeof args.question === "string" ? args.question : "Review the WBS structure."}</p>

      {phaseTree.length > 0 && (
        <div className="overflow-hidden rounded-sm border border-line">
          <p className="label-caps border-b border-line px-3 py-2 text-2xs font-semibold text-muted">Structure</p>
          <div className="divide-y divide-line">
            {phaseTree.map((phase, i) => (
              <div key={phase.code ?? i}>
                <div className="flex items-center gap-2 border-l-2 border-accent px-3 py-2">
                  <span className="font-mono text-2xs text-accent-text">{phase.code}</span>
                  <span className="text-xs font-semibold text-fg">{phase.name}</span>
                </div>
                {Array.isArray(phase.modules) &&
                  phase.modules.map((mod) => (
                    <div key={mod.code} className="flex items-center gap-2 border-l-2 border-line bg-well py-1.5 pl-7 pr-3">
                      <span className="font-mono text-2xs text-muted">{mod.code}</span>
                      <span className="text-xs text-secondary">{mod.name}</span>
                    </div>
                  ))}
              </div>
            ))}
          </div>
        </div>
      )}

      <label className="block text-xs font-medium text-muted">
        Changes (if rejecting)
        <textarea
          className="mt-1.5 w-full resize-none rounded-sm border border-line bg-app px-3 py-2.5 text-xs leading-relaxed text-fg placeholder:text-muted focus:border-accent-hi focus:outline-none"
          rows={2}
          placeholder="e.g. Split Phase 2 into Testing and Deployment phases…"
          value={modifications}
          onChange={(e) => setModifications(e.target.value)}
        />
      </label>

      {useDecisionMenu ? (
        <DecisionBar
          allowedDecisions={allowedDecisions}
          approveLabel="Approve Structure"
          onApprove={approve}
          onReject={(t) => decide({ action: "reject", approved: false, modifications: t || undefined }, false)}
          onDecision={(payload) => decide(payload, true)}
        />
      ) : (
        <div className="flex gap-2.5">
          <Button variant="primary" size="md" onClick={approve} className="flex-1">
            Approve Structure
          </Button>
          <Button variant="secondary" size="md" onClick={reject}>
            Reject
          </Button>
        </div>
      )}
    </GateFrame>
  );
}
