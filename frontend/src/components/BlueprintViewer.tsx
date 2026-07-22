import type { Blueprint } from "../hooks/useDiagramAgent";

interface BlueprintViewerProps {
  blueprint: Blueprint;
  blueprintForDiagram?: string;
  onGenerateDiagram?: (description: string) => void;
}

const PATTERN_COLORS: Record<string, string> = {
  microservices: "bg-purple-500/15 text-purple-300 border-purple-500/25",
  monolith: "bg-slate-500/15 text-slate-300 border-slate-500/25",
  serverless: "bg-sky-500/15 text-sky-300 border-sky-500/25",
  "event-driven": "bg-amber-500/15 text-amber-300 border-amber-500/25",
  hybrid: "bg-teal-500/15 text-teal-300 border-teal-500/25",
};

const TIER_COLORS: Record<string, string> = {
  frontend: "text-sky-400",
  backend: "text-blue-400",
  data: "text-violet-400",
  infra: "text-slate-400",
  external: "text-slate-600",
  security: "text-red-400",
};

export default function BlueprintViewer({
  blueprint,
  blueprintForDiagram,
  onGenerateDiagram,
}: BlueprintViewerProps) {
  const { pattern, pattern_rationale, audience, detail_level, layout_intent } = blueprint;
  const nodes = Array.isArray(blueprint.nodes) ? blueprint.nodes : [];
  const clusters = Array.isArray(blueprint.clusters) ? blueprint.clusters : [];
  const edges = Array.isArray(blueprint.edges) ? blueprint.edges : [];
  const patternClass = PATTERN_COLORS[pattern] ?? PATTERN_COLORS["hybrid"];
  const metadata = [
    audience ? `Audience: ${audience}` : null,
    detail_level ? `Detail: ${detail_level}` : null,
    layout_intent ? `Layout: ${layout_intent}` : null,
  ].filter((m): m is string => Boolean(m));

  // Group nodes by cluster
  const clusterMap: Record<string, typeof nodes> = {};
  for (const node of nodes) {
    const cid = node.cluster ?? "ungrouped";
    (clusterMap[cid] = clusterMap[cid] ?? []).push(node);
  }
  const clusterLabels: Record<string, string> = Object.fromEntries(
    clusters.map((c) => [c.id, c.label]),
  );
  const clusterTiers: Record<string, string> = Object.fromEntries(
    clusters.map((c) => [c.id, c.tier ?? "backend"]),
  );

  const handleGenerate = () => {
    if (onGenerateDiagram && blueprintForDiagram) {
      onGenerateDiagram(blueprintForDiagram);
    }
  };

  return (
    <div className="flex flex-col gap-4 p-5">
      {/* Pattern badge + rationale */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <span
            className={`rounded-full border px-3 py-1 text-xs font-semibold capitalize ${patternClass}`}
          >
            {pattern}
          </span>
          <span className="text-[11px] text-slate-600">architecture</span>
        </div>
        {pattern_rationale && (
          <p className="text-xs leading-relaxed text-slate-400">{pattern_rationale}</p>
        )}
        {metadata.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {metadata.map((m) => (
              <span
                key={m}
                className="rounded-md border border-white/8 bg-white/4 px-2 py-0.5 text-[10px] text-slate-500"
              >
                {m}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Component clusters */}
      <div className="flex flex-col gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-700">
          Components
        </p>
        {Object.entries(clusterMap).map(([cid, cnodes]) => {
          const label = clusterLabels[cid] ?? cid;
          const tier = clusterTiers[cid] ?? "backend";
          const tierColor = TIER_COLORS[tier] ?? "text-slate-400";
          return (
            <div key={cid} className="rounded-xl border border-white/8 bg-white/4 px-3 py-2.5">
              <p
                className={`mb-2 text-[10px] font-semibold uppercase tracking-widest ${tierColor}`}
              >
                {label}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {cnodes.map((node) => (
                  <div
                    key={node.id}
                    className="flex flex-col rounded-lg border border-white/8 bg-black/20 px-2.5 py-1.5"
                  >
                    <span className="text-[11px] font-medium text-slate-300">{node.label}</span>
                    {node.tech && <span className="text-[10px] text-slate-600">{node.tech}</span>}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-2">
        {[
          { label: "Nodes", value: nodes.length },
          { label: "Clusters", value: clusters.length },
          { label: "Flows", value: edges.length },
        ].map(({ label, value }) => (
          <div
            key={label}
            className="rounded-xl border border-white/8 bg-white/4 px-3 py-2 text-center"
          >
            <p className="text-base font-bold text-amber-300">{value}</p>
            <p className="text-[10px] text-slate-600">{label}</p>
          </div>
        ))}
      </div>

      {/* Generate Diagram button */}
      {blueprintForDiagram && onGenerateDiagram && (
        <button
          onClick={handleGenerate}
          className="flex items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-xs font-semibold text-white shadow-md shadow-blue-900/30 transition-all hover:bg-blue-500 active:scale-98"
        >
          <svg
            className="h-4 w-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <rect x="3" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="3" width="7" height="7" rx="1" />
            <rect x="3" y="14" width="7" height="7" rx="1" />
            <path d="M17.5 14v7M14 17.5h7" strokeLinecap="round" />
            <path d="M10 6.5h4M6.5 10v4" strokeLinecap="round" />
          </svg>
          Generate Diagram from Blueprint
        </button>
      )}
    </div>
  );
}
