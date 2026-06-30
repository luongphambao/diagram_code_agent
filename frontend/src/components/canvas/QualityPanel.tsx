import type { ComplianceState, DriftReport, QualitySnapshot } from "../../hooks/useDiagramAgent";

interface QualityPanelProps {
  quality?: QualitySnapshot;
  compliance?: ComplianceState;
  drift?: DriftReport;
}

const GRADE_CLS: Record<string, string> = {
  A: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  B: "border-teal-500/40 bg-teal-500/10 text-teal-300",
  C: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  D: "border-orange-500/40 bg-orange-500/10 text-orange-300",
  F: "border-red-500/40 bg-red-500/10 text-red-300",
};

function Pct({ label, value }: { label: string; value: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[11px]">
        <span className="text-slate-500">{label}</span>
        <span className="font-semibold text-slate-300">{pct}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/8">
        <div className="h-full rounded-full bg-blue-500/70" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">{title}</p>
      {children}
    </div>
  );
}

export default function QualityPanel({ quality, compliance, drift }: QualityPanelProps) {
  if (!quality && !compliance && !drift) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
        <p className="text-sm text-slate-600">No quality snapshot yet</p>
        <p className="text-xs text-slate-700">Run the quality summary, compliance pack, or reality-sync tools to populate governance read-outs.</p>
      </div>
    );
  }

  const grade = (quality?.quality_grade || "?").charAt(0).toUpperCase();
  const dimEntries = Object.entries(quality?.findings_by_dimension || {});
  const sevEntries = Object.entries(quality?.findings_by_severity || {});
  const ds = drift?.summary;

  return (
    <div className="flex-1 space-y-6 overflow-y-auto p-6">
      {/* Quality score */}
      {quality && (
        <div className="space-y-4">
          <div className="flex items-center gap-4">
            <div className={`flex h-16 w-16 flex-col items-center justify-center rounded-2xl border ${GRADE_CLS[grade] || GRADE_CLS.F}`}>
              <span className="text-2xl font-bold leading-none">{grade}</span>
              <span className="mt-0.5 text-[10px] opacity-80">{(quality.quality_score ?? 0).toFixed(0)}/100</span>
            </div>
            <div className="flex flex-1 flex-wrap gap-1.5">
              <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-[11px] text-slate-300">
                {quality.findings_open ?? 0} open findings
              </span>
              <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-[11px] text-slate-300">
                {quality.findings_waived ?? 0} waived
              </span>
              <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-[11px] text-slate-300">
                {quality.findings_resolved ?? 0} resolved
              </span>
              <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-[11px] text-slate-300">
                {quality.total_decisions ?? 0} decisions
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
            <Pct label="Evidence coverage" value={quality.evidence_coverage_pct ?? 0} />
            <Pct label="Assumptions confirmed" value={quality.assumption_confirmation_pct ?? 0} />
            <Pct label="Risks mitigated" value={quality.risk_mitigation_pct ?? 0} />
          </div>

          {(dimEntries.length > 0 || sevEntries.length > 0) && (
            <Section title="Findings">
              <div className="flex flex-wrap gap-1.5">
                {sevEntries.map(([sev, n]) => (
                  <span key={sev} className="rounded border border-white/8 bg-white/5 px-2 py-0.5 text-[11px] text-slate-300">
                    <span className="font-semibold capitalize text-white">{sev}</span> {n}
                  </span>
                ))}
                {dimEntries.map(([dim, n]) => (
                  <span key={dim} className="rounded border border-white/8 bg-white/5 px-2 py-0.5 text-[11px] text-slate-400">
                    {dim.replace(/_/g, " ")}: {n}
                  </span>
                ))}
              </div>
            </Section>
          )}

          {(quality.total_tokens ?? 0) > 0 && (
            <p className="text-[11px] text-slate-600">
              Spend: {(quality.total_tokens ?? 0).toLocaleString()} tokens · {quality.model_calls ?? 0} model calls
            </p>
          )}
        </div>
      )}

      {/* Compliance */}
      {compliance && (
        <Section title={`Compliance · ${compliance.pack}`}>
          {compliance.controls.length > 0 ? (
            <table className="w-full text-[11px]">
              <tbody>
                {compliance.controls.map((c) => (
                  <tr key={c.id} className="border-b border-white/5">
                    <td className="py-1 pr-2 font-mono text-slate-600">{c.standard_ref || c.id}</td>
                    <td className="py-1 pr-2 text-slate-300">{c.name}</td>
                    <td className="py-1 pr-2 text-right">
                      <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                        c.status === "implemented" ? "bg-emerald-500/15 text-emerald-300"
                          : c.status === "waived" ? "bg-slate-500/15 text-slate-400"
                          : "bg-amber-500/15 text-amber-300"
                      }`}>{c.status}</span>
                    </td>
                    <td className="py-1 text-right">
                      <span className={`text-[10px] ${c.grounded ? "text-emerald-400" : "text-red-400/80"}`}>
                        {c.grounded ? "evidence ✓" : "no evidence"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-[11px] text-slate-600">Pack applied — no controls minted yet.</p>
          )}
        </Section>
      )}

      {/* Drift */}
      {drift && ds && (
        <Section title="Reality drift">
          <div className="mb-2 flex flex-wrap gap-1.5">
            <span className="rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] text-emerald-300">{ds.matched ?? 0} matched</span>
            <span className="rounded-full border border-amber-500/25 bg-amber-500/10 px-2.5 py-0.5 text-[11px] text-amber-300">{ds.in_design_not_in_reality ?? 0} design-only</span>
            <span className="rounded-full border border-orange-500/25 bg-orange-500/10 px-2.5 py-0.5 text-[11px] text-orange-300">{ds.in_reality_not_in_design ?? 0} reality-only</span>
          </div>
          {(drift.remediation && drift.remediation.length > 0) && (
            <ul className="space-y-1">
              {drift.remediation.slice(0, 8).map((r, i) => (
                <li key={i} className="flex gap-1.5 text-[11px] leading-relaxed text-slate-400">
                  <span className="text-slate-600">•</span>
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}
    </div>
  );
}
