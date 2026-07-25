import type { TechAlternative, TechRisk, TechStackLayer } from "../hooks/agent-utils";
import { fmtUsd } from "./format";
import Chip from "../ui/Chip";

const LAYER_ORDER = [
  "frontend",
  "backend",
  "database",
  "auth",
  "infra",
  "monitoring",
  "networking",
  "security",
  "cache",
  "queue",
  "cdn",
  "search",
  "storage",
  "ci_cd",
  "analytics",
  "ai_ml",
  "integration",
];

/** The tech-stack layer card grid — ported from TechStackApproval.tsx as a
 * standalone primitive (plan §F.5) since BusinessCaseCard and a future
 * tech-stack summary view both want the same "one layer, its choice, cost,
 * risks and alternatives" block. */
export default function LayerList({ techStack }: { techStack: Record<string, TechStackLayer> }) {
  const layers = [
    ...LAYER_ORDER.filter((l) => l in techStack),
    ...Object.keys(techStack).filter((l) => !LAYER_ORDER.includes(l)),
  ];

  return (
    <div className="grid grid-cols-1 gap-2">
      {layers.map((layer) => {
        const info = techStack[layer];
        if (!info) return null;

        const metaParts: string[] = [];
        if (info.estimated_monthly_cost_usd) metaParts.push(fmtUsd(info.estimated_monthly_cost_usd));
        if (info.capacity_sizing) metaParts.push(info.capacity_sizing);
        if (info.performance_target) metaParts.push(info.performance_target);

        const risks: TechRisk[] = Array.isArray(info.risks) ? info.risks : [];

        return (
          <div key={layer} className="rounded-sm border border-line bg-well px-3 py-2.5">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="label-caps text-2xs font-semibold text-muted">{layer}</span>
                  <span className="text-xs font-semibold text-accent-text">{info.choice}</span>
                  {info.cost_tier && <Chip variant="neutral">{info.cost_tier}</Chip>}
                  {risks.length > 0 && (
                    <span
                      title={risks.map((r) => `${r.risk}${r.mitigation ? ` → ${r.mitigation}` : ""}`).join("\n")}
                    >
                      <Chip variant="warn">⚠ {risks.length}</Chip>
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs leading-relaxed text-secondary">{info.rationale}</p>
                {metaParts.length > 0 && (
                  <p className="mt-1 text-2xs text-muted leading-relaxed">{metaParts.join(" · ")}</p>
                )}
              </div>
            </div>
            {Array.isArray(info.alternatives) && info.alternatives.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {info.alternatives.map((alt, i) => {
                  const name = typeof alt === "string" ? alt : ((alt as TechAlternative)?.name ?? "");
                  const why = typeof alt === "object" ? (alt as TechAlternative)?.why_rejected : undefined;
                  return (
                    <span key={`${name}-${i}`} title={why || undefined}>
                      <Chip variant="neutral">{name}</Chip>
                    </span>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
