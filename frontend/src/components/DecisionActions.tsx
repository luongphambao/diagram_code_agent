import { useState } from "react";
import type { DecisionAction, DecisionPayload } from "../hooks/useDiagramAgent";

interface AssumptionItem {
  id: string;
  statement: string;
}

interface DecisionActionsProps {
  allowedDecisions: DecisionAction[];
  /** Pending assumptions the user can confirm via approve_with_assumptions. */
  assumptions?: AssumptionItem[];
  disabled?: boolean;
  approveLabel?: string;
  onApprove: () => void;
  onReject: (text: string) => void;
  onDecision: (payload: DecisionPayload) => void;
}

const LABELS: Record<DecisionAction, string> = {
  approve: "Approve",
  reject: "Request changes",
  approve_with_assumptions: "Approve with assumptions",
  accept_risk: "Accept risk",
  request_evidence: "Request evidence",
  request_alternative: "Request alternative",
};

/**
 * HITL v2 decision menu (docx §5.3). Renders the trade-off actions a gate offers
 * (`allowed_decisions`) as a primary Approve button plus secondary actions, each
 * with the small inline form its payload needs. Approve/reject reuse the host
 * card's existing handlers; the richer actions post a structured DecisionPayload.
 */
export default function DecisionActions({
  allowedDecisions,
  assumptions = [],
  disabled = false,
  approveLabel = "Approve",
  onApprove,
  onReject,
  onDecision,
}: DecisionActionsProps) {
  const [open, setOpen] = useState<DecisionAction | null>(null);
  const [text, setText] = useState("");
  const [owner, setOwner] = useState("");
  const [picked, setPicked] = useState<string[]>([]);

  const secondary = allowedDecisions.filter((a) => a !== "approve");
  const reset = () => {
    setOpen(null);
    setText("");
    setOwner("");
    setPicked([]);
  };

  const submit = (action: DecisionAction) => {
    if (action === "reject") {
      if (!text.trim()) return;
      onReject(text.trim());
      reset();
      return;
    }
    if (action === "approve_with_assumptions") {
      if (!picked.length) return;
      onDecision({
        action,
        approved: true,
        assumption_ids: picked,
        comment: text.trim() || undefined,
      });
      reset();
      return;
    }
    if (action === "accept_risk") {
      if (!text.trim()) return;
      onDecision({
        action,
        approved: true,
        statement: text.trim(),
        owner: owner.trim() || undefined,
      });
      reset();
      return;
    }
    if (action === "request_evidence") {
      if (!text.trim()) return;
      onDecision({ action, claim: text.trim() });
      reset();
      return;
    }
    if (action === "request_alternative") {
      onDecision({ action, option_comparison: text.trim() || undefined });
      reset();
      return;
    }
  };

  const togglePick = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  if (open) {
    return (
      <div className="flex flex-col gap-2.5 rounded-xl border border-white/10 bg-black/20 px-3 py-3">
        <div className="flex items-center gap-2">
          <button onClick={reset} className="text-slate-600 hover:text-slate-400">
            ← Back
          </button>
          <p className="text-xs font-medium text-slate-400">{LABELS[open]}</p>
        </div>

        {open === "approve_with_assumptions" &&
          (assumptions.length ? (
            <div className="flex flex-col gap-1">
              {assumptions.map((a) => (
                <label key={a.id} className="flex items-start gap-2 text-[11px] text-slate-300">
                  <input
                    type="checkbox"
                    checked={picked.includes(a.id)}
                    onChange={() => togglePick(a.id)}
                    className="mt-0.5"
                    disabled={disabled}
                  />
                  <span>
                    <span className="text-slate-500">{a.id}</span> · {a.statement}
                  </span>
                </label>
              ))}
            </div>
          ) : (
            <p className="text-[11px] text-slate-500">No pending assumptions to confirm.</p>
          ))}

        {open === "accept_risk" && (
          <input
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
            disabled={disabled}
            placeholder="Risk owner (optional)"
            className="rounded-lg border border-white/10 bg-black/30 px-2.5 py-1.5 text-[11px] text-slate-200 placeholder:text-slate-700 focus:border-amber-500/40 focus:outline-none"
          />
        )}

        {open !== "approve_with_assumptions" && (
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={2}
            disabled={disabled}
            autoFocus
            placeholder={
              open === "accept_risk"
                ? "Describe the risk you are accepting…"
                : open === "request_evidence"
                  ? "Which claim needs a source?"
                  : open === "request_alternative"
                    ? "What alternative / constraint to compare? (optional)"
                    : "Describe the changes you want…"
            }
            className="w-full resize-none rounded-lg border border-white/10 bg-black/30 px-2.5 py-2 text-[11px] leading-relaxed text-slate-200 placeholder:text-slate-700 focus:border-amber-500/40 focus:outline-none"
          />
        )}

        <button
          onClick={() => submit(open)}
          disabled={disabled}
          className="rounded-lg bg-amber-700 px-3 py-2 text-[11px] font-semibold text-white transition-all hover:bg-amber-600 disabled:opacity-40"
        >
          Submit {LABELS[open].toLowerCase()}
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      <button
        onClick={onApprove}
        disabled={disabled}
        className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-amber-700 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-amber-900/30 transition-all hover:bg-amber-600 active:scale-98 disabled:opacity-50"
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
        {approveLabel}
      </button>
      {secondary.map((a) => (
        <button
          key={a}
          onClick={() => setOpen(a)}
          disabled={disabled}
          className="flex items-center justify-center rounded-xl border border-white/10 bg-white/4 px-3 py-2.5 text-xs font-semibold text-slate-300 transition-all hover:bg-white/8 disabled:opacity-50"
        >
          {LABELS[a]}
        </button>
      ))}
    </div>
  );
}
