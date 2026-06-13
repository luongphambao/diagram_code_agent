import { useState } from "react";
import type { Delegation, LogEntry } from "../hooks/useDiagramAgent";

// ── Subagent metadata ─────────────────────────────────────────────────────────

interface SubagentMeta {
  icon: string;
  label: string;
  color: "blue" | "violet" | "amber" | "emerald" | "rose" | "slate";
}

const SUBAGENT_META: Record<string, SubagentMeta> = {
  drawer: { icon: "✏️", label: "DRAWER", color: "blue" },
  critic: { icon: "🔍", label: "CRITIC", color: "violet" },
};

function metaFor(name: string): SubagentMeta {
  return (
    SUBAGENT_META[name.toLowerCase()] ?? {
      icon: "🤖",
      label: name.toUpperCase(),
      color: "slate",
    }
  );
}

// ── Color tokens ──────────────────────────────────────────────────────────────

type ColorKey = SubagentMeta["color"];

const COLORS: Record<
  ColorKey,
  { badge: string; numBg: string; numText: string; card: string; step: string }
> = {
  blue: {
    badge: "border-blue-500/30 bg-blue-500/10 text-blue-300",
    numBg: "bg-blue-500/15",
    numText: "text-blue-400",
    card: "border-blue-500/15 bg-blue-500/4",
    step: "text-blue-400/80",
  },
  violet: {
    badge: "border-violet-500/30 bg-violet-500/10 text-violet-300",
    numBg: "bg-violet-500/15",
    numText: "text-violet-400",
    card: "border-violet-500/15 bg-violet-500/4",
    step: "text-violet-400/80",
  },
  amber: {
    badge: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    numBg: "bg-amber-500/15",
    numText: "text-amber-400",
    card: "border-amber-500/15 bg-amber-500/4",
    step: "text-amber-400/80",
  },
  emerald: {
    badge: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    numBg: "bg-emerald-500/15",
    numText: "text-emerald-400",
    card: "border-emerald-500/15 bg-emerald-500/4",
    step: "text-emerald-400/80",
  },
  rose: {
    badge: "border-rose-500/30 bg-rose-500/10 text-rose-300",
    numBg: "bg-rose-500/15",
    numText: "text-rose-400",
    card: "border-rose-500/15 bg-rose-500/4",
    step: "text-rose-400/80",
  },
  slate: {
    badge: "border-slate-500/30 bg-slate-500/10 text-slate-300",
    numBg: "bg-slate-500/15",
    numText: "text-slate-400",
    card: "border-slate-500/15 bg-slate-500/4",
    step: "text-slate-400/80",
  },
};

// ── Indicator roles (always visible chips at top) ─────────────────────────────

const INDICATOR_ROLES: ReadonlyArray<{ key: string }> = [
  { key: "drawer" },
  { key: "critic" },
];

// ── Tool chip (compact mono pill) ─────────────────────────────────────────────

function ToolChip({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-white/4 text-slate-500 border border-white/6">
      {name}
    </span>
  );
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: Delegation["status"] }) {
  if (status === "completed") {
    return (
      <span className="flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-emerald-400">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        DONE
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="flex items-center gap-1.5 rounded-full border border-red-500/30 bg-red-500/10 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-red-400">
        <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
        ERROR
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-amber-400">
      <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
      RUNNING
    </span>
  );
}

// ── Delegation card ───────────────────────────────────────────────────────────

interface DelegationCardProps {
  d: Delegation;
  index: number;
  toolLogs: LogEntry[];
}

const RESULT_PREVIEW = 280;
const MAX_TOOL_CHIPS = 10;
const MAX_TOOL_DETAILS = 8;

function DelegationCard({ d, index, toolLogs }: DelegationCardProps) {
  const [expanded, setExpanded] = useState(false);
  const m = metaFor(d.subagent);
  const c = COLORS[m.color];
  const hasResult = !!d.result;
  const resultLong = hasResult && (d.result?.length ?? 0) > RESULT_PREVIEW;

  // Deduplicate consecutive identical tool names for readability
  const toolNames = toolLogs.map((l) => l.tool ?? "tool");
  const dedupedTools: string[] = toolNames.reduce<string[]>((acc, t) => {
    if (acc.length === 0 || acc[acc.length - 1] !== t) acc.push(t);
    return acc;
  }, []);
  const visibleTools = dedupedTools.slice(0, MAX_TOOL_CHIPS);
  const hiddenCount = dedupedTools.length - visibleTools.length;
  const detailLogs = toolLogs
    .filter((l) => (l.type === "tool_start" || l.type === "tool_end") && l.tool && (l.input || l.output || l.error))
    .slice(-MAX_TOOL_DETAILS);

  return (
    <div className={`overflow-hidden rounded-xl border ${c.card}`}>
      <div className="flex items-start gap-3 px-4 py-3.5">
        {/* Number badge */}
        <div
          className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg ${c.numBg}`}
        >
          <span className={`text-[12px] font-bold font-mono ${c.numText}`}>
            #{index + 1}
          </span>
        </div>

        {/* Main content */}
        <div className="min-w-0 flex-1 space-y-2">
          {/* Type badge */}
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold tracking-wide ${c.badge}`}
          >
            <span>{m.icon}</span>
            <span>{m.label}</span>
          </span>

          {/* Task description */}
          <p className="text-[12px] leading-relaxed text-slate-400">
            {d.description || "Working…"}
          </p>

          {/* Live tool (while running) */}
          {d.status === "running" && (
            <div className={`flex items-center gap-1.5 text-[11px] ${c.step}`}>
              <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse" />
              {d.current_tool ? (
                <>
                  <span className="font-mono">{d.current_tool}</span>
                  {d.current_label && (
                    <span className="text-slate-600">— {d.current_label}</span>
                  )}
                  {d.current_detail && (
                    <span className="truncate text-slate-500">: {d.current_detail}</span>
                  )}
                </>
              ) : d.current_label ? (
                d.current_label + "…"
              ) : (
                "Working…"
              )}
            </div>
          )}

          {/* Tool history chips */}
          {visibleTools.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {visibleTools.map((t, i) => (
                <ToolChip key={i} name={t} />
              ))}
              {hiddenCount > 0 && (
                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] text-slate-700">
                  +{hiddenCount} more
                </span>
              )}
            </div>
          )}

          {detailLogs.length > 0 && (
            <div className="space-y-1 rounded-lg border border-white/6 bg-black/10 p-2">
              {detailLogs.map((l, i) => (
                <div key={`${l.tool}-${i}`} className="flex gap-2 text-[10.5px] leading-snug">
                  <span className={l.error ? "text-red-500" : l.type === "tool_end" ? "text-emerald-500" : "text-amber-500"}>
                    {l.error ? "error" : l.type === "tool_end" ? "done" : "run"}
                  </span>
                  <span className="shrink-0 font-mono text-slate-600">{l.tool}</span>
                  {l.elapsed_s !== undefined && (
                    <span className="shrink-0 text-slate-700">{l.elapsed_s}s</span>
                  )}
                  <span className="min-w-0 truncate text-slate-400">{l.error || l.output || l.input}</span>
                </div>
              ))}
            </div>
          )}

          {/* Result box */}
          {hasResult && (
            <div className="pt-0.5">
              <div className="rounded-lg border border-white/8 bg-white/4 p-2.5">
                <p className="text-[11.5px] leading-relaxed text-slate-500 whitespace-pre-wrap">
                  {expanded || !resultLong
                    ? d.result
                    : d.result!.slice(0, RESULT_PREVIEW) + "…"}
                </p>
              </div>
              {resultLong && (
                <button
                  type="button"
                  onClick={() => setExpanded((v) => !v)}
                  className="mt-1 text-[11px] text-slate-700 hover:text-slate-500 transition-colors"
                >
                  {expanded ? "Show less ▲" : "Show more ▼"}
                </button>
              )}
            </div>
          )}
        </div>

        {/* Status badge — top-right */}
        <div className="flex-shrink-0 pt-0.5">
          <StatusBadge status={d.status} />
        </div>
      </div>
    </div>
  );
}

// ── Orchestrator section ──────────────────────────────────────────────────────

interface OrchestratorSectionProps {
  isRunning: boolean;
  activity: string | null;
  mainLogs: LogEntry[];
}

const MAX_ORCHESTRATOR_CHIPS = 6;

function OrchestratorSection({ isRunning, activity, mainLogs }: OrchestratorSectionProps) {
  // Show recent main-agent tool calls (not subagent ones), newest last
  const recentTools = mainLogs
    .filter((l) => l.type === "tool_start" && l.tool)
    .slice(-MAX_ORCHESTRATOR_CHIPS);

  return (
    <div className="px-5 py-4 border-b border-white/8 bg-[#0d1118]">
      {/* Header */}
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2.5">
          <span className="text-[13px] font-semibold text-slate-200">
            🤖 Orchestrator
          </span>
          {isRunning ? (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border border-blue-500/30 bg-blue-500/10 text-blue-300 text-[10px] font-semibold uppercase tracking-[0.1em]">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
              Active
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 text-[10px] font-semibold uppercase tracking-[0.1em]">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              Done
            </span>
          )}
        </div>
      </div>

      {/* Live activity label */}
      {activity && isRunning && (
        <div className="flex items-center gap-1.5 text-[11px] text-slate-400 mb-2">
          <span className="h-1 w-1 rounded-full bg-blue-400 animate-pulse flex-shrink-0" />
          <span className="truncate">{activity}</span>
        </div>
      )}

      {/* Main agent tool chips */}
      {recentTools.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {recentTools.map((l, i) => (
            <ToolChip key={i} name={l.tool!} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Panel ─────────────────────────────────────────────────────────────────────

interface SubagentPanelProps {
  delegations: Delegation[];
  activeSubagent: string | null;
  isRunning: boolean;
  logs?: LogEntry[];
  activity?: string | null;
}

export default function SubagentPanel({
  delegations,
  activeSubagent,
  isRunning,
  logs = [],
  activity = null,
}: SubagentPanelProps) {
  const safeDelegations = Array.isArray(delegations) ? delegations : [];

  if (!safeDelegations.length && !activeSubagent && !isRunning) return null;

  const calledKeys = new Set(safeDelegations.map((d) => d.subagent.toLowerCase()));

  // Split logs: main orchestrator vs per-subagent
  const mainLogs = logs.filter((l) => !l.subagent);
  const logsBySubagent = (subagentKey: string) =>
    logs.filter(
      (l) => l.subagent?.toLowerCase() === subagentKey.toLowerCase()
    );

  return (
    <div className="w-full bg-[#0c1015] border border-white/8 rounded-2xl overflow-hidden">

      {/* ── Orchestrator section ────────────────────────────────────────────── */}
      <OrchestratorSection
        isRunning={isRunning}
        activity={activity}
        mainLogs={mainLogs}
      />

      {/* ── Indicator chips row ─────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-5 py-2.5 border-b border-white/8 bg-[#0c1015]">
        <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-700 mr-1">
          Subagents
        </span>
        {INDICATOR_ROLES.map(({ key }) => {
          const m = metaFor(key);
          const c = COLORS[m.color];
          const fired = calledKeys.has(key);
          const isActive =
            activeSubagent?.toLowerCase() === key && isRunning;
          return (
            <span
              key={key}
              className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-[0.1em] border transition-opacity ${c.badge} ${
                fired ? "opacity-100" : "opacity-35"
              }`}
            >
              {isActive && (
                <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
              )}
              <span>{m.icon}</span>
              <span>{m.label}</span>
            </span>
          );
        })}
      </div>

      {/* ── Delegation list ─────────────────────────────────────────────────── */}
      <div className="p-4 space-y-2">
        {safeDelegations.length === 0 ? (
          <p className="text-sm text-slate-700 italic py-2 px-1">
            Waiting for delegation…
          </p>
        ) : (
          safeDelegations.map((d, i) => (
            <DelegationCard
              key={d.id || i}
              d={d}
              index={i}
              toolLogs={logsBySubagent(d.subagent)}
            />
          ))
        )}
      </div>
    </div>
  );
}
