import { useState } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import type { DecisionAction } from "../../hooks/agent-utils";
import GateFrame from "../GateFrame";
import DecisionBar from "../DecisionBar";
import Chip from "../../ui/Chip";
import Button from "../../ui/Button";
import { colorForKey } from "../ColorScale";
import type { GateCardProps } from "../types";

const ROLE_LABELS: Record<string, string> = { BE: "BE", FE_Mobile: "FE/Mob", BA: "BA", QC: "QC", PM: "PM" };

/** Same defensive normalisation as the old WbsApproval.tsx: the model
 * sometimes emits these dict/array fields as JSON/Python-repr strings. */
function normalizeRoleMap(value: unknown): Record<string, number> {
  let v = value;
  if (typeof v === "string") {
    const s = v.trim();
    if (!s || (s[0] !== "{" && s[0] !== "[")) return {};
    try {
      v = JSON.parse(s);
    } catch {
      try {
        v = JSON.parse(s.replace(/'/g, '"'));
      } catch {
        return {};
      }
    }
  }
  if (!v || typeof v !== "object" || Array.isArray(v)) return {};
  const out: Record<string, number> = {};
  for (const [role, md] of Object.entries(v as Record<string, unknown>)) {
    const n = typeof md === "number" ? md : Number(md);
    if (role.length > 1 && Number.isFinite(n)) out[role] = n;
  }
  return out;
}

function normalizeObjectList<T = Record<string, unknown>>(value: unknown): T[] {
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
  if (Array.isArray(v)) return v as T[];
  if (v && typeof v === "object") return Object.values(v as Record<string, T>);
  return [];
}

/** Ported from components/WbsApproval.tsx (plan §F). Role chips use
 * ColorScale (plan §F.5) instead of the old bespoke ROLE_COLORS rainbow. */
export default function WbsCard({ args, status, respond }: GateCardProps) {
  const [modifications, setModifications] = useState("");
  const [decided, setDecided] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  const allowedDecisions = (args.allowed_decisions as DecisionAction[]) ?? [];
  const useDecisionMenu = allowedDecisions.some((a) => a !== "approve" && a !== "reject");
  const totalMandays = args.total_mandays;
  const totalManmonths = args.total_manmonths;
  const timelineWeeks = args.timeline_weeks;
  const timelineMonths = args.timeline_months;
  const roleMap = normalizeRoleMap(args.effort_by_role);
  const moduleList = normalizeObjectList<{ code?: string; name?: string; total_md?: number | string }>(args.effort_by_module);

  function decide(payload: Record<string, unknown>, approved: boolean) {
    setDecided(true);
    setDecision(approved ? "approved" : "rejected");
    void respond?.(payload);
  }
  const approve = () => decide({ action: "approve", approved: true, modifications: modifications.trim() || undefined }, true);
  const reject = () => decide({ action: "reject", approved: false, modifications: modifications.trim() || undefined }, false);

  const summaryParts: string[] = [];
  if (typeof totalMandays === "number") summaryParts.push(`${totalMandays} MD`);
  if (typeof totalManmonths === "number") summaryParts.push(`${totalManmonths} months`);
  if (typeof timelineWeeks === "number") summaryParts.push(`${timelineWeeks} wks`);

  if (decided && status === ToolCallStatus.Executing) {
    return (
      <GateFrame label="WBS Plan" tone="decision" status={status}>
        <p className="text-xs text-muted">{decision === "approved" ? "WBS plan approved — continuing…" : "Revision requested — regenerating…"}</p>
      </GateFrame>
    );
  }

  return (
    <GateFrame label="WBS Plan" tone="decision" status={status}>
      {summaryParts.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {summaryParts.map((part, i) => (
            <Chip key={i} variant="accent" numeric>
              {part}
            </Chip>
          ))}
          {typeof timelineMonths === "number" && <Chip variant="neutral">{timelineMonths}mo timeline</Chip>}
        </div>
      )}

      <p className="text-sm text-secondary">{typeof args.question === "string" ? args.question : "Review the WBS plan."}</p>

      {Object.keys(roleMap).length > 0 && (
        <div className="rounded-sm border border-line bg-well px-3 py-2.5">
          <p className="label-caps mb-2 text-2xs font-semibold text-muted">Effort by Role</p>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(roleMap).map(([role, md]) => (
              <Chip key={role} variant={colorForKey(role)} numeric>
                {ROLE_LABELS[role] ?? role} {md}md
              </Chip>
            ))}
          </div>
        </div>
      )}

      {moduleList.length > 0 && (
        <div className="overflow-hidden rounded-sm border border-line">
          <p className="label-caps border-b border-line px-3 py-2 text-2xs font-semibold text-muted">Effort by Module</p>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-line text-left">
                <th className="w-20 px-3 py-1.5 font-semibold text-muted">Code</th>
                <th className="px-2 py-1.5 font-semibold text-muted">Module</th>
                <th className="w-16 px-3 py-1.5 text-right font-semibold text-muted">MD</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {moduleList.map((row, i) => (
                <tr key={row.code ?? i}>
                  <td className="px-3 py-1.5 font-mono text-muted">{row.code}</td>
                  <td className="px-2 py-1.5 text-secondary">{row.name}</td>
                  <td className="px-3 py-1.5 text-right font-semibold text-accent-text tnum">{row.total_md}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <label className="block text-xs font-medium text-muted">
        Changes (if rejecting)
        <textarea
          className="mt-1.5 w-full resize-none rounded-sm border border-line bg-app px-3 py-2.5 text-xs leading-relaxed text-fg placeholder:text-muted focus:border-accent-hi focus:outline-none"
          rows={2}
          placeholder="e.g. Increase QA allocation to 20% of total effort…"
          value={modifications}
          onChange={(e) => setModifications(e.target.value)}
        />
      </label>

      {useDecisionMenu ? (
        <DecisionBar
          allowedDecisions={allowedDecisions}
          approveLabel="Approve Plan"
          onApprove={approve}
          onReject={(t) => decide({ action: "reject", approved: false, modifications: t || undefined }, false)}
          onDecision={(payload) => decide(payload, true)}
        />
      ) : (
        <div className="flex gap-2.5">
          <Button variant="primary" size="md" onClick={approve} className="flex-1">
            Approve Plan
          </Button>
          <Button variant="secondary" size="md" onClick={reject}>
            Reject
          </Button>
        </div>
      )}
    </GateFrame>
  );
}
