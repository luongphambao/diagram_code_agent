import { useState } from "react";
import type { PendingInterrupt, DecisionPayload } from "../hooks/useDiagramAgent";
import DecisionActions from "./DecisionActions";

interface WbsSkeletonApprovalProps {
  interrupt: PendingInterrupt;
  onResolve: (approved: boolean, modifications?: string) => void;
  onDecision?: (payload: DecisionPayload) => void;
  disabled?: boolean;
}

type SkeletonModule = { code?: string; name?: string };
type SkeletonPhase = { code?: string; name?: string; modules?: SkeletonModule[] };

/**
 * Normalise the `phases` tree to a real array. The model sometimes emits it as a
 * JSON/Python-repr string or a numeric-keyed dict; a bare `Array.isArray(...)` guard
 * then renders NO structure at all (the "empty skeleton card" symptom). Parse strings,
 * unwrap numeric-keyed dicts, and return [] for anything else.
 */
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

export default function WbsSkeletonApproval({
  interrupt,
  onResolve,
  onDecision,
  disabled = false,
}: WbsSkeletonApprovalProps) {
  const [modifications, setModifications] = useState("");
  const [decided, setDecided] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  const allowedDecisions = interrupt.data.allowed_decisions ?? [];
  const useDecisionMenu =
    onDecision != null && allowedDecisions.some((a: string) => a !== "approve" && a !== "reject");

  const { question, project_name, project_code, phases } = interrupt.data;
  const phaseTree = normalizePhases(phases);

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

  return (
    <div className="flex w-full flex-col overflow-hidden rounded-2xl border border-teal-500/20 bg-teal-950/15">
      {/* Header */}
      <div className="flex items-center gap-2.5 border-b border-white/8 bg-white/4 px-4 py-3">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-teal-500/20">
          <svg
            className="h-3.5 w-3.5 text-teal-300"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M3 10h18M3 14h18M10 3v18M14 3v18M3 6a3 3 0 013-3h12a3 3 0 013 3v12a3 3 0 01-3 3H6a3 3 0 01-3-3V6z"
            />
          </svg>
        </div>
        <p className="flex-1 text-sm font-semibold text-white">WBS Structure Review</p>
        <span className="rounded-full border border-teal-500/25 bg-teal-500/10 px-2 py-0.5 text-[11px] font-medium text-teal-300">
          HITL Gate
        </span>
      </div>

      {decided ? (
        <div className="px-4 py-3">
          <p className="text-xs text-slate-500">
            {decision === "approved"
              ? "WBS structure approved — continuing…"
              : "Revision requested — regenerating…"}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3 px-4 py-4">
          {/* Project chips */}
          {(project_name || project_code) && (
            <div className="flex flex-wrap gap-1.5">
              {project_name && (
                <span className="rounded-full border border-teal-500/20 bg-teal-900/20 px-2.5 py-0.5 text-[11px] font-medium text-teal-200">
                  {project_name}
                </span>
              )}
              {project_code && (
                <span className="rounded-full border border-white/10 bg-white/6 px-2.5 py-0.5 text-[11px] font-mono text-slate-400">
                  {project_code}
                </span>
              )}
            </div>
          )}

          {/* Question */}
          <p className="text-xs leading-relaxed text-slate-400">{question}</p>

          {/* Phase / module tree */}
          {phaseTree.length > 0 && (
            <div className="rounded-xl border border-white/8 bg-white/3 overflow-hidden">
              <p className="border-b border-white/6 px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-slate-500">
                Structure
              </p>
              <div className="divide-y divide-white/5">
                {phaseTree.map((phase, i) => (
                  <div key={phase.code ?? i}>
                    {/* Phase row */}
                    <div className="flex items-center gap-2 border-l-2 border-teal-500/60 px-3 py-2">
                      <span className="font-mono text-[10px] text-teal-400/70">{phase.code}</span>
                      <span className="text-xs font-semibold text-slate-200">{phase.name}</span>
                    </div>
                    {/* Module rows */}
                    {Array.isArray(phase.modules) &&
                      phase.modules.map((mod) => (
                        <div
                          key={mod.code}
                          className="flex items-center gap-2 border-l-2 border-white/6 bg-white/2 pl-7 pr-3 py-1.5"
                        >
                          <span className="font-mono text-[10px] text-slate-600">{mod.code}</span>
                          <span className="text-[11px] text-slate-400">{mod.name}</span>
                        </div>
                      ))}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Notes textarea */}
          <div>
            <label className="mb-1.5 block text-[11px] font-medium text-slate-600">
              Changes (if rejecting)
            </label>
            <textarea
              className="w-full resize-none rounded-xl border border-white/8 bg-black/30 px-3 py-2.5 text-xs leading-relaxed text-slate-200 placeholder:text-slate-700 focus:border-teal-500/40 focus:outline-none"
              rows={2}
              placeholder="e.g. Split Phase 2 into Testing and Deployment phases…"
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
              approveLabel="Approve Structure"
              onApprove={approve}
              onReject={(t) => {
                setDecided(true);
                setDecision("rejected");
                onResolve(false, t || undefined);
              }}
              onDecision={onDecision!}
            />
          ) : (
            <div className="flex gap-2.5">
              <button
                onClick={approve}
                disabled={disabled}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-teal-700 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-teal-900/30 transition-all hover:bg-teal-600 active:scale-98 disabled:opacity-50"
              >
                <svg
                  className="h-3.5 w-3.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                Approve Structure
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
