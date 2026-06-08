import { useState } from "react";
import type { Delegation } from "../hooks/useDiagramAgent";

// ── Subagent metadata ─────────────────────────────────────────────────────────

interface SubagentMeta {
  icon: string;
  label: string;
  /** Tailwind color key used by colorScheme() */
  color: "blue" | "violet" | "amber" | "emerald" | "rose" | "slate";
}

const SUBAGENT_META: Record<string, SubagentMeta> = {
  drawer: { icon: "✏️", label: "DRAWER",  color: "blue"   },
  critic: { icon: "🔍", label: "CRITIC",  color: "violet" },
};

function metaFor(name: string): SubagentMeta {
  return SUBAGENT_META[name.toLowerCase()] ?? {
    icon: "🤖", label: name.toUpperCase(), color: "slate",
  };
}

// ── Color tokens ──────────────────────────────────────────────────────────────

type ColorKey = SubagentMeta["color"];

const COLORS: Record<ColorKey, {
  badge: string;
  numBg: string;
  numText: string;
  card: string;
  step: string;
}> = {
  blue: {
    badge:   "border-blue-500/30   bg-blue-500/10   text-blue-300",
    numBg:   "bg-blue-500/15",
    numText: "text-blue-400",
    card:    "border-blue-500/15   bg-blue-500/4",
    step:    "text-blue-400/80",
  },
  violet: {
    badge:   "border-violet-500/30 bg-violet-500/10 text-violet-300",
    numBg:   "bg-violet-500/15",
    numText: "text-violet-400",
    card:    "border-violet-500/15 bg-violet-500/4",
    step:    "text-violet-400/80",
  },
  amber: {
    badge:   "border-amber-500/30  bg-amber-500/10  text-amber-300",
    numBg:   "bg-amber-500/15",
    numText: "text-amber-400",
    card:    "border-amber-500/15  bg-amber-500/4",
    step:    "text-amber-400/80",
  },
  emerald: {
    badge:   "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    numBg:   "bg-emerald-500/15",
    numText: "text-emerald-400",
    card:    "border-emerald-500/15 bg-emerald-500/4",
    step:    "text-emerald-400/80",
  },
  rose: {
    badge:   "border-rose-500/30   bg-rose-500/10   text-rose-300",
    numBg:   "bg-rose-500/15",
    numText: "text-rose-400",
    card:    "border-rose-500/15   bg-rose-500/4",
    step:    "text-rose-400/80",
  },
  slate: {
    badge:   "border-slate-500/30  bg-slate-500/10  text-slate-300",
    numBg:   "bg-slate-500/15",
    numText: "text-slate-400",
    card:    "border-slate-500/15  bg-slate-500/4",
    step:    "text-slate-400/80",
  },
};

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: Delegation["status"] }) {
  if (status === "completed") {
    return (
      <span className="flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-emerald-400">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        COMPLETED
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

// ── Task card ─────────────────────────────────────────────────────────────────

interface TaskCardProps {
  d: Delegation;
  index: number;
}

const RESULT_PREVIEW = 240;

function TaskCard({ d, index }: TaskCardProps) {
  const [expanded, setExpanded] = useState(false);
  const m = metaFor(d.subagent);
  const c = COLORS[m.color];
  const hasResult = !!d.result;
  const resultLong = hasResult && (d.result?.length ?? 0) > RESULT_PREVIEW;

  return (
    <div className={`overflow-hidden rounded-xl border ${c.card}`}>
      {/* Header row */}
      <div className="flex items-start gap-3 px-4 py-3.5">
        {/* Number badge */}
        <div className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg ${c.numBg}`}>
          <span className={`text-[12px] font-bold ${c.numText}`}>
            #{index + 1}
          </span>
        </div>

        {/* Main content */}
        <div className="min-w-0 flex-1 space-y-1.5">
          {/* Type badge */}
          <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold tracking-wide ${c.badge}`}>
            <span>{m.icon}</span>
            <span>{m.label}</span>
          </span>

          {/* Task description */}
          <p className="text-[12px] leading-relaxed text-slate-400">
            {d.description || "Working…"}
          </p>

          {/* Live step (while running) */}
          {d.status === "running" && d.current_label && (
            <div className={`flex items-center gap-1.5 text-[11px] ${c.step}`}>
              <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse" />
              {d.current_label}…
            </div>
          )}
          {d.status === "running" && !d.current_label && (
            <div className={`flex items-center gap-1.5 text-[11px] ${c.step}`}>
              <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse" />
              Working…
            </div>
          )}

          {/* Result */}
          {hasResult && (
            <div className="pt-0.5">
              <p className="text-[11.5px] leading-relaxed text-slate-500 whitespace-pre-wrap">
                {expanded || !resultLong
                  ? d.result
                  : d.result!.slice(0, RESULT_PREVIEW) + "…"}
              </p>
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

// ── Panel ─────────────────────────────────────────────────────────────────────

interface SubagentPanelProps {
  delegations: Delegation[];
  activeSubagent: string | null;
  isRunning: boolean;
}

export default function SubagentPanel({ delegations, activeSubagent, isRunning }: SubagentPanelProps) {
  if (!delegations.length && !activeSubagent) return null;

  const completed = delegations.filter((d) => d.status === "completed").length;
  const total = delegations.length;

  return (
    <div className="w-full max-w-lg space-y-3">
      {/* Section header */}
      <div className="flex items-center gap-2">
        <svg className="h-3.5 w-3.5 text-slate-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="8" r="4" />
          <path strokeLinecap="round" d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
        </svg>
        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-600">
          Subagent Tasks
        </span>
        {total > 0 && (
          <span className="ml-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-slate-700">
            {completed}/{total} done
          </span>
        )}
        {/* Active subagent live badge */}
        {activeSubagent && isRunning && !delegations.some((d) => d.status === "running") && (() => {
          const m = metaFor(activeSubagent);
          const c = COLORS[m.color];
          return (
            <span className={`ml-auto flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-medium ${c.badge}`}>
              <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse" />
              {m.icon} {m.label}
            </span>
          );
        })()}
      </div>

      {/* Task cards */}
      <div className="space-y-2">
        {delegations.map((d, i) => (
          <TaskCard key={d.id || i} d={d} index={i} />
        ))}
      </div>
    </div>
  );
}
