import { useState } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import type { Blueprint, DecisionAction, DecisionPayload } from "../../hooks/agent-utils";
import GateFrame from "../GateFrame";
import DecisionBar from "../DecisionBar";
import Chip from "../../ui/Chip";
import Button from "../../ui/Button";
import { colorForKey } from "../ColorScale";
import type { GateCardProps } from "../types";

type KeyDecision = string | { decision?: unknown; rationale?: unknown; tradeoffs?: unknown };

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
  if (typeof decision === "string") return { title: decision, rationale: "", tradeoffs: "" };
  if (decision && typeof decision === "object") {
    const d = decision as { decision?: unknown; rationale?: unknown; tradeoffs?: unknown };
    return {
      title: textValue(d.decision) || textValue(d.rationale) || "Decision",
      rationale: textValue(d.rationale),
      tradeoffs: tradeoffText(d.tradeoffs),
    };
  }
  return { title: String(decision ?? ""), rationale: "", tradeoffs: "" };
}

/** Ported from components/BlueprintApproval.tsx (plan §F). */
export default function BlueprintCard({ args, status, respond }: GateCardProps) {
  const [mode, setMode] = useState<"idle" | "feedback">("idle");
  const [modifications, setModifications] = useState("");
  const [decided, setDecided] = useState(false);

  const allowedDecisions = (args.allowed_decisions as DecisionAction[]) ?? [];
  const useDecisionMenu = allowedDecisions.some((a) => a !== "approve" && a !== "reject");

  const blueprint = (args.blueprint ?? {}) as Blueprint & {
    pillar_coverage?: Record<string, { addressed_by?: string[]; gaps?: string[] }>;
    nfr_mapping?: Array<{ nfr: string; mechanism?: string }>;
  };
  const pattern = blueprint.pattern ?? "unknown";
  const patternRationale = blueprint.pattern_rationale ?? "";
  const keyDecisions = Array.isArray(blueprint.key_decisions) ? (blueprint.key_decisions as KeyDecision[]) : [];
  const nodes = Array.isArray(blueprint.nodes) ? blueprint.nodes : [];
  const clusters = Array.isArray(blueprint.clusters) ? blueprint.clusters : [];
  const edges = Array.isArray(blueprint.edges) ? blueprint.edges : [];
  const metadata = [
    blueprint.audience ? `Audience: ${blueprint.audience}` : null,
    blueprint.detail_level ? `Detail: ${blueprint.detail_level}` : null,
    blueprint.layout_intent ? `Layout: ${blueprint.layout_intent}` : null,
    blueprint.presentation_style ? `Style: ${blueprint.presentation_style}` : null,
    blueprint.brand ? `Brand: ${blueprint.brand}` : null,
  ].filter((m): m is string => Boolean(m));

  const labelOf = (id: string) => nodes.find((n) => n.id === id)?.label ?? id;
  const grouped = clusters.map((c) => ({ cluster: c, nodes: nodes.filter((n) => n.cluster === c.id) }));
  const orphans = nodes.filter((n) => !clusters.some((c) => c.id === n.cluster));
  if (orphans.length) grouped.push({ cluster: { id: "_other", label: "Other", tier: "" }, nodes: orphans });

  function decide(payload: DecisionPayload | Record<string, unknown>) {
    setDecided(true);
    void respond?.(payload);
  }
  const approve = () => decide({ action: "approve", approved: true });
  const requestChanges = () => {
    if (!modifications.trim()) return;
    decide({ action: "reject", approved: false, modifications: modifications.trim() });
  };

  if (decided && status === ToolCallStatus.Executing) {
    return (
      <GateFrame label="Architecture Blueprint" tone="decision" status={status} badge={<Chip variant="neutral">{pattern}</Chip>}>
        <p className="text-xs text-muted">
          {mode === "feedback" ? "Feedback sent — redesigning blueprint…" : "Approved — generating the diagram…"}
        </p>
      </GateFrame>
    );
  }

  return (
    <GateFrame label="Architecture Blueprint" tone="decision" status={status} badge={<Chip variant="neutral">{pattern}</Chip>}>
      {mode === "idle" ? (
        <>
          {metadata.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {metadata.map((m) => (
                <Chip key={m} variant="neutral">
                  {m}
                </Chip>
              ))}
            </div>
          )}

          {patternRationale && (
            <div>
              <p className="label-caps mb-1 text-2xs font-semibold text-warn-text">Why this architecture</p>
              <p className="text-xs leading-relaxed text-secondary">{patternRationale}</p>
            </div>
          )}

          {keyDecisions.length > 0 && (
            <div>
              <p className="label-caps mb-1.5 text-2xs font-semibold text-warn-text">Key design decisions</p>
              <ul className="flex flex-col gap-1.5">
                {keyDecisions.map((d, i) => {
                  const item = normalizeDecision(d);
                  return (
                    <li key={i} className="flex gap-2 text-xs leading-relaxed text-secondary">
                      <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-warn" />
                      <span className="min-w-0">
                        <span>{item.title}</span>
                        {item.rationale && item.rationale !== item.title && (
                          <span className="block text-2xs text-muted">{item.rationale}</span>
                        )}
                        {item.tradeoffs && <span className="block text-2xs text-warn-text">Tradeoffs: {item.tradeoffs}</span>}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {grouped.length > 0 && (
            <div>
              <p className="label-caps mb-1.5 text-2xs font-semibold text-warn-text">Components ({nodes.length})</p>
              <div className="flex flex-col gap-2">
                {grouped.map(({ cluster, nodes: cNodes }) => (
                  <div key={cluster.id} className="rounded-sm border border-line bg-well px-3 py-2">
                    <div className="mb-1.5 flex items-center gap-1.5">
                      <span className={`h-1.5 w-1.5 rounded-full bg-${colorForKey(cluster.tier ?? "") === "neutral" ? "muted" : "accent"}`} />
                      <span className="text-xs font-semibold text-fg">{cluster.label}</span>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {cNodes.map((n) => (
                        <span key={n.id} title={n.tech ? `${n.label} · ${n.tech}` : n.label}>
                          <Chip variant="neutral">
                            {n.label}
                            {n.tech ? <span className="text-muted"> · {n.tech}</span> : null}
                          </Chip>
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {edges.length > 0 && (
            <div>
              <p className="label-caps mb-1.5 text-2xs font-semibold text-warn-text">Data flows ({edges.length})</p>
              <div className="flex flex-col gap-1">
                {edges.slice(0, 12).map((e, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-2xs text-secondary">
                    <span className="text-fg">{labelOf(e.from)}</span>
                    <span className="text-warn-text">→</span>
                    <span className="text-fg">{labelOf(e.to)}</span>
                    {(e.label || e.protocol) && <span className="text-muted">· {e.label || e.protocol}</span>}
                  </div>
                ))}
                {edges.length > 12 && <p className="text-2xs text-muted">+{edges.length - 12} more flows</p>}
              </div>
            </div>
          )}

          {Array.isArray(blueprint.nfr_mapping) && blueprint.nfr_mapping.length > 0 && (
            <div>
              <p className="label-caps mb-1 text-2xs font-semibold text-warn-text">NFRs mapped: {blueprint.nfr_mapping.length}</p>
              <p className="text-2xs text-muted">{blueprint.nfr_mapping.map((n) => n.nfr).join(" · ")}</p>
            </div>
          )}

          {blueprint.pillar_coverage && typeof blueprint.pillar_coverage === "object" && Object.keys(blueprint.pillar_coverage).length > 0 && (
            <div>
              <p className="label-caps mb-1.5 text-2xs font-semibold text-warn-text">Pillar coverage</p>
              <div className="flex flex-wrap gap-1">
                {Object.entries(blueprint.pillar_coverage).map(([pillar, data]) => {
                  const gaps = Array.isArray(data?.gaps) ? data.gaps : [];
                  return (
                    <span key={pillar} title={gaps.length ? `Gaps: ${gaps.join(", ")}` : undefined}>
                      <Chip variant={gaps.length ? "warn" : "neutral"}>{pillar}</Chip>
                    </span>
                  );
                })}
              </div>
            </div>
          )}

          <p className="text-xs text-secondary">{typeof args.question === "string" ? args.question : ""}</p>

          {useDecisionMenu ? (
            <DecisionBar
              allowedDecisions={allowedDecisions}
              approveLabel="Looks good! Generate diagram"
              onApprove={approve}
              onReject={(text) => {
                setMode("feedback");
                decide({ action: "reject", approved: false, modifications: text });
              }}
              onDecision={(payload) => decide(payload)}
            />
          ) : (
            <div className="flex gap-2.5">
              <Button variant="primary" size="md" onClick={approve} className="flex-1">
                Looks good! Generate diagram
              </Button>
              <Button variant="secondary" size="md" onClick={() => setMode("feedback")}>
                Request changes
              </Button>
            </div>
          )}
        </>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <button onClick={() => setMode("idle")} className="text-xs text-muted hover:text-secondary">
              ← Back
            </button>
            <p className="text-xs text-secondary">What should be changed?</p>
          </div>
          <textarea
            className="w-full resize-none rounded-sm border border-line bg-app px-3 py-2.5 text-xs leading-relaxed text-fg placeholder:text-muted focus:border-accent-hi focus:outline-none"
            rows={3}
            placeholder="e.g. Add a Redis cache and a read replica; split auth into a dedicated security tier; use an event bus between services..."
            value={modifications}
            onChange={(e) => setModifications(e.target.value)}
            autoFocus
          />
          <Button variant="primary" size="md" onClick={requestChanges} disabled={!modifications.trim()}>
            Redesign with changes
          </Button>
        </>
      )}
    </GateFrame>
  );
}
