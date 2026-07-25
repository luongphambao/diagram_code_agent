import { useEffect, useRef, useState } from "react";
import type { AgentState, LogEntry } from "../../hooks/useDiagramAgent";
import { fmtMd } from "../../hooks/agent-utils";
import ActivityRow from "./ActivityRow";
import SubagentPanel from "../SubagentPanel";
import QualityPanel from "./QualityPanel";
import CommentThread from "./CommentThread";
import TabBar, { type TabBarItem } from "../../ui/TabBar";
import Button from "../../ui/Button";
import EmptyState from "../../ui/EmptyState";
import Lightbox from "../../canvas/Lightbox";
import CodeTab from "../../canvas/CodeTab";
import CanvasSummaryBar from "../../canvas/CanvasSummaryBar";
import { useExport } from "../../canvas/useExport";
import { resolveSrc } from "../../lib/artifacts";
import { MIME_TYPES } from "../../lib/downloadBase64";

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

const PANEL_ID = "artifact";

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

  const { download, isAvailable, openDrawio } = useExport(agentState);

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
  const [codeView, setCodeView] = useState<"code" | "drawio">("code");
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

  // Count semantics (plan §G): Activity's count is COMPLETED steps
  // (tool_end), not tool_start (which double-counts a still-running step and
  // treats an errored step as a success). A separate danger-colored count
  // surfaces failures — what an operator actually scans for.
  const completedCount = logs ? logs.filter((l) => l.type === "tool_end").length : 0;
  const errorCount = logs ? logs.filter((l) => l.type === "tool_end" && (l.error || l.ok === false)).length : 0;

  const tabItems: TabBarItem[] = tabs.map((t): TabBarItem => {
    if (t === "activity") {
      return {
        id: t,
        label: "Activity",
        count: logs && logs.length > 0 ? (errorCount > 0 ? errorCount : completedCount) : undefined,
        countVariant: errorCount > 0 ? "danger" : isRunning ? "accent" : "neutral",
      };
    }
    if (t === "agents") {
      return {
        id: t,
        label: "Agents",
        count: hasDelegations ? delegations!.length : undefined,
        countVariant: isRunning && hasLiveAgentWork ? "accent" : "neutral",
      };
    }
    const LABELS: Partial<Record<Tab, string>> = { pdf: "PDF", ppt: "PPT", wbs: "WBS" };
    return { id: t, label: LABELS[t] ?? t.charAt(0).toUpperCase() + t.slice(1) };
  });

  return (
    <>
      <div className="flex flex-1 flex-col overflow-hidden bg-surface">
        {/* Toolbar */}
        <div className="flex items-center gap-2 border-b border-line bg-raised px-5 py-2.5">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <span className="h-2 w-2 flex-shrink-0 rounded-full bg-ok shadow-sm" />
            {iteration && iteration > 1 && (
              <span className="flex-shrink-0 rounded-sm bg-well px-2 py-0.5 text-2xs text-muted">v{iteration}</span>
            )}
            <span className="truncate text-xs text-muted">{summary || "Diagram generated"}</span>
          </div>

          <TabBar items={tabItems} active={tab} onSelect={(id) => setTab(id as Tab)} panelId={PANEL_ID} label="Artifact tabs" />

          {/* Download group */}
          <div className="flex items-center gap-2">
            {(["png", "drawio", "pdf", "ppt", "wbs"] as const).map((id) => {
              if (id === "wbs" && !hasWbs) return null;
              return (
                <Button key={id} variant="secondary" size="sm" disabled={!isAvailable(id)} onClick={() => download(id)}>
                  <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  {id === "drawio" ? ".drawio" : id.toUpperCase()}
                </Button>
              );
            })}
            <Button variant="secondary" size="sm" disabled={!drawio} onClick={openDrawio} className="border-accent/30 bg-accent/10 text-accent-text hover:bg-accent/20">
              <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
              Draw.io
            </Button>
            {tab === "preview" && (
              <Button variant="secondary" size="sm" onClick={() => setLightbox(true)}>
                <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 8V4m0 0h4M4 4l5 5m11-5h-4m4 0v4m0-4l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                </svg>
                Zoom
              </Button>
            )}
          </div>
        </div>

        {(hasQuality || hasWbs) && <CanvasSummaryBar agentState={agentState} onSelectTab={(t) => setTab(t as Tab)} />}

        {/* Tab content */}
        <div id={`${PANEL_ID}-panel-${tab}`} role="tabpanel" aria-labelledby={`${PANEL_ID}-tab-${tab}`} className="flex flex-1 flex-col overflow-hidden">
          {tab === "preview" && (
            <div
              className="flex flex-1 cursor-zoom-in items-center justify-center overflow-auto p-8"
              style={{ backgroundImage: "radial-gradient(circle, color-mix(in srgb, var(--ink-100) 3%, transparent) 1px, transparent 1px)", backgroundSize: "20px 20px" }}
              onClick={() => setLightbox(true)}
            >
              <img
                src={resolveSrc(png_base64, MIME_TYPES.png)}
                alt="Generated architecture diagram"
                className="max-h-full max-w-full rounded-md object-contain shadow-2xl ring-1 ring-line transition-transform hover:scale-[1.01]"
              />
            </div>
          )}

          {tab === "code" && (
            <div className="flex flex-1 flex-col overflow-hidden">
              {code || drawio ? (
                <>
                  {code && drawio && (
                    <div className="flex items-center gap-1 border-b border-line bg-raised px-4 pt-2">
                      {(["code", "drawio"] as const).map((v) => (
                        <button
                          key={v}
                          onClick={() => setCodeView(v)}
                          className={`rounded-t-sm px-3 py-1.5 text-xs font-medium ${codeView === v ? "border-b-2 border-accent text-fg" : "text-muted hover:text-secondary"}`}
                        >
                          {v === "code" ? "Diagram Code" : "Draw.io XML"}
                        </button>
                      ))}
                    </div>
                  )}
                  <CodeTab
                    code={codeView === "code" && code ? code : drawio || code || ""}
                    lang={codeView === "code" && code ? "python" : "xml"}
                    title={codeView === "code" && code ? "Diagram source" : "Draw.io XML"}
                  />
                </>
              ) : (
                <EmptyState title="No code available" />
              )}
            </div>
          )}

          {tab === "pdf" && (
            <div className="flex flex-1 flex-col overflow-hidden bg-app">
              {pdf_base64 ? (
                <>
                  <div className="flex items-center justify-between border-b border-line px-4 py-2">
                    <span className="text-xs font-medium text-secondary">PDF report preview</span>
                    <Button variant="secondary" size="sm" onClick={() => download("pdf")}>
                      Download
                    </Button>
                  </div>
                  <iframe title="PDF report preview" src={resolveSrc(pdf_base64, MIME_TYPES.pdf)} className="h-full w-full flex-1 border-0 bg-white" />
                </>
              ) : (
                <EmptyState title="No PDF report available" />
              )}
            </div>
          )}

          {tab === "ppt" && (
            <div className="flex flex-1 flex-col overflow-hidden bg-app">
              <div className="flex items-center justify-between border-b border-line px-4 py-2">
                <span className="text-xs font-medium text-secondary">BnK PowerPoint proposal</span>
                <Button variant="secondary" size="sm" disabled={!pptx_base64} onClick={() => download("ppt")}>
                  Download .pptx
                </Button>
              </div>
              <div className="flex flex-1 items-center justify-center p-8">
                <div className="rounded-md border border-line bg-well px-6 py-5 text-center">
                  <p className="text-sm font-semibold text-fg">Editable PowerPoint ready</p>
                  <p className="mt-1 text-xs text-secondary">
                    PowerPoint preview is not available in-browser. Download the deck to inspect and edit it.
                  </p>
                </div>
              </div>
            </div>
          )}

          {tab === "wbs" && (
            <div className="flex flex-1 flex-col overflow-hidden bg-app">
              <div className="flex items-center justify-between border-b border-line px-4 py-2">
                <span className="text-xs font-medium text-secondary">Work Breakdown Structure</span>
                <Button variant="secondary" size="sm" disabled={!wbs_xlsx_base64} onClick={() => download("wbs")}>
                  Download .xlsx
                </Button>
              </div>
              {wbs_summary ? (
                <div className="flex-1 space-y-5 overflow-y-auto p-6">
                  <div className="flex flex-wrap gap-2">
                    {[
                      `${fmtMd(wbs_summary.total_mandays)} MD`,
                      `${fmtMd(wbs_summary.total_manmonths)} MM`,
                      `${wbs_summary.months} months`,
                      `${wbs_summary.weeks} weeks`,
                    ].map((val) => (
                      <span key={val} className="tnum rounded-sm border border-line bg-well px-3 py-1 text-xs font-semibold text-fg">
                        {val}
                      </span>
                    ))}
                  </div>
                  {Object.keys(wbs_summary.effort_by_role).length > 0 && (
                    <div>
                      <p className="label-caps mb-2 text-2xs font-semibold text-muted">Effort by Role</p>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(wbs_summary.effort_by_role).map(([role, md]) => (
                          <span key={role} className="tnum rounded-sm border border-line bg-well px-2.5 py-1 text-xs text-secondary">
                            <span className="font-semibold text-fg">{role}</span> {fmtMd(md)} MD
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {wbs_summary.effort_by_module.length > 0 && (
                    <div>
                      <p className="label-caps mb-2 text-2xs font-semibold text-muted">Effort by Module</p>
                      <table className="w-full text-xs">
                        <tbody>
                          {wbs_summary.effort_by_module.map((m) => (
                            <tr key={m.code} className="border-b border-line">
                              <td className="py-1.5 pr-3 font-mono text-muted">{m.code}</td>
                              <td className="py-1.5 pr-3 text-secondary">{m.name}</td>
                              <td className="tnum py-1.5 text-right font-semibold text-accent-text">{fmtMd(m.total_md)} MD</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ) : (
                <EmptyState title="No WBS summary available" />
              )}
            </div>
          )}

          {tab === "quality" && (
            <div className="flex flex-1 flex-col overflow-hidden bg-app">
              <div className="flex items-center justify-between border-b border-line px-4 py-2">
                <span className="text-xs font-medium text-secondary">Governance &amp; quality</span>
                {quality?.solution_revision != null && <span className="text-2xs text-muted">CSM rev {quality.solution_revision}</span>}
              </div>
              <QualityPanel quality={quality} compliance={compliance} drift={drift} />
            </div>
          )}

          {tab === "comments" && <CommentThread threadId={threadId} userRole={userRole} />}

          {tab === "activity" && (
            <div className="flex flex-1 flex-col overflow-hidden bg-app">
              {logs && logs.length > 0 ? (
                <div className="flex-1 space-y-1.5 overflow-y-auto p-4">
                  {logs.map((entry: LogEntry, i) => (
                    <ActivityRow key={i} entry={entry} />
                  ))}
                </div>
              ) : (
                <EmptyState title="No activity log available" />
              )}
            </div>
          )}

          {tab === "agents" && (
            <div className="flex flex-1 flex-col overflow-hidden bg-app">
              {hasLiveAgentWork ? (
                <div className="flex-1 overflow-y-auto p-4">
                  <SubagentPanel delegations={delegations ?? []} activeSubagent={activeSubagent ?? null} isRunning={isRunning} logs={logs} activity={activity} />
                </div>
              ) : (
                <EmptyState title="No subagent delegations yet" hint="Drawer & critic agents appear once the blueprint is approved and rendering begins." />
              )}
            </div>
          )}
        </div>
      </div>

      <Lightbox
        open={lightbox}
        onClose={() => setLightbox(false)}
        imageSrc={`data:image/png;base64,${png_base64}`}
        alt="Diagram fullscreen preview"
        actions={
          <>
            <Button variant="secondary" size="sm" onClick={() => download("png")}>
              ↓ PNG
            </Button>
            {drawio && (
              <>
                <Button variant="secondary" size="sm" onClick={() => download("drawio")}>
                  ↓ .drawio
                </Button>
                <Button variant="secondary" size="sm" onClick={openDrawio} className="border-accent/30 bg-accent/10 text-accent-text">
                  ↗ Draw.io
                </Button>
              </>
            )}
            {pdf_base64 && (
              <Button variant="secondary" size="sm" onClick={() => download("pdf")}>
                PDF
              </Button>
            )}
          </>
        }
      />
    </>
  );
}
