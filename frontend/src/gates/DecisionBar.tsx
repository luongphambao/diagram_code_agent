import { useState } from "react";
import type { DecisionAction, DecisionPayload } from "../hooks/agent-utils";
import Button from "../ui/Button";

interface AssumptionItem {
  id: string;
  statement: string;
}

interface DecisionBarProps {
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
 * HITL v2 decision menu — ported from components/DecisionActions.tsx onto
 * the design-system primitives (plan §F: "restyled onto the new tokens; the
 * amber was doing 'this is a decision' duty that the tone stripe now does
 * better"). Behaviour is unchanged: renders the trade-off actions a gate
 * offers (`allowedDecisions`) as a primary Approve button plus secondary
 * actions, each with the small inline form its payload needs.
 */
export default function DecisionBar({
  allowedDecisions,
  assumptions = [],
  disabled = false,
  approveLabel = "Approve",
  onApprove,
  onReject,
  onDecision,
}: DecisionBarProps) {
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
      onDecision({ action, approved: true, statement: text.trim(), owner: owner.trim() || undefined });
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
      <div className="flex flex-col gap-2.5 rounded-sm border border-line bg-well px-3 py-3">
        <div className="flex items-center gap-2">
          <button onClick={reset} className="text-xs text-muted hover:text-secondary">
            ← Back
          </button>
          <p className="text-xs font-medium text-secondary">{LABELS[open]}</p>
        </div>

        {open === "approve_with_assumptions" &&
          (assumptions.length ? (
            <div className="flex flex-col gap-1">
              {assumptions.map((a) => (
                <label key={a.id} className="flex items-start gap-2 text-xs text-secondary">
                  <input
                    type="checkbox"
                    checked={picked.includes(a.id)}
                    onChange={() => togglePick(a.id)}
                    className="mt-0.5"
                    disabled={disabled}
                  />
                  <span>
                    <span className="text-muted">{a.id}</span> · {a.statement}
                  </span>
                </label>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted">No pending assumptions to confirm.</p>
          ))}

        {open === "accept_risk" && (
          <input
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
            disabled={disabled}
            placeholder="Risk owner (optional)"
            className="rounded-sm border border-line bg-app px-2.5 py-1.5 text-xs text-fg placeholder:text-muted focus:border-accent-hi focus:outline-none"
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
            className="w-full resize-none rounded-sm border border-line bg-app px-2.5 py-2 text-xs leading-relaxed text-fg placeholder:text-muted focus:border-accent-hi focus:outline-none"
          />
        )}

        <Button variant="primary" size="sm" onClick={() => submit(open)} disabled={disabled}>
          Submit {LABELS[open].toLowerCase()}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      <Button variant="primary" size="md" onClick={onApprove} disabled={disabled} className="flex-1">
        {approveLabel}
      </Button>
      {secondary.map((a) => (
        <Button key={a} variant="secondary" size="md" onClick={() => setOpen(a)} disabled={disabled}>
          {LABELS[a]}
        </Button>
      ))}
    </div>
  );
}
