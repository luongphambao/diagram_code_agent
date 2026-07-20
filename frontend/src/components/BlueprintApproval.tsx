import { useState } from "react";
import type { DecisionPayload, PendingInterrupt } from "../hooks/useDiagramAgent";
import DecisionActions from "./DecisionActions";

interface BlueprintApprovalProps {
  interrupt: PendingInterrupt;
  onResolve: (approved: boolean, modifications?: string) => void;
  onDecision?: (payload: DecisionPayload) => void;
  disabled?: boolean;
}

const PATTERN_COLORS: Record<string, string> = {
  microservices: "bg-purple-500/15 text-purple-300 border-purple-500/25",
  monolith: "bg-slate-500/15 text-slate-300 border-slate-500/25",
  serverless: "bg-sky-500/15 text-sky-300 border-sky-500/25",
  "event-driven": "bg-amber-500/15 text-amber-300 border-amber-500/25",
  hybrid: "bg-teal-500/15 text-teal-300 border-teal-500/25",
};

const TIER_DOT: Record<string, string> = {
  frontend: "bg-blue-400",
  backend: "bg-green-400",
  data: "bg-indigo-400",
  infra: "bg-pink-400",
  external: "bg-slate-400",
  security: "bg-red-400",
};

type KeyDecision = string | {
  decision?: unknown;
  rationale?: unknown;
  tradeoffs?: unknown;
};

function textValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function tradeoffText(value: unknown): string {
  if (Array.isArray(value)) return value.map(textValue).filter(Boolean).join("; ");
  return textValue(value);
}

function normalizeDecision(decision: KeyDecision): { title: string; rationale: string; tradeoffs: string } {
  if (typeof decision === "string") {
    return { title: decision, rationale: "", tradeoffs: "" };
  }
  if (decision && typeof decision === "object") {
    const title = textValue(decision.decision) || textValue(decision.rationale) || "Decision";
    return {
      title,
      rationale: textValue(decision.rationale),
      tradeoffs: tradeoffText(decision.tradeoffs),
    };
  }
  return { title: String(decision ?? ""), rationale: "", tradeoffs: "" };
}

export default function BlueprintApproval({ interrupt, onResolve, onDecision, disabled = false }: BlueprintApprovalProps) {
  const [mode, setMode] = useState<"idle" | "feedback">("idle");
  const [modifications, setModifications] = useState("");
  const [decided, setDecided] = useState(false);
  const allowedDecisions = interrupt.data.allowed_decisions ?? [];
  // Show the richer HITL v2 menu only when the gate offers more than approve/reject.
  const useDecisionMenu = onDecision != null &&
    allowedDecisions.some((a) => a !== "approve" && a !== "reject");

  const blueprint = interrupt.data.blueprint as typeof interrupt.data.blueprint & {
    pillar_coverage?: Record<string, { addressed_by?: string[]; gaps?: string[] }>;
    nfr_mapping?: Array<{ nfr: string; mechanism?: string }>;
  };
  const pattern = blueprint?.pattern ?? "unknown";
  const patternRationale = blueprint?.pattern_rationale ?? "";
  const keyDecisions = Array.isArray(blueprint?.key_decisions) ? blueprint.key_decisions as KeyDecision[] : [];
  const nodes = Array.isArray(blueprint?.nodes) ? blueprint.nodes : [];
  const clusters = Array.isArray(blueprint?.clusters) ? blueprint.clusters : [];
  const edges = Array.isArray(blueprint?.edges) ? blueprint.edges : [];
  const metadata = [
    blueprint?.audience ? `Audience: ${blueprint.audience}` : null,
    blueprint?.detail_level ? `Detail: ${blueprint.detail_level}` : null,
    blueprint?.layout_intent ? `Layout: ${blueprint.layout_intent}` : null,
    blueprint?.presentation_style ? `Style: ${blueprint.presentation_style}` : null,
    blueprint?.brand ? `Brand: ${blueprint.brand}` : null,
  ].filter((m): m is string => Boolean(m));
  const patternClass = PATTERN_COLORS[pattern] ?? PATTERN_COLORS["hybrid"];

  const labelOf = (id: string) => nodes.find((n) => n.id === id)?.label ?? id;

  // Group nodes by cluster (preserving cluster order; ungrouped → "Other").
  const grouped = clusters.map((c) => ({
    cluster: c,
    nodes: nodes.filter((n) => n.cluster === c.id),
  }));
  const orphans = nodes.filter((n) => !clusters.some((c) => c.id === n.cluster));
  if (orphans.length) grouped.push({ cluster: { id: "_other", label: "Other", tier: "" }, nodes: orphans });

  const approve = () => { setDecided(true); onResolve(true); };
  const requestChanges = () => {
    if (!modifications.trim()) return;
    setDecided(true);
    onResolve(false, modifications.trim());
  };

  return (
    <div className="flex w-full flex-col overflow-hidden rounded-2xl border border-amber-500/20 bg-amber-950/15">
      {/* Header */}
      <div className="flex items-center gap-2.5 border-b border-white/8 bg-white/4 px-4 py-3">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-amber-500/20">
          <svg className="h-3.5 w-3.5 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6" />
          </svg>
        </div>
        <p className="flex-1 text-sm font-semibold text-white">Architecture Blueprint</p>
        <span className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium capitalize ${patternClass}`}>
          {pattern}
        </span>
      </div>

      {decided ? (
        <div className="px-4 py-3">
          <p className="text-xs text-slate-600">
            {mode === "feedback" ? "Feedback sent — redesigning blueprint..." : "Approved — generating the diagram..."}
          </p>
        </div>
      ) : mode === "idle" ? (
        <div className="flex flex-col gap-3.5 px-4 py-3.5">
          {/* Blueprint metadata */}
          {metadata.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {metadata.map((m) => (
                <span key={m} className="rounded-md border border-white/8 bg-black/25 px-2 py-0.5 text-[10px] text-slate-400">
                  {m}
                </span>
              ))}
            </div>
          )}

          {/* Why this pattern */}
          {patternRationale && (
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-amber-400/70">Why this architecture</p>
              <p className="text-[11px] leading-relaxed text-slate-300">{patternRationale}</p>
            </div>
          )}

          {/* Key design decisions */}
          {keyDecisions.length > 0 && (
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-amber-400/70">Key design decisions</p>
              <ul className="flex flex-col gap-1.5">
                {keyDecisions.map((d, i) => {
                  const item = normalizeDecision(d);
                  return (
                    <li key={i} className="flex gap-2 text-[11px] leading-relaxed text-slate-300">
                      <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-amber-400/70" />
                      <span className="min-w-0">
                        <span>{item.title}</span>
                        {item.rationale && item.rationale !== item.title && (
                          <span className="block text-[10px] text-slate-500">{item.rationale}</span>
                        )}
                        {item.tradeoffs && (
                          <span className="block text-[10px] text-amber-300/70">Tradeoffs: {item.tradeoffs}</span>
                        )}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {/* Components by cluster */}
          {grouped.length > 0 && (
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-amber-400/70">
                Components ({nodes.length})
              </p>
              <div className="flex flex-col gap-2">
                {grouped.map(({ cluster, nodes: cNodes }) => (
                  <div key={cluster.id} className="rounded-xl border border-white/8 bg-white/4 px-3 py-2">
                    <div className="mb-1.5 flex items-center gap-1.5">
                      <span className={`h-1.5 w-1.5 rounded-full ${TIER_DOT[cluster.tier ?? ""] ?? "bg-slate-500"}`} />
                      <span className="text-[11px] font-semibold text-slate-200">{cluster.label}</span>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {cNodes.map((n) => (
                        <span
                          key={n.id}
                          title={n.tech ? `${n.label} · ${n.tech}` : n.label}
                          className="rounded-md border border-white/8 bg-black/30 px-2 py-0.5 text-[10px] text-slate-300"
                        >
                          {n.label}
                          {n.tech ? <span className="text-slate-600"> · {n.tech}</span> : null}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Data flows */}
          {edges.length > 0 && (
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-amber-400/70">
                Data flows ({edges.length})
              </p>
              <div className="flex flex-col gap-1">
                {edges.slice(0, 12).map((e, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-[10px] text-slate-400">
                    <span className="text-slate-300">{labelOf(e.from)}</span>
                    <span className="text-amber-400/70">→</span>
                    <span className="text-slate-300">{labelOf(e.to)}</span>
                    {(e.label || e.protocol) && (
                      <span className="text-slate-600">· {e.label || e.protocol}</span>
                    )}
                  </div>
                ))}
                {edges.length > 12 && <p className="text-[10px] text-slate-600">+{edges.length - 12} more flows</p>}
              </div>
            </div>
          )}

          {/* NFR mapping summary */}
          {Array.isArray(blueprint?.nfr_mapping) && blueprint.nfr_mapping.length > 0 && (
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-amber-400/70">
                NFRs mapped: {blueprint.nfr_mapping.length}
              </p>
              <p className="text-[10px] text-slate-500">
                {blueprint.nfr_mapping.map((n) => n.nfr).join(" · ")}
              </p>
            </div>
          )}

          {/* Well-Architected pillar coverage */}
          {blueprint?.pillar_coverage && typeof blueprint.pillar_coverage === "object" && Object.keys(blueprint.pillar_coverage).length > 0 && (
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-amber-400/70">Pillar coverage</p>
              <div className="flex flex-wrap gap-1">
                {Object.entries(blueprint.pillar_coverage).map(([pillar, data]) => {
                  const gaps = Array.isArray(data?.gaps) ? data.gaps : [];
                  const hasGaps = gaps.length > 0;
                  return (
                    <span
                      key={pillar}
                      title={hasGaps ? `Gaps: ${gaps.join(", ")}` : undefined}
                      className={`rounded-md border px-2 py-0.5 text-[10px] capitalize ${hasGaps ? "border-amber-500/30 bg-amber-500/10 text-amber-300" : "border-white/8 bg-white/4 text-slate-400"}`}
                    >
                      {pillar}
                    </span>
                  );
                })}
              </div>
            </div>
          )}

          <p className="text-xs text-slate-500">{interrupt.data.question}</p>

          {useDecisionMenu ? (
            <DecisionActions
              allowedDecisions={allowedDecisions}
              disabled={disabled}
              approveLabel="Looks good! Generate diagram"
              onApprove={approve}
              onReject={(text) => { setMode("feedback"); setDecided(true); onResolve(false, text); }}
              onDecision={(payload) => { setDecided(true); onDecision!(payload); }}
            />
          ) : (
            <div className="flex gap-2.5">
              <button
                onClick={approve}
                disabled={disabled}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-amber-700 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-amber-900/30 transition-all hover:bg-amber-600 active:scale-98 disabled:opacity-50"
              >
                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                Looks good! Generate diagram
              </button>
              <button
                onClick={() => setMode("feedback")}
                disabled={disabled}
                className="flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/4 px-4 py-2.5 text-xs font-semibold text-slate-300 transition-all hover:bg-white/8 disabled:opacity-50"
              >
                Request changes
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-3 px-4 py-3">
          <div className="flex items-center gap-2">
            <button onClick={() => setMode("idle")} className="text-slate-600 hover:text-slate-400">← Back</button>
            <p className="text-xs text-slate-500">What should be changed?</p>
          </div>
          <textarea
            className="w-full resize-none rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-xs leading-relaxed text-slate-200 placeholder:text-slate-700 focus:border-amber-500/40 focus:outline-none"
            rows={3}
            placeholder="e.g. Add a Redis cache and a read replica; split auth into a dedicated security tier; use an event bus between services..."
            value={modifications}
            onChange={(e) => setModifications(e.target.value)}
            disabled={disabled}
            autoFocus
          />
          <button
            onClick={requestChanges}
            disabled={disabled || !modifications.trim()}
            className="rounded-xl bg-amber-700 px-4 py-2.5 text-xs font-semibold text-white transition-all hover:bg-amber-600 disabled:opacity-40"
          >
            Redesign with changes
          </button>
        </div>
      )}
    </div>
  );
}
