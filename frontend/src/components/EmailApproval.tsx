import { useState } from "react";
import type { PendingInterrupt } from "../hooks/useDiagramAgent";

interface EmailApprovalProps {
  interrupt: PendingInterrupt;
  onResolve: (approved: boolean) => void;
  disabled?: boolean;
}

export default function EmailApproval({ interrupt, onResolve, disabled = false }: EmailApprovalProps) {
  const [decided, setDecided] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  const { recipient_email, subject, project_name, recipient_name } = interrupt.data;

  const approve = () => {
    setDecided(true);
    setDecision("approved");
    onResolve(true);
  };

  const reject = () => {
    setDecided(true);
    setDecision("rejected");
    onResolve(false);
  };

  return (
    <div className="flex w-full flex-col overflow-hidden rounded-2xl border border-blue-500/20 bg-blue-950/15">
      <div className="flex items-center gap-2.5 border-b border-white/8 bg-white/4 px-4 py-3">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-500/20">
          <svg className="h-3.5 w-3.5 text-blue-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
        </div>
        <p className="flex-1 text-sm font-semibold text-white">Send Architecture Report</p>
        <span className="rounded-full border border-blue-500/25 bg-blue-500/10 px-2 py-0.5 text-[11px] font-medium text-blue-300">
          via Gmail
        </span>
      </div>

      {decided ? (
        <div className="px-4 py-3">
          <p className="text-xs text-slate-500">
            {decision === "approved" ? "Sending email…" : "Email send cancelled."}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3 px-4 py-4">
          <p className="text-xs leading-relaxed text-slate-400">{interrupt.data.question}</p>

          <div className="rounded-xl border border-white/8 bg-white/4 px-3 py-3 space-y-2">
            {recipient_email && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-blue-300/70">To</p>
                <p className="mt-0.5 text-sm text-slate-100">{recipient_email}</p>
              </div>
            )}
            {subject && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-blue-300/70">Subject</p>
                <p className="mt-0.5 text-xs text-slate-300">{subject}</p>
              </div>
            )}
            {project_name && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-blue-300/70">Project</p>
                <p className="mt-0.5 text-xs text-slate-400">{project_name}</p>
              </div>
            )}
            {recipient_name && recipient_name !== "Team" && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-blue-300/70">Recipient</p>
                <p className="mt-0.5 text-xs text-slate-400">{recipient_name}</p>
              </div>
            )}
          </div>

          <p className="text-[11px] text-slate-500">
            The PDF report will be attached and sent from the connected Gmail account.
          </p>

          <div className="flex gap-2.5">
            <button
              onClick={approve}
              disabled={disabled}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-blue-700 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-blue-900/30 transition-all hover:bg-blue-600 active:scale-98 disabled:opacity-50"
            >
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
              Send Email
            </button>
            <button
              onClick={reject}
              disabled={disabled}
              className="rounded-xl border border-white/10 bg-white/4 px-4 py-2.5 text-xs font-semibold text-slate-300 transition-all hover:bg-white/8 disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
