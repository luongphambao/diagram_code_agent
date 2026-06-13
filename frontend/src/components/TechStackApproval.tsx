import { useState } from "react";
import type { PendingInterrupt, TechAlternative, CostRange, ScalingPhase, TechRisk } from "../hooks/useDiagramAgent";

interface TechStackApprovalProps {
  interrupt: PendingInterrupt;
  onResolve: (approved: boolean, modifications?: string) => void;
  disabled?: boolean;
}

const LAYER_ORDER = [
  "frontend", "backend", "database", "auth", "infra", "monitoring",
  "networking", "security", "cache", "queue", "cdn", "search",
  "storage", "ci_cd", "analytics", "ai_ml", "integration",
];

function fmtUsd(r?: CostRange | null): string {
  if (!r) return "";
  const fmt = (n: number) => n >= 1000 ? `$${(n / 1000).toFixed(n % 1000 === 0 ? 0 : 1)}k` : `$${n}`;
  return `${fmt(r.min_usd)}–${fmt(r.max_usd)}/mo`;
}

export default function TechStackApproval({ interrupt, onResolve, disabled = false }: TechStackApprovalProps) {
  const [modifications, setModifications] = useState("");
  const [decided, setDecided] = useState(false);

  const techStack = interrupt.data.tech_stack ?? {};
  const assumptions = interrupt.data.assumptions;
  const scalingRoadmap = Array.isArray(interrupt.data.scaling_roadmap) ? interrupt.data.scaling_roadmap : [];
  const totalCost = interrupt.data.estimated_total_monthly_cost_usd;

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

  // Build assumption chips
  const assumptionChips: string[] = [];
  if (assumptions) {
    if (assumptions.project_phase) assumptionChips.push(assumptions.project_phase.toUpperCase());
    if (assumptions.monthly_budget_range_usd) assumptionChips.push(fmtUsd(assumptions.monthly_budget_range_usd) + " budget");
    if (assumptions.users?.mau) assumptionChips.push(`${(assumptions.users.mau / 1000).toFixed(0)}k MAU`);
    if (assumptions.users?.peak_concurrent) assumptionChips.push(`~${assumptions.users.peak_concurrent.toLocaleString()} concurrent`);
    if (assumptions.users?.peak_rps) assumptionChips.push(`~${assumptions.users.peak_rps} RPS`);
    if (assumptions.availability_target) assumptionChips.push(assumptions.availability_target);
    if (assumptions.latency_target_p99_ms) assumptionChips.push(`p99 ≤${assumptions.latency_target_p99_ms}ms`);
    if (assumptions.team) {
      const t = assumptions.team;
      const parts = [t.size ? `Team ${t.size}` : null, t.skill_level || null].filter(Boolean);
      if (parts.length) assumptionChips.push(parts.join(" "));
    }
    if (assumptions.primary_region) assumptionChips.push(assumptions.primary_region);
    if (Array.isArray(assumptions.compliance) && assumptions.compliance.length) assumptionChips.push(...assumptions.compliance);
  }

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

      {/* Assumptions block */}
      {assumptions && (
        <div className="mx-4 mt-3 rounded-xl border border-white/8 bg-white/3 px-3 py-2.5">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-slate-500">Design Assumptions</p>
          {assumptionChips.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {assumptionChips.map((chip, i) => (
                <span key={i} className="rounded-full border border-blue-500/20 bg-blue-900/20 px-2 py-0.5 text-[10px] text-blue-300">
                  {chip}
                </span>
              ))}
            </div>
          )}
          {Array.isArray(assumptions.confirm_with_customer) && assumptions.confirm_with_customer.length > 0 && (
            <div className="mt-2.5">
              <p className="mb-1 text-[10px] font-semibold text-amber-400/80">Confirm with customer</p>
              <ul className="space-y-0.5">
                {assumptions.confirm_with_customer.map((item, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-[10px] leading-relaxed text-amber-300/70">
                    <span className="mt-0.5 shrink-0">•</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Layer cards */}
      <div className="grid grid-cols-1 gap-2 px-4 py-3">
        {layers.map((layer) => {
          const info = techStack[layer];
          if (!info) return null;

          // Build per-layer meta line segments
          const metaParts: string[] = [];
          if (info.estimated_monthly_cost_usd) metaParts.push(fmtUsd(info.estimated_monthly_cost_usd));
          if (info.capacity_sizing) metaParts.push(info.capacity_sizing);
          if (info.performance_target) metaParts.push(info.performance_target);

          const risks: TechRisk[] = Array.isArray(info.risks) ? info.risks : [];

          return (
            <div key={layer} className="rounded-xl border border-white/8 bg-white/4 px-3 py-2.5">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-600">
                      {layer}
                    </span>
                    <span className="text-xs font-semibold text-blue-300">{info.choice}</span>
                    {info.cost_tier && (
                      <span className="rounded border border-white/10 bg-white/6 px-1.5 py-0.5 text-[9px] font-bold text-slate-500">
                        {info.cost_tier}
                      </span>
                    )}
                    {risks.length > 0 && (
                      <span
                        className="rounded border border-amber-500/20 bg-amber-900/10 px-1.5 py-0.5 text-[9px] text-amber-400 cursor-help"
                        title={risks.map(r => `${r.risk}${r.mitigation ? ` → ${r.mitigation}` : ""}`).join("\n")}
                      >
                        ⚠ {risks.length}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{info.rationale}</p>
                  {metaParts.length > 0 && (
                    <p className="mt-1 text-[10px] text-slate-600 leading-relaxed">
                      {metaParts.join(" · ")}
                    </p>
                  )}
                </div>
              </div>
              {Array.isArray(info.alternatives) && info.alternatives.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {info.alternatives.map((alt, i) => {
                    const name = typeof alt === "string" ? alt : (alt as TechAlternative)?.name ?? "";
                    const why = typeof alt === "object" ? (alt as TechAlternative)?.why_rejected : undefined;
                    return (
                      <span
                        key={`${name}-${i}`}
                        title={why || undefined}
                        className="rounded-full border border-white/8 bg-white/4 px-2 py-0.5 text-[10px] text-slate-600"
                      >
                        {name}
                      </span>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Footer: total cost + scaling roadmap */}
      {(totalCost || scalingRoadmap.length > 0) && (
        <div className="mx-4 mb-3 rounded-xl border border-white/8 bg-white/3 px-3 py-2.5">
          {totalCost && (
            <p className="text-[11px] font-semibold text-slate-300">
              Estimated total:{" "}
              <span className="text-blue-300">{fmtUsd(totalCost)}</span>
              <span className="ml-1 text-[10px] font-normal text-slate-600">(assumption-based, infra only)</span>
            </p>
          )}
          {scalingRoadmap.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-[10px] font-semibold uppercase tracking-widest text-slate-500 hover:text-slate-400">
                Scaling roadmap
              </summary>
              <div className="mt-2 space-y-2">
                {scalingRoadmap.map((phase: ScalingPhase, i: number) => (
                  <div key={i} className="text-[10px] leading-relaxed">
                    <span className="font-semibold text-slate-300">{phase.phase}</span>
                    {phase.trigger && (
                      <span className="ml-2 text-slate-600">when: {phase.trigger}</span>
                    )}
                    {phase.est_monthly_cost_usd && (
                      <span className="ml-2 text-slate-600">{fmtUsd(phase.est_monthly_cost_usd)}</span>
                    )}
                    {Array.isArray(phase.changes) && phase.changes.length > 0 && (
                      <p className="mt-0.5 text-slate-600">{phase.changes.join(", ")}</p>
                    )}
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}

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
