import { useState } from "react";
import type { PendingInterrupt, DecisionPayload } from "../hooks/useDiagramAgent";
import DecisionActions from "./DecisionActions";

interface WbsExcelApprovalProps {
  interrupt: PendingInterrupt;
  onResolve: (approved: boolean) => void;
  onDecision?: (payload: DecisionPayload) => void;
  disabled?: boolean;
}

export default function WbsExcelApproval({
  interrupt,
  onResolve,
  onDecision,
  disabled = false,
}: WbsExcelApprovalProps) {
  const [decided, setDecided] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  const allowedDecisions = interrupt.data.allowed_decisions ?? [];
  const useDecisionMenu =
    onDecision != null && allowedDecisions.some((a: string) => a !== "approve" && a !== "reject");

  const { question, total_mandays, timeline_months } = interrupt.data;

  const summaryParts: string[] = [];
  if (total_mandays != null) summaryParts.push(`${total_mandays} MD`);
  if (timeline_months != null) summaryParts.push(`${timeline_months} months`);

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
    <div className="flex w-full flex-col overflow-hidden rounded-2xl border border-green-500/20 bg-green-950/15">
      {/* Header */}
      <div className="flex items-center gap-2.5 border-b border-white/8 bg-white/4 px-4 py-3">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-green-500/20">
          <svg
            className="h-3.5 w-3.5 text-green-300"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
            />
          </svg>
        </div>
        <p className="flex-1 text-sm font-semibold text-white">Export WBS Excel</p>
        <span className="rounded-full border border-green-500/25 bg-green-500/10 px-2 py-0.5 text-[11px] font-medium text-green-300">
          .xlsx
        </span>
      </div>

      {decided ? (
        <div className="px-4 py-3">
          <p className="text-xs text-slate-500">
            {decision === "approved" ? "Generating Excel file…" : "Export cancelled."}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3 px-4 py-4">
          {/* Summary */}
          {summaryParts.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {summaryParts.map((part, i) => (
                <span
                  key={i}
                  className="rounded-full border border-green-500/20 bg-green-900/20 px-2.5 py-0.5 text-[11px] font-semibold text-green-200"
                >
                  {part}
                </span>
              ))}
            </div>
          )}

          {/* Question */}
          <p className="text-xs leading-relaxed text-slate-400">{question}</p>

          {/* Info box */}
          <div className="rounded-xl border border-white/8 bg-white/3 px-3 py-2.5">
            <div className="flex items-start gap-2">
              <svg
                className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-green-400/70"
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
                Clones the BnK template with live BA/QC/PM formulas and a dynamic Delivery Plan
                grid.
              </p>
            </div>
          </div>

          {/* Actions */}
          {useDecisionMenu ? (
            <DecisionActions
              allowedDecisions={allowedDecisions}
              disabled={disabled}
              approveLabel="Generate .xlsx"
              onApprove={approve}
              onReject={() => {
                setDecided(true);
                setDecision("rejected");
                onResolve(false);
              }}
              onDecision={onDecision!}
            />
          ) : (
            <div className="flex gap-2.5">
              <button
                onClick={approve}
                disabled={disabled}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-green-700 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-green-900/30 transition-all hover:bg-green-600 active:scale-98 disabled:opacity-50"
              >
                <svg
                  className="h-3.5 w-3.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
                  />
                </svg>
                Generate .xlsx
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
