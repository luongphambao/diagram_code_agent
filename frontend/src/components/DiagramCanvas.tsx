import { useState } from "react";
import type { AgentState, LogEntry, PendingInterrupt } from "../hooks/useDiagramAgent";
import AgentStatus from "./AgentStatus";
import SubagentPanel from "./SubagentPanel";

// ── Activity log row ──────────────────────────────────────────────────────────

function ActivityRow({ entry }: { entry: LogEntry }) {
  const [expanded, setExpanded] = useState(false);

  if (entry.type === "llm") {
    return (
      <div className="flex items-center gap-2 rounded-md px-3 py-1.5 bg-white/3 border border-white/5">
        <span className="h-1.5 w-1.5 rounded-full bg-violet-400 flex-shrink-0" />
        <span className="text-[11px] text-violet-300/80 font-mono">
          LLM turn #{entry.turn}
        </span>
        <span className="text-[10px] text-slate-700 ml-auto">{entry.t}s</span>
      </div>
    );
  }

  const hasDetail = !!(entry.output || entry.error);
  const isError = !!entry.error;

  return (
    <div
      className={`rounded-md border ${isError ? "border-red-500/20 bg-red-500/5" : "border-white/5 bg-white/3"}`}
    >
      <button
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left"
        onClick={() => hasDetail && setExpanded((v) => !v)}
      >
        <span className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${isError ? "bg-red-400" : "bg-blue-400"}`} />
        <span className="text-[11px] font-semibold text-slate-400 flex-shrink-0">{entry.tool}</span>
        <span className="flex-1 truncate text-[11px] text-slate-600 font-mono">{entry.input}</span>
        {entry.elapsed_s !== undefined && (
          <span className="flex-shrink-0 text-[10px] text-slate-700">{entry.elapsed_s}s</span>
        )}
        {hasDetail && (
          <span className="flex-shrink-0 text-[10px] text-slate-700">{expanded ? "▲" : "▼"}</span>
        )}
      </button>
      {expanded && hasDetail && (
        <pre className={`border-t border-white/5 px-3 py-2 font-mono text-[10px] leading-relaxed whitespace-pre-wrap ${isError ? "text-red-400/80" : "text-slate-500"}`}>
          {entry.error ?? entry.output}
        </pre>
      )}
    </div>
  );
}

interface DiagramCanvasProps {
  agentState: AgentState;
  pendingInterrupt: PendingInterrupt | null;
  isRunning: boolean;
  activeSubagent?: string | null;
  activity?: string | null;
}

type Tab = "preview" | "code" | "activity" | "agents";

export default function DiagramCanvas({ agentState, pendingInterrupt, isRunning, activeSubagent, activity }: DiagramCanvasProps) {
  const [lightbox, setLightbox] = useState(false);
  const [tab, setTab] = useState<Tab>("preview");
  const { current_step, png_base64, drawio, summary, error, iteration, code, logs, delegations } = agentState;

  // ── Download helpers ──────────────────────────────────────────────────────
  const downloadPng = () => {
    if (!png_base64) return;
    const a = document.createElement("a");
    a.href = `data:image/png;base64,${png_base64}`;
    a.download = `diagram${iteration && iteration > 1 ? `_v${iteration}` : ""}.png`;
    a.click();
  };

  const downloadDrawio = () => {
    if (!drawio) return;
    const blob = new Blob([drawio], { type: "application/xml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `diagram${iteration && iteration > 1 ? `_v${iteration}` : ""}.drawio`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const openInDrawio = () => {
    if (!drawio) return;
    window.open(`https://app.diagrams.net/?src=about#U${encodeURIComponent(drawio)}`, "_blank");
  };

  // ── Empty / idle ──────────────────────────────────────────────────────────
  if (!current_step && !isRunning && !png_base64 && !error && !pendingInterrupt) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-5 bg-[#0f1117]">
        <div className="flex h-24 w-24 items-center justify-center rounded-3xl border border-white/8 bg-white/4">
          <svg className="h-12 w-12 text-slate-800" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
            <rect x="3" y="3" width="7" height="7" rx="1.5" />
            <rect x="14" y="3" width="7" height="7" rx="1.5" />
            <rect x="3" y="14" width="7" height="7" rx="1.5" />
            <path d="M17.5 14v7M14 17.5h7" strokeLinecap="round" />
            <path d="M10 6.5h4M6.5 10v4" strokeLinecap="round" />
          </svg>
        </div>
        <div className="text-center">
          <p className="text-base font-semibold text-slate-600">Diagram will appear here</p>
          <p className="mt-1.5 text-sm text-slate-800">Start a conversation in the chat panel</p>
        </div>
      </div>
    );
  }

  // ── Diagram ready ─────────────────────────────────────────────────────────
  if (png_base64) {
    return (
      <>
        <div className="flex flex-1 flex-col overflow-hidden bg-[#0f1117]">
          {/* Toolbar */}
          <div className="flex items-center gap-2 border-b border-white/8 bg-[#0c1015] px-5 py-2.5">
            {/* Status dot + summary */}
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <span className="h-2 w-2 flex-shrink-0 rounded-full bg-emerald-400 shadow-sm shadow-emerald-500/40" />
              {iteration && iteration > 1 && (
                <span className="flex-shrink-0 rounded-full bg-white/8 px-2 py-0.5 text-[11px] text-slate-600">
                  v{iteration}
                </span>
              )}
              <span className="truncate text-xs text-slate-600">{summary || "Diagram generated"}</span>
            </div>

            {/* Tabs */}
            <div className="flex items-center rounded-lg border border-white/8 bg-white/4 p-0.5">
              {(["preview", "code", "activity", "agents"] as Tab[]).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`rounded-md px-3 py-1 text-[11px] font-medium capitalize transition-colors ${
                    tab === t
                      ? "bg-white/10 text-slate-200"
                      : "text-slate-600 hover:text-slate-400"
                  }`}
                >
                  {t === "activity" && logs && logs.length > 0
                    ? `Activity (${logs.filter((e) => e.type === "tool_start").length})`
                    : t === "agents" && delegations && delegations.length > 0
                    ? `Agents (${delegations.length})`
                    : t === "code" && code
                    ? "Code"
                    : t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>

            {/* Download group */}
            <div className="flex items-center gap-2">
              <button
                onClick={downloadPng}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/4 px-3 py-1.5 text-xs font-medium text-slate-400 transition-colors hover:bg-white/8 hover:text-slate-200"
              >
                <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                PNG
              </button>
              <button
                onClick={downloadDrawio}
                disabled={!drawio}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/4 px-3 py-1.5 text-xs font-medium text-slate-400 transition-colors hover:bg-white/8 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-30"
              >
                <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                .drawio
              </button>
              <button
                onClick={openInDrawio}
                disabled={!drawio}
                className="flex items-center gap-1.5 rounded-lg border border-blue-500/25 bg-blue-500/8 px-3 py-1.5 text-xs font-medium text-blue-400 transition-colors hover:bg-blue-500/15 disabled:cursor-not-allowed disabled:opacity-30"
              >
                <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
                Draw.io
              </button>
              {tab === "preview" && (
                <button
                  onClick={() => setLightbox(true)}
                  className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/4 px-3 py-1.5 text-xs font-medium text-slate-400 transition-colors hover:bg-white/8 hover:text-slate-200"
                  title="Full screen preview"
                >
                  <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4 8V4m0 0h4M4 4l5 5m11-5h-4m4 0v4m0-4l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                  </svg>
                  Zoom
                </button>
              )}
            </div>
          </div>

          {/* Tab content */}
          {tab === "preview" && (
            <div
              className="flex flex-1 cursor-zoom-in items-center justify-center overflow-auto p-8"
              style={{ backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.025) 1px, transparent 1px)", backgroundSize: "20px 20px" }}
              onClick={() => setLightbox(true)}
            >
              <img
                src={`data:image/png;base64,${png_base64}`}
                alt="Generated architecture diagram"
                className="max-h-full max-w-full rounded-xl object-contain shadow-2xl ring-1 ring-white/8 transition-transform hover:scale-[1.01]"
              />
            </div>
          )}

          {tab === "code" && (
            <div className="flex flex-1 flex-col overflow-hidden">
              {code ? (
                <pre className="flex-1 overflow-auto p-6 font-mono text-xs leading-relaxed text-slate-300 bg-[#0b0e14]">
                  {code}
                </pre>
              ) : (
                <div className="flex flex-1 items-center justify-center">
                  <p className="text-sm text-slate-700">No code available</p>
                </div>
              )}
            </div>
          )}

          {tab === "activity" && (
            <div className="flex flex-1 flex-col overflow-hidden bg-[#0b0e14]">
              {logs && logs.length > 0 ? (
                <div className="flex-1 overflow-y-auto p-4 space-y-1.5">
                  {logs.map((entry: LogEntry, i) => (
                    <ActivityRow key={i} entry={entry} />
                  ))}
                </div>
              ) : (
                <div className="flex flex-1 items-center justify-center">
                  <p className="text-sm text-slate-700">No activity log available</p>
                </div>
              )}
            </div>
          )}

          {tab === "agents" && (
            <div className="flex flex-1 flex-col overflow-hidden bg-[#0b0e14]">
              {delegations && delegations.length > 0 ? (
                <div className="flex-1 overflow-y-auto p-4">
                  <SubagentPanel
                    delegations={delegations}
                    activeSubagent={activeSubagent ?? null}
                    isRunning={false}
                    logs={logs}
                  />
                </div>
              ) : (
                <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center px-6">
                  <p className="text-sm text-slate-600">No subagent delegations yet</p>
                  {isRunning && (
                    <p className="text-xs text-slate-700">Drawer &amp; critic agents appear once the blueprint is approved and rendering begins.</p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Lightbox */}
        {lightbox && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-sm"
            onClick={() => setLightbox(false)}
          >
            <button
              className="absolute right-5 top-5 flex h-9 w-9 items-center justify-center rounded-full border border-white/15 bg-white/10 text-white transition-colors hover:bg-white/20"
              onClick={() => setLightbox(false)}
            >
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
            <div className="absolute right-5 top-16 flex flex-col gap-2">
              <button
                onClick={(e) => { e.stopPropagation(); downloadPng(); }}
                className="flex items-center gap-2 rounded-lg border border-white/15 bg-white/10 px-3 py-2 text-xs font-medium text-white hover:bg-white/20"
              >
                ↓ PNG
              </button>
              {drawio && (
                <>
                  <button
                    onClick={(e) => { e.stopPropagation(); downloadDrawio(); }}
                    className="flex items-center gap-2 rounded-lg border border-white/15 bg-white/10 px-3 py-2 text-xs font-medium text-white hover:bg-white/20"
                  >
                    ↓ .drawio
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); openInDrawio(); }}
                    className="flex items-center gap-2 rounded-lg border border-blue-500/40 bg-blue-500/20 px-3 py-2 text-xs font-medium text-blue-300 hover:bg-blue-500/30"
                  >
                    ↗ Draw.io
                  </button>
                </>
              )}
            </div>
            <img
              src={`data:image/png;base64,${png_base64}`}
              alt="Diagram fullscreen preview"
              className="max-h-[90vh] max-w-[90vw] rounded-xl object-contain shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        )}
      </>
    );
  }

  // ── In-progress / waiting ─────────────────────────────────────────────────
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 bg-[#0f1117] p-10 overflow-y-auto">
      {(isRunning || current_step) && (
        <AgentStatus
          step={current_step ?? (isRunning ? "planning" : "done")}
          iteration={iteration}
        />
      )}

      {/* Live subagent delegation panel */}
      <div className="w-full max-w-lg">
        <SubagentPanel
          delegations={delegations ?? []}
          activeSubagent={activeSubagent ?? null}
          isRunning={isRunning}
          logs={logs}
          activity={activity}
        />
      </div>

      {isRunning && (
        <p className="text-xs text-slate-800">This usually takes 1–3 minutes depending on complexity.</p>
      )}

      {pendingInterrupt && !isRunning && (
        <p className="text-xs text-blue-500/80">← Review this step in the chat panel to continue.</p>
      )}

      {error && (
        <div className="w-full max-w-lg rounded-2xl border border-red-500/20 bg-red-500/8 p-5">
          <p className="text-sm font-semibold text-red-400">Generation failed</p>
          <p className="mt-1.5 text-xs leading-relaxed text-red-400/70">{error}</p>
        </div>
      )}
    </div>
  );
}
