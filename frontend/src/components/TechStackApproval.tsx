import { useState } from "react";
import type { PendingInterrupt } from "../hooks/useDiagramAgent";

interface TechStackApprovalProps {
  interrupt: PendingInterrupt;
  onResolve: (approved: boolean, modifications?: string) => void;
  disabled?: boolean;
}

const LAYER_ORDER = ["frontend", "backend", "database", "cache", "queue", "auth", "infra", "monitoring", "cdn", "search"];

export default function TechStackApproval({ interrupt, onResolve, disabled = false }: TechStackApprovalProps) {
  const [modifications, setModifications] = useState("");
  const [decided, setDecided] = useState(false);

  const techStack = interrupt.data.tech_stack ?? {};

  // Sort layers in preferred order
  const layers = [
    ...LAYER_ORDER.filter((l) => l in techStack),
    ...Object.keys(techStack).filter((l) => !LAYER_ORDER.includes(l)),
  ];

  const approve = () => {
    setDecided(true);
    onResolve(true, modifications.trim() || undefined);
  };

  const reject = () => {
    setDecided(true);
    onResolve(false);
  };

  return (
    <div className="flex w-full flex-col overflow-hidden rounded-2xl border border-blue-500/20 bg-blue-950/20">
      {/* Header */}
      <div className="flex items-center gap-2.5 border-b border-white/8 bg-white/4 px-4 py-3">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-500/20">
          <svg className="h-3.5 w-3.5 text-blue-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 7.5l3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0021 18V6a2.25 2.25 0 00-2.25-2.25H5.25A2.25 2.25 0 003 6v12a2.25 2.25 0 002.25 2.25z" />
          </svg>
        </div>
        <p className="text-sm font-semibold text-white">Tech Stack Recommendation</p>
      </div>

      {/* Question */}
      <p className="px-4 pt-3 text-xs leading-relaxed text-slate-400">{interrupt.data.question}</p>

      {/* Layer cards */}
      <div className="grid grid-cols-1 gap-2 px-4 py-3">
        {layers.map((layer) => {
          const info = techStack[layer];
          if (!info) return null;
          return (
            <div key={layer} className="rounded-xl border border-white/8 bg-white/4 px-3 py-2.5">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-600">
                      {layer}
                    </span>
                    <span className="text-xs font-semibold text-blue-300">{info.choice}</span>
                  </div>
                  <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{info.rationale}</p>
                </div>
              </div>
              {info.alternatives && info.alternatives.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {info.alternatives.map((alt) => (
                    <span
                      key={alt}
                      className="rounded-full border border-white/8 bg-white/4 px-2 py-0.5 text-[10px] text-slate-600"
                    >
                      {alt}
                    </span>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {decided ? (
        <div className="border-t border-white/8 px-4 py-3">
          <p className="text-xs text-slate-600">Response sent — designing architecture...</p>
        </div>
      ) : (
        <>
          {/* Optional modifications */}
          <div className="px-4 pb-3">
            <label className="mb-1.5 block text-[11px] font-medium text-slate-600">
              Suggest changes (optional)
            </label>
            <textarea
              className="w-full resize-none rounded-xl border border-white/8 bg-black/30 px-3 py-2.5 text-xs leading-relaxed text-slate-200 placeholder:text-slate-700 focus:border-blue-500/40 focus:outline-none"
              rows={2}
              placeholder="e.g. Replace MongoDB with PostgreSQL for the data layer..."
              value={modifications}
              onChange={(e) => setModifications(e.target.value)}
              disabled={disabled}
            />
          </div>

          {/* Actions */}
          <div className="flex gap-2.5 border-t border-white/8 px-4 py-3">
            <button
              onClick={approve}
              disabled={disabled}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-blue-900/30 transition-all hover:bg-blue-500 active:scale-98 disabled:opacity-50"
            >
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
              Approve Stack
            </button>
            <button
              onClick={reject}
              disabled={disabled}
              className="rounded-xl border border-white/10 bg-white/4 px-4 py-2.5 text-xs font-semibold text-slate-400 transition-all hover:bg-white/8 disabled:opacity-50"
            >
              Reject
            </button>
          </div>
        </>
      )}
    </div>
  );
}
