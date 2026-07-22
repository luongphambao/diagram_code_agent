import { useEffect, useRef, useState } from "react";
import type { AgentState, LogEntry } from "../../hooks/useDiagramAgent";
import { fmtMd } from "../../hooks/agent-utils";
import ActivityRow from "./ActivityRow";
import SubagentPanel from "../SubagentPanel";
import QualityPanel from "./QualityPanel";
import CommentThread from "./CommentThread";

type Tab =
  "preview" | "pdf" | "ppt" | "wbs" | "quality" | "code" | "activity" | "agents" | "comments";

interface ArtifactTabsProps {
  agentState: AgentState;
  isRunning: boolean;
  activeSubagent?: string | null;
  activity?: string | null;
  threadId: string;
  userRole: string;
}

export default function ArtifactTabs({
  agentState,
  isRunning,
  activeSubagent,
  activity,
  threadId,
  userRole,
}: ArtifactTabsProps) {
  const {
    png_base64,
    pdf_base64,
    pptx_base64,
    wbs_xlsx_base64,
    wbs_summary,
    drawio,
    summary,
    iteration,
    code,
    logs,
    delegations,
    quality,
    compliance,
    drift,
  } = agentState;
  const hasDelegations = !!delegations && delegations.length > 0;
  const hasLiveAgentWork = isRunning || !!activeSubagent || hasDelegations || !!activity;
  const hasWbs = !!wbs_summary || !!wbs_xlsx_base64;
  const hasQuality = !!quality || !!compliance || !!drift;

  const tabs: Tab[] = [
    ...(png_base64 ? (["preview"] as Tab[]) : []),
    ...(pdf_base64 ? (["pdf"] as Tab[]) : []),
    ...(pptx_base64 ? (["ppt"] as Tab[]) : []),
    ...(hasWbs ? (["wbs"] as Tab[]) : []),
    ...(hasQuality ? (["quality"] as Tab[]) : []),
    "code",
    "activity",
    "agents",
    "comments",
  ];

  // Default to whichever artifact tab actually has content — falling back to
  // "preview" would render a broken image when no diagram was generated yet
  // (e.g. a WBS-only conversation).
  const [tab, setTabState] = useState<Tab>(tabs[0]);
  const [lightbox, setLightbox] = useState(false);
  // `tabs` is recomputed every render, so the mount-time `tabs[0]` snapshot goes stale
  // when an artifact (e.g. WBS) arrives AFTER mount: the new tab shows in the bar but
  // stays unselected, and if the active tab ever leaves `tabs` the content area renders
  // nothing. Follow the best artifact tab until the user manually picks one, and always
  // recover if the current tab disappears.
  const userPicked = useRef(false);
  const setTab = (t: Tab) => {
    userPicked.current = true;
    setTabState(t);
  };
  const tabsKey = tabs.join("|");
  useEffect(() => {
    if (!tabs.includes(tab)) {
      setTabState(tabs[0]);
    } else if (!userPicked.current && tab !== tabs[0]) {
      setTabState(tabs[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabsKey]);

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

  const downloadPdf = () => {
    if (!pdf_base64) return;
    const bytes = Uint8Array.from(atob(pdf_base64), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `architecture_report${iteration && iteration > 1 ? `_v${iteration}` : ""}.pdf`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadWbsXlsx = () => {
    if (!wbs_xlsx_base64) return;
    const bytes = Uint8Array.from(atob(wbs_xlsx_base64), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(
      new Blob([bytes], {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `wbs${iteration && iteration > 1 ? `_v${iteration}` : ""}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadPptx = () => {
    if (!pptx_base64) return;
    const bytes = Uint8Array.from(atob(pptx_base64), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(
      new Blob([bytes], {
        type: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `architecture_proposal${iteration && iteration > 1 ? `_v${iteration}` : ""}.pptx`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const openInDrawio = () => {
    if (!drawio) return;
    window.open(`https://app.diagrams.net/?src=about#U${encodeURIComponent(drawio)}`, "_blank");
  };

  return (
    <>
      <div className="flex flex-1 flex-col overflow-hidden bg-surface-canvas">
        {/* Toolbar */}
        <div className="flex items-center gap-2 border-b border-white/8 bg-surface-panel px-5 py-2.5">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <span className="h-2 w-2 flex-shrink-0 rounded-full bg-emerald-400 shadow-sm shadow-emerald-500/40" />
            {iteration && iteration > 1 && (
              <span className="flex-shrink-0 rounded-full bg-white/8 px-2 py-0.5 text-[11px] text-slate-600">
                v{iteration}
              </span>
            )}
            <span className="truncate text-xs text-slate-600">
              {summary || "Diagram generated"}
            </span>
          </div>

          {/* Tabs */}
          <div className="flex items-center rounded-lg border border-white/8 bg-white/4 p-0.5">
            {tabs.map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`rounded-md px-3 py-1 text-[11px] font-medium capitalize transition-colors ${
                  tab === t ? "bg-white/10 text-slate-200" : "text-slate-600 hover:text-slate-400"
                }`}
              >
                {t === "activity" && logs && logs.length > 0
                  ? `Activity (${logs.filter((e) => e.type === "tool_start").length})`
                  : t === "agents" && delegations && delegations.length > 0
                    ? `Agents (${delegations.length})`
                    : t === "pdf"
                      ? "PDF"
                      : t === "ppt"
                        ? "PPT"
                        : t === "wbs"
                          ? "WBS"
                          : t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>

          {/* Download group */}
          <div className="flex items-center gap-2">
            {(["PNG", ".drawio", "PDF", "PPT", "WBS"] as const).map((label) => {
              if (label === "WBS" && !hasWbs) return null;
              const disabled =
                label === "PNG"
                  ? !png_base64
                  : label === ".drawio"
                    ? !drawio
                    : label === "PDF"
                      ? !pdf_base64
                      : label === "PPT"
                        ? !pptx_base64
                        : !wbs_xlsx_base64;
              const handler =
                label === "PNG"
                  ? downloadPng
                  : label === ".drawio"
                    ? downloadDrawio
                    : label === "PDF"
                      ? downloadPdf
                      : label === "PPT"
                        ? downloadPptx
                        : downloadWbsXlsx;
              return (
                <button
                  key={label}
                  onClick={handler}
                  disabled={disabled}
                  className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/4 px-3 py-1.5 text-xs font-medium text-slate-400 transition-colors hover:bg-white/8 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-30"
                >
                  <svg
                    className="h-3 w-3"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                    />
                  </svg>
                  {label}
                </button>
              );
            })}
            <button
              onClick={openInDrawio}
              disabled={!drawio}
              className="flex items-center gap-1.5 rounded-lg border border-blue-500/25 bg-blue-500/8 px-3 py-1.5 text-xs font-medium text-blue-400 transition-colors hover:bg-blue-500/15 disabled:cursor-not-allowed disabled:opacity-30"
            >
              <svg
                className="h-3 w-3"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
                />
              </svg>
              Draw.io
            </button>
            {tab === "preview" && (
              <button
                onClick={() => setLightbox(true)}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/4 px-3 py-1.5 text-xs font-medium text-slate-400 transition-colors hover:bg-white/8 hover:text-slate-200"
              >
                <svg
                  className="h-3 w-3"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M4 8V4m0 0h4M4 4l5 5m11-5h-4m4 0v4m0-4l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"
                  />
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
            style={{
              backgroundImage:
                "radial-gradient(circle, rgba(255,255,255,0.025) 1px, transparent 1px)",
              backgroundSize: "20px 20px",
            }}
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
              <pre className="flex-1 overflow-auto bg-surface-base p-6 font-mono text-xs leading-relaxed text-slate-300">
                {code}
              </pre>
            ) : (
              <div className="flex flex-1 items-center justify-center">
                <p className="text-sm text-slate-700">No code available</p>
              </div>
            )}
          </div>
        )}

        {tab === "pdf" && (
          <div className="flex flex-1 flex-col overflow-hidden bg-surface-base">
            {pdf_base64 ? (
              <>
                <div className="flex items-center justify-between border-b border-white/8 px-4 py-2">
                  <span className="text-xs font-medium text-slate-400">PDF report preview</span>
                  <button
                    onClick={downloadPdf}
                    className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/4 px-3 py-1.5 text-xs font-medium text-slate-300 transition-colors hover:bg-white/8"
                  >
                    <svg
                      className="h-3 w-3"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                      />
                    </svg>
                    Download
                  </button>
                </div>
                <iframe
                  title="PDF report preview"
                  src={`data:application/pdf;base64,${pdf_base64}`}
                  className="h-full w-full flex-1 border-0 bg-white"
                />
              </>
            ) : (
              <div className="flex flex-1 items-center justify-center">
                <p className="text-sm text-slate-700">No PDF report available</p>
              </div>
            )}
          </div>
        )}

        {tab === "ppt" && (
          <div className="flex flex-1 flex-col overflow-hidden bg-surface-base">
            <div className="flex items-center justify-between border-b border-white/8 px-4 py-2">
              <span className="text-xs font-medium text-slate-400">BnK PowerPoint proposal</span>
              <button
                onClick={downloadPptx}
                disabled={!pptx_base64}
                className="flex items-center gap-1.5 rounded-lg border border-orange-500/30 bg-orange-500/10 px-3 py-1.5 text-xs font-medium text-orange-200 transition-colors hover:bg-orange-500/20 disabled:cursor-not-allowed disabled:opacity-30"
              >
                <svg
                  className="h-3 w-3"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                  />
                </svg>
                Download .pptx
              </button>
            </div>
            <div className="flex flex-1 items-center justify-center p-8">
              <div className="rounded-xl border border-orange-500/20 bg-orange-500/8 px-6 py-5 text-center">
                <p className="text-sm font-semibold text-orange-100">Editable PowerPoint ready</p>
                <p className="mt-1 text-xs text-slate-500">
                  PowerPoint preview is not available in-browser. Download the deck to inspect and
                  edit it.
                </p>
              </div>
            </div>
          </div>
        )}

        {tab === "wbs" && (
          <div className="flex flex-1 flex-col overflow-hidden bg-surface-base">
            <div className="flex items-center justify-between border-b border-white/8 px-4 py-2">
              <span className="text-xs font-medium text-slate-400">Work Breakdown Structure</span>
              <button
                onClick={downloadWbsXlsx}
                disabled={!wbs_xlsx_base64}
                className="flex items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-200 transition-colors hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-30"
              >
                <svg
                  className="h-3 w-3"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                  />
                </svg>
                Download .xlsx
              </button>
            </div>
            {wbs_summary ? (
              <div className="flex-1 space-y-5 overflow-y-auto p-6">
                <div className="flex flex-wrap gap-2">
                  {[
                    {
                      val: fmtMd(wbs_summary.total_mandays) + " MD",
                      cls: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
                    },
                    {
                      val: fmtMd(wbs_summary.total_manmonths) + " MM",
                      cls: "border-teal-500/30 bg-teal-500/10 text-teal-300",
                    },
                    {
                      val: wbs_summary.months + " months",
                      cls: "border-sky-500/30 bg-sky-500/10 text-sky-300",
                    },
                    {
                      val: wbs_summary.weeks + " weeks",
                      cls: "border-slate-500/30 bg-slate-500/10 text-slate-300",
                    },
                  ].map(({ val, cls }) => (
                    <span
                      key={val}
                      className={`rounded-full border px-3 py-1 text-xs font-semibold ${cls}`}
                    >
                      {val}
                    </span>
                  ))}
                </div>
                {Object.keys(wbs_summary.effort_by_role).length > 0 && (
                  <div>
                    <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                      Effort by Role
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(wbs_summary.effort_by_role).map(([role, md]) => (
                        <span
                          key={role}
                          className="rounded border border-white/8 bg-white/5 px-2.5 py-1 text-xs text-slate-300"
                        >
                          <span className="font-semibold text-white">{role}</span> {fmtMd(md)} MD
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {wbs_summary.effort_by_module.length > 0 && (
                  <div>
                    <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                      Effort by Module
                    </p>
                    <table className="w-full text-xs">
                      <tbody>
                        {wbs_summary.effort_by_module.map((m) => (
                          <tr key={m.code} className="border-b border-white/5">
                            <td className="py-1.5 pr-3 font-mono text-slate-500">{m.code}</td>
                            <td className="py-1.5 pr-3 text-slate-300">{m.name}</td>
                            <td className="py-1.5 text-right font-semibold text-emerald-300">
                              {fmtMd(m.total_md)} MD
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex flex-1 items-center justify-center">
                <p className="text-sm text-slate-700">No WBS summary available</p>
              </div>
            )}
          </div>
        )}

        {tab === "quality" && (
          <div className="flex flex-1 flex-col overflow-hidden bg-surface-base">
            <div className="flex items-center justify-between border-b border-white/8 px-4 py-2">
              <span className="text-xs font-medium text-slate-400">Governance &amp; quality</span>
              {quality?.solution_revision != null && (
                <span className="text-[11px] text-slate-600">
                  CSM rev {quality.solution_revision}
                </span>
              )}
            </div>
            <QualityPanel quality={quality} compliance={compliance} drift={drift} />
          </div>
        )}

        {tab === "comments" && <CommentThread threadId={threadId} userRole={userRole} />}

        {tab === "activity" && (
          <div className="flex flex-1 flex-col overflow-hidden bg-surface-base">
            {logs && logs.length > 0 ? (
              <div className="flex-1 space-y-1.5 overflow-y-auto p-4">
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
          <div className="flex flex-1 flex-col overflow-hidden bg-surface-base">
            {hasLiveAgentWork ? (
              <div className="flex-1 overflow-y-auto p-4">
                <SubagentPanel
                  delegations={delegations ?? []}
                  activeSubagent={activeSubagent ?? null}
                  isRunning={isRunning}
                  logs={logs}
                  activity={activity}
                />
              </div>
            ) : (
              <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
                <p className="text-sm text-slate-600">No subagent delegations yet</p>
                <p className="text-xs text-slate-700">
                  Drawer &amp; critic agents appear once the blueprint is approved and rendering
                  begins.
                </p>
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
            <svg
              className="h-5 w-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
          <div className="absolute right-5 top-16 flex flex-col gap-2">
            <button
              onClick={(e) => {
                e.stopPropagation();
                downloadPng();
              }}
              className="flex items-center gap-2 rounded-lg border border-white/15 bg-white/10 px-3 py-2 text-xs font-medium text-white hover:bg-white/20"
            >
              ↓ PNG
            </button>
            {drawio && (
              <>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    downloadDrawio();
                  }}
                  className="flex items-center gap-2 rounded-lg border border-white/15 bg-white/10 px-3 py-2 text-xs font-medium text-white hover:bg-white/20"
                >
                  ↓ .drawio
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    openInDrawio();
                  }}
                  className="flex items-center gap-2 rounded-lg border border-blue-500/40 bg-blue-500/20 px-3 py-2 text-xs font-medium text-blue-300 hover:bg-blue-500/30"
                >
                  ↗ Draw.io
                </button>
              </>
            )}
            {pdf_base64 && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  downloadPdf();
                }}
                className="flex items-center gap-2 rounded-lg border border-white/15 bg-white/10 px-3 py-2 text-xs font-medium text-white hover:bg-white/20"
              >
                PDF
              </button>
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
