import { useState } from "react";
import type { PendingInterrupt } from "../hooks/useDiagramAgent";

interface BriefApprovalProps {
  interrupt: PendingInterrupt;
  onResolve: (approved: boolean, modifications?: string) => void;
  disabled?: boolean;
}

export default function BriefApproval({ interrupt, onResolve, disabled = false }: BriefApprovalProps) {
  const [mode, setMode] = useState<"idle" | "feedback">("idle");
  const [modifications, setModifications] = useState("");
  const [decided, setDecided] = useState(false);

  const brief = interrupt.data.brief ?? { objective: "" };
  const objective = brief.objective ?? "";
  const functional = Array.isArray(brief.functional_requirements) ? brief.functional_requirements : [];
  const nonFunctional = Array.isArray(brief.non_functional_requirements) ? brief.non_functional_requirements : [];
  const layout = Array.isArray(brief.layout_constraints) ? brief.layout_constraints : [];
  const assumptions = Array.isArray(brief.assumptions) ? brief.assumptions : [];
  const stakeholders = Array.isArray(brief.stakeholders) ? brief.stakeholders : [];

  const chips = [
    brief.application_type ? `Type: ${brief.application_type}` : null,
    brief.scale_level ? `Scale: ${brief.scale_level}` : null,
    brief.security_level ? `Security: ${brief.security_level}` : null,
    brief.provider_preference ? `Provider: ${brief.provider_preference}` : null,
  ].filter((c): c is string => Boolean(c));

  const approve = () => { setDecided(true); onResolve(true); };
  const requestChanges = () => {
    if (!modifications.trim()) return;
    setDecided(true);
    onResolve(false, modifications.trim());
  };

  const reqList = (title: string, items: string[]) =>
    items.length > 0 ? (
      <div>
        <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-teal-400/70">
          {title} ({items.length})
        </p>
        <ul className="flex flex-col gap-1.5">
          {items.map((r, i) => (
            <li key={i} className="flex gap-2 text-[11px] leading-relaxed text-slate-300">
              <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-teal-400/70" />
              <span>{r}</span>
            </li>
          ))}
        </ul>
      </div>
    ) : null;

  return (
    <div className="flex w-full flex-col overflow-hidden rounded-2xl border border-teal-500/20 bg-teal-950/15">
      {/* Header */}
      <div className="flex items-center gap-2.5 border-b border-white/8 bg-white/4 px-4 py-3">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-teal-500/20">
          <svg className="h-3.5 w-3.5 text-teal-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <p className="flex-1 text-sm font-semibold text-white">Requirements Brief</p>
      </div>

      {decided ? (
        <div className="px-4 py-3">
          <p className="text-xs text-slate-600">
            {mode === "feedback" ? "Feedback sent — revising the brief..." : "Approved — recommending tech stack..."}
          </p>
        </div>
      ) : mode === "idle" ? (
        <div className="flex flex-col gap-3.5 px-4 py-3.5">
          {/* Classification chips */}
          {chips.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {chips.map((c) => (
                <span key={c} className="rounded-md border border-white/8 bg-black/25 px-2 py-0.5 text-[10px] capitalize text-slate-400">
                  {c}
                </span>
              ))}
            </div>
          )}

          {/* Objective */}
          {objective && (
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-teal-400/70">Objective</p>
              <p className="text-[11px] leading-relaxed text-slate-300">{objective}</p>
            </div>
          )}

          {reqList("Functional requirements", functional)}
          {reqList("Non-functional requirements", nonFunctional)}
          {reqList("Layout constraints", layout)}
          {reqList("Assumptions", assumptions)}

          {/* Stakeholders */}
          {stakeholders.length > 0 && (
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-teal-400/70">Stakeholders</p>
              <div className="flex flex-wrap gap-1">
                {stakeholders.map((s, i) => (
                  <span key={i} className="rounded-md border border-white/8 bg-black/30 px-2 py-0.5 text-[10px] text-slate-300">
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          <p className="text-xs text-slate-500">{interrupt.data.question}</p>

          <div className="flex gap-2.5">
            <button
              onClick={approve}
              disabled={disabled}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-teal-700 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-teal-900/30 transition-all hover:bg-teal-600 active:scale-98 disabled:opacity-50"
            >
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
              Approve requirements
            </button>
            <button
              onClick={() => setMode("feedback")}
              disabled={disabled}
              className="flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/4 px-4 py-2.5 text-xs font-semibold text-slate-300 transition-all hover:bg-white/8 disabled:opacity-50"
            >
              Request changes
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3 px-4 py-3">
          <div className="flex items-center gap-2">
            <button onClick={() => setMode("idle")} className="text-slate-600 hover:text-slate-400">← Back</button>
            <p className="text-xs text-slate-500">What should be changed?</p>
          </div>
          <textarea
            className="w-full resize-none rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-xs leading-relaxed text-slate-200 placeholder:text-slate-700 focus:border-teal-500/40 focus:outline-none"
            rows={3}
            placeholder="e.g. Add an offline-sync requirement; the app must integrate with the existing FMS over REST; target 50k MAU..."
            value={modifications}
            onChange={(e) => setModifications(e.target.value)}
            disabled={disabled}
            autoFocus
          />
          <button
            onClick={requestChanges}
            disabled={disabled || !modifications.trim()}
            className="rounded-xl bg-teal-700 px-4 py-2.5 text-xs font-semibold text-white transition-all hover:bg-teal-600 disabled:opacity-40"
          >
            Revise brief with changes
          </button>
        </div>
      )}
    </div>
  );
}
