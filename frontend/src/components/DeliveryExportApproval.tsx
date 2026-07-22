import { useState } from "react";
import type { PendingInterrupt, DecisionPayload } from "../hooks/useDiagramAgent";
import DecisionActions from "./DecisionActions";

interface DeliveryExportApprovalProps {
  interrupt: PendingInterrupt;
  onResolve: (approved: boolean) => void;
  onDecision?: (payload: DecisionPayload) => void;
  disabled?: boolean;
}

export default function DeliveryExportApproval({
  interrupt,
  onResolve,
  onDecision,
  disabled = false,
}: DeliveryExportApprovalProps) {
  const [decided, setDecided] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  const allowedDecisions = interrupt.data.allowed_decisions ?? [];
  const useDecisionMenu =
    onDecision != null && allowedDecisions.some((a: string) => a !== "approve" && a !== "reject");

  const { question, system, dry_run } = interrupt.data;
  const sys = (system || "tracker").toUpperCase();
  const live = dry_run === false;

  const approve = () => {
    setDecided(true);
    setDecision("approved");
    onResolve(true);
  };
  const cancel = () => {
    setDecided(true);
    setDecision("rejected");
    onResolve(false);
  };

  return (
    <div className="flex w-full flex-col overflow-hidden rounded-2xl border border-indigo-500/20 bg-indigo-950/15">
      {/* Header */}
      <div className="flex items-center gap-2.5 border-b border-white/8 bg-white/4 px-4 py-3">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-500/20">
          <svg
            className="h-3.5 w-3.5 text-indigo-300"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 7.5L12 3m0 0L7.5 7.5M12 3v13.5"
            />
          </svg>
        </div>
        <p className="flex-1 text-sm font-semibold text-white">Delivery export · {sys}</p>
        <span
          className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${
            live
              ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
              : "border-indigo-500/25 bg-indigo-500/10 text-indigo-300"
          }`}
        >
          {live ? "LIVE" : "preview"}
        </span>
      </div>

      {decided ? (
        <div className="px-4 py-3">
          <p className="text-xs text-slate-500">
            {decision === "approved"
              ? live
                ? `Syncing work items to ${sys}…`
                : `Building ${sys} preview…`
              : "Export cancelled."}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3 px-4 py-4">
          <p className="text-xs leading-relaxed text-slate-400">{question}</p>

          <div className="rounded-xl border border-white/8 bg-white/3 px-3 py-2.5">
            <div className="flex items-start gap-2">
              <svg
                className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-indigo-400/70"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"
                />
              </svg>
              <p className="text-[11px] leading-relaxed text-slate-500">
                {live
                  ? `Each work item maps to one ${sys} issue keyed by its CSM id — re-runs create, update or skip idempotently (never duplicates).`
                  : `Writes a reviewable preview only; nothing leaves the process. Re-run with a live sync to push.`}
              </p>
            </div>
          </div>

          {useDecisionMenu ? (
            <DecisionActions
              allowedDecisions={allowedDecisions}
              disabled={disabled}
              approveLabel={live ? `Sync to ${sys}` : "Build preview"}
              onApprove={approve}
              onReject={cancel}
              onDecision={onDecision!}
            />
          ) : (
            <div className="flex gap-2.5">
              <button
                onClick={approve}
                disabled={disabled}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-indigo-700 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-indigo-900/30 transition-all hover:bg-indigo-600 active:scale-98 disabled:opacity-50"
              >
                <svg
                  className="h-3.5 w-3.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14M13 6l6 6-6 6" />
                </svg>
                {live ? `Sync to ${sys}` : "Build preview"}
              </button>
              <button
                onClick={cancel}
                disabled={disabled}
                className="rounded-xl border border-white/10 bg-white/4 px-4 py-2.5 text-xs font-semibold text-slate-300 transition-all hover:bg-white/8 disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
