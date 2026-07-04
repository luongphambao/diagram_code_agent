import { useState } from "react";
import type { PendingInterrupt, DecisionPayload } from "../hooks/useDiagramAgent";
import DecisionActions from "./DecisionActions";

interface WbsApprovalProps {
  interrupt: PendingInterrupt;
  onResolve: (approved: boolean, modifications?: string) => void;
  onDecision?: (payload: DecisionPayload) => void;
  disabled?: boolean;
}

const ROLE_COLORS: Record<string, string> = {
  BE: "border-blue-500/25 bg-blue-900/20 text-blue-300",
  FE_Mobile: "border-violet-500/25 bg-violet-900/20 text-violet-300",
  BA: "border-amber-500/25 bg-amber-900/20 text-amber-300",
  QC: "border-rose-500/25 bg-rose-900/20 text-rose-300",
  PM: "border-emerald-500/25 bg-emerald-900/20 text-emerald-300",
};

const ROLE_LABELS: Record<string, string> = {
  BE: "BE",
  FE_Mobile: "FE/Mob",
  BA: "BA",
  QC: "QC",
  PM: "PM",
};

export default function WbsApproval({ interrupt, onResolve, onDecision, disabled = false }: WbsApprovalProps) {
  const [modifications, setModifications] = useState("");
  const [decided, setDecided] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  const allowedDecisions = interrupt.data.allowed_decisions ?? [];
  const useDecisionMenu = onDecision != null &&
    allowedDecisions.some((a: string) => a !== "approve" && a !== "reject");

  const {
    question,
    total_mandays,
    total_manmonths,
    timeline_weeks,
    timeline_months,
    effort_by_role,
    effort_by_module,
  } = interrupt.data;

  // Defensive: the model sometimes emits dict args as a (single- or double-quoted)
  // string. A raw string here makes `Object.entries(...)` iterate characters, rendering
  // one "Nmd" chip per character. Normalise to a plain {role: number} object; anything
  // that can't be parsed into that shape renders nothing rather than garbage.
  const roleMap = normalizeRoleMap(effort_by_role);

  const approve = () => {
    setDecided(true);
    setDecision("approved");
    onResolve(true, modifications.trim() || undefined);
  };

  const reject = () => {
    setDecided(true);
    setDecision("rejected");
    onResolve(false, modifications.trim() || undefined);
  };

  const summaryParts: string[] = [];
  if (total_mandays != null) summaryParts.push(`${total_mandays} MD`);
  if (total_manmonths != null) summaryParts.push(`${total_manmonths} months`);
  if (timeline_weeks != null) summaryParts.push(`${timeline_weeks} wks`);

  return (
    <div className="flex w-full flex-col overflow-hidden rounded-2xl border border-amber-500/20 bg-amber-950/15">
      {/* Header */}
      <div className="flex items-center gap-2.5 border-b border-white/8 bg-white/4 px-4 py-3">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-amber-500/20">
          <svg className="h-3.5 w-3.5 text-amber-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.5h18M3 17.25h18M3 9.75h18M3 6h18M7.5 3v18M16.5 3v18M5.25 3h13.5A2.25 2.25 0 0121 5.25v13.5A2.25 2.25 0 0118.75 21H5.25A2.25 2.25 0 013 18.75V5.25A2.25 2.25 0 015.25 3z" />
          </svg>
        </div>
        <p className="flex-1 text-sm font-semibold text-white">WBS Plan Review</p>
        <span className="rounded-full border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-300">
          HITL Gate
        </span>
      </div>

      {decided ? (
        <div className="px-4 py-3">
          <p className="text-xs text-slate-500">
            {decision === "approved" ? "WBS plan approved — continuing…" : "Revision requested — regenerating…"}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3 px-4 py-4">
          {/* Summary row */}
          {summaryParts.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {summaryParts.map((part, i) => (
                <span
                  key={i}
                  className="rounded-full border border-amber-500/20 bg-amber-900/20 px-2.5 py-0.5 text-[11px] font-semibold text-amber-200"
                >
                  {part}
                </span>
              ))}
              {timeline_months != null && (
                <span className="rounded-full border border-white/10 bg-white/6 px-2.5 py-0.5 text-[11px] text-slate-400">
                  {timeline_months}mo timeline
                </span>
              )}
            </div>
          )}

          {/* Question */}
          <p className="text-xs leading-relaxed text-slate-400">{question}</p>

          {/* Role breakdown */}
          {roleMap && Object.keys(roleMap).length > 0 && (
            <div className="rounded-xl border border-white/8 bg-white/3 px-3 py-2.5">
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-slate-500">Effort by Role</p>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(roleMap).map(([role, md]) => {
                  const colorClass = ROLE_COLORS[role] ?? "border-white/10 bg-white/6 text-slate-300";
                  const label = ROLE_LABELS[role] ?? role;
                  return (
                    <span
                      key={role}
                      className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${colorClass}`}
                    >
                      {label} {md}md
                    </span>
                  );
                })}
              </div>
            </div>
          )}

          {/* Effort by module table */}
          {Array.isArray(effort_by_module) && effort_by_module.length > 0 && (
            <div className="rounded-xl border border-white/8 bg-white/3 overflow-hidden">
              <p className="border-b border-white/6 px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-slate-500">
                Effort by Module
              </p>
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-white/5 text-left">
                    <th className="px-3 py-1.5 font-semibold text-slate-600 w-20">Code</th>
                    <th className="px-2 py-1.5 font-semibold text-slate-600">Module</th>
                    <th className="px-3 py-1.5 text-right font-semibold text-slate-600 w-16">MD</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {effort_by_module.map((row) => (
                    <tr key={row.code} className="hover:bg-white/3">
                      <td className="px-3 py-1.5 font-mono text-slate-600">{row.code}</td>
                      <td className="px-2 py-1.5 text-slate-400">{row.name}</td>
                      <td className="px-3 py-1.5 text-right font-semibold text-amber-300/80">{row.total_md}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Notes textarea */}
          <div>
            <label className="mb-1.5 block text-[11px] font-medium text-slate-600">
              Changes (if rejecting)
            </label>
            <textarea
              className="w-full resize-none rounded-xl border border-white/8 bg-black/30 px-3 py-2.5 text-xs leading-relaxed text-slate-200 placeholder:text-slate-700 focus:border-amber-500/40 focus:outline-none"
              rows={2}
              placeholder="e.g. Increase QA allocation to 20% of total effort…"
              value={modifications}
              onChange={(e) => setModifications(e.target.value)}
              disabled={disabled}
            />
          </div>

          {/* Actions */}
          {useDecisionMenu ? (
            <DecisionActions
              allowedDecisions={allowedDecisions}
              disabled={disabled}
              approveLabel="Approve Plan"
              onApprove={approve}
              onReject={(t) => { setDecided(true); setDecision("rejected"); onResolve(false, t || undefined); }}
              onDecision={onDecision!}
            />
          ) : (
            <div className="flex gap-2.5">
              <button
                onClick={approve}
                disabled={disabled}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-amber-700 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-amber-900/30 transition-all hover:bg-amber-600 active:scale-98 disabled:opacity-50"
              >
                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                Approve Plan
              </button>
              <button
                onClick={reject}
                disabled={disabled}
                className="rounded-xl border border-white/10 bg-white/4 px-4 py-2.5 text-xs font-semibold text-slate-300 transition-all hover:bg-white/8 disabled:opacity-50"
              >
                Reject
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
