import { useState } from "react";
import type { PendingInterrupt } from "../hooks/useDiagramAgent";

interface DiagramFeedbackProps {
  interrupt: PendingInterrupt;
  onResolve: (satisfied: boolean, feedback?: string) => void;
  disabled?: boolean;
  iteration?: number;
}

export default function DiagramFeedback({
  interrupt,
  onResolve,
  disabled = false,
  iteration = 1,
}: DiagramFeedbackProps) {
  const [feedback, setFeedback] = useState("");
  const [decided, setDecided] = useState(false);
  const [mode, setMode] = useState<"idle" | "feedback">("idle");

  const approve = () => {
    setDecided(true);
    onResolve(true);
  };

  const requestChanges = () => {
    if (!feedback.trim()) return;
    setDecided(true);
    onResolve(false, feedback.trim());
  };

  return (
    <div className="flex w-full flex-col overflow-hidden rounded-2xl border border-emerald-500/20 bg-emerald-950/20">
      {/* Header */}
      <div className="flex items-center gap-2.5 border-b border-white/8 bg-white/4 px-4 py-3">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500/20">
          <svg
            className="h-3.5 w-3.5 text-emerald-400"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14"
            />
            <path strokeLinecap="round" strokeLinejoin="round" d="M14 8h.01" />
            <rect x="2" y="3" width="20" height="18" rx="2" />
          </svg>
        </div>
        <p className="flex-1 text-sm font-semibold text-white">Diagram Ready for Review</p>
        {iteration > 1 && (
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-slate-500">
            Iteration {iteration}
          </span>
        )}
      </div>

      {decided ? (
        <div className="px-4 py-3">
          <p className="text-xs text-slate-600">
            {mode === "feedback"
              ? "Feedback sent — regenerating diagram..."
              : "Approved — finishing up..."}
          </p>
        </div>
      ) : mode === "idle" ? (
        /* Initial choice */
        <div className="flex flex-col gap-3 px-4 py-4">
          <p className="text-xs leading-relaxed text-slate-400">{interrupt.data.question}</p>
          <p className="text-xs text-slate-600">Review the diagram on the right, then:</p>
          <div className="flex gap-2.5">
            <button
              onClick={approve}
              disabled={disabled}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-emerald-700 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-emerald-900/30 transition-all hover:bg-emerald-600 active:scale-98 disabled:opacity-50"
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
              Looks great!
            </button>
            <button
              onClick={() => setMode("feedback")}
              disabled={disabled}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/4 px-4 py-2.5 text-xs font-semibold text-slate-300 transition-all hover:bg-white/8 disabled:opacity-50"
            >
              <svg
                className="h-3.5 w-3.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                />
              </svg>
              Request changes
            </button>
          </div>
        </div>
      ) : (
        /* Feedback input */
        <div className="flex flex-col gap-3 px-4 py-4">
          <div className="flex items-center gap-2">
            <button onClick={() => setMode("idle")} className="text-slate-600 hover:text-slate-400">
              ← Back
            </button>
            <p className="text-xs text-slate-500">What should be changed?</p>
          </div>
          <textarea
            className="w-full resize-none rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-xs leading-relaxed text-slate-200 placeholder:text-slate-700 focus:border-blue-500/40 focus:outline-none"
            rows={3}
            placeholder="e.g. Move Redis inside the backend cluster, add a load balancer in front of the API servers..."
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            disabled={disabled}
            autoFocus
          />
          <div className="flex gap-2">
            <button
              onClick={requestChanges}
              disabled={disabled || !feedback.trim()}
              className="flex-1 rounded-xl bg-blue-600 px-4 py-2.5 text-xs font-semibold text-white transition-all hover:bg-blue-500 disabled:opacity-40"
            >
              Regenerate with changes
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
