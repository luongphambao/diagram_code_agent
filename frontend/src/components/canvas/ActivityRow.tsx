import { useState } from "react";
import type { LogEntry } from "../../hooks/useDiagramAgent";

export default function ActivityRow({ entry }: { entry: LogEntry }) {
  const [expanded, setExpanded] = useState(false);

  if (entry.type === "llm") {
    return (
      <div className="flex items-center gap-2 rounded-md border border-white/5 bg-white/3 px-3 py-1.5">
        <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-violet-400" />
        <span className="font-mono text-[11px] text-violet-300/80">LLM turn #{entry.turn}</span>
        <span className="ml-auto text-[10px] text-slate-700">{entry.t}s</span>
      </div>
    );
  }

  const isEnd = entry.type === "tool_end";
  const title = entry.label || entry.tool || "tool";
  const detail = isEnd ? entry.error || entry.output || "" : entry.input || "";
  const hasDetail = !!detail;
  const isError = !!entry.error;
  const dotClass = isError ? "bg-red-400" : isEnd ? "bg-emerald-400" : "bg-amber-400";
  const statusText = isError ? "ERROR" : isEnd ? "DONE" : "RUN";
  const statusClass = isError ? "text-red-400" : isEnd ? "text-emerald-400" : "text-amber-400";

  return (
    <div
      className={`rounded-md border ${isError ? "border-red-500/20 bg-red-500/5" : "border-white/5 bg-white/3"}`}
    >
      <button
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left"
        onClick={() => hasDetail && setExpanded((v) => !v)}
      >
        <span className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${dotClass}`} />
        <span className={`w-10 flex-shrink-0 text-[10px] font-semibold ${statusClass}`}>
          {statusText}
        </span>
        <span className="min-w-0 flex-shrink-0 text-[11px] font-semibold text-slate-400">
          {title}
        </span>
        {entry.subagent && (
          <span className="flex-shrink-0 rounded border border-white/8 bg-white/4 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-slate-600">
            {entry.subagent}
          </span>
        )}
        <span className="flex-1 truncate font-mono text-[11px] text-slate-600">{detail}</span>
        {entry.elapsed_s !== undefined && (
          <span className="flex-shrink-0 text-[10px] text-slate-700">{entry.elapsed_s}s</span>
        )}
        {hasDetail && (
          <span className="flex-shrink-0 text-[10px] text-slate-700">{expanded ? "▲" : "▼"}</span>
        )}
      </button>
      {expanded && hasDetail && (
        <pre
          className={`whitespace-pre-wrap border-t border-white/5 px-3 py-2 font-mono text-[10px] leading-relaxed ${isError ? "text-red-400/80" : "text-slate-500"}`}
        >
          {detail}
        </pre>
      )}
    </div>
  );
}
