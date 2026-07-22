import { Fragment, useEffect, useRef, useState } from "react";
import { useAgentContext } from "../../context/AgentContext";
import type { DecisionPayload, ResolvedGate } from "../../hooks/useDiagramAgent";
import { downloadBase64File, openBase64InNewTab, MIME_TYPES } from "../../lib/downloadBase64";
import { fmtMd } from "../../hooks/agent-utils";
import TechStackApproval from "../TechStackApproval";
import BlueprintApproval from "../BlueprintApproval";
import DiagramFeedback from "../DiagramFeedback";
import PdfReportApproval from "../PdfReportApproval";
import PptProposalApproval from "../PptProposalApproval";
import EmailApproval from "../EmailApproval";
import MeetingApproval from "../MeetingApproval";
import MeetingSlotPicker from "../MeetingSlotPicker";
import WbsSkeletonApproval from "../WbsSkeletonApproval";
import WbsApproval from "../WbsApproval";
import WbsExcelApproval from "../WbsExcelApproval";
import DeliveryExportApproval from "../DeliveryExportApproval";

const GATE_LABELS: Record<string, string> = {
  brief_approval: "Requirements Brief",
  techstack_approval: "Tech Stack Recommendation",
  blueprint_approval: "Architecture Blueprint",
  result_review: "Diagram Review",
  pdf_report_approval: "PDF Report",
  ppt_proposal_approval: "PPT Proposal",
  email_approval: "Email",
  slot_picker: "Meeting Slot",
  meeting_approval: "Meeting",
  wbs_skeleton_approval: "WBS Skeleton",
  wbs_approval: "WBS Plan",
  wbs_excel_approval: "WBS Excel Export",
  delivery_export_approval: "Delivery Export",
};

function summarizeDecision(decision: Record<string, unknown>): { positive: boolean; text: string } {
  if (
    typeof decision.action === "string" &&
    decision.action !== "approve" &&
    decision.action !== "reject"
  ) {
    return { positive: true, text: decision.action.replace(/_/g, " ") };
  }
  if (typeof decision.satisfied === "boolean") {
    return {
      positive: decision.satisfied,
      text: decision.satisfied ? "Satisfied" : "Needs changes",
    };
  }
  if (typeof decision.approved === "boolean") {
    return { positive: decision.approved, text: decision.approved ? "Approved" : "Rejected" };
  }
  return { positive: true, text: "Resolved" };
}

function ResolvedGateCard({ gate }: { gate: ResolvedGate }) {
  const label = GATE_LABELS[gate.data.type] ?? gate.data.type;
  const { positive, text } = summarizeDecision(gate.decision);
  const note = (gate.decision.modifications ?? gate.decision.feedback ?? gate.decision.comment) as
    string | undefined;
  return (
    <div className="ml-9 max-w-[82%] rounded-xl border border-white/8 bg-white/3 px-3.5 py-2.5">
      <div className="flex items-center gap-2">
        <span
          className={`h-1.5 w-1.5 rounded-full ${positive ? "bg-emerald-400" : "bg-red-400"}`}
        />
        <p className="text-xs font-semibold text-slate-300">{label}</p>
        <span
          className={`ml-auto text-[10px] font-medium capitalize ${positive ? "text-emerald-400" : "text-red-400"}`}
        >
          {text}
        </span>
      </div>
      {gate.data.question && (
        <p className="mt-1 text-[11px] text-slate-600">{gate.data.question}</p>
      )}
      {note && <p className="mt-1 text-[11px] italic text-slate-500">"{note}"</p>}
    </div>
  );
}

export default function MessageList() {
  const {
    chatMessages: messages,
    pendingInterrupt,
    gateHistory,
    isRunning,
    agentState,
    activity,
    activeSubagent,
    error,
    resolveGate,
  } = useAgentContext();
  const {
    pdf_base64: pdfBase64,
    pptx_base64: pptxBase64,
    wbs_xlsx_base64: wbsXlsxBase64,
    wbs_summary: wbsSummary,
    last_meeting: lastMeeting,
    iteration,
  } = agentState;

  const [wbsPreviewOpen, setWbsPreviewOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, error, pendingInterrupt, pdfBase64, pptxBase64, wbsXlsxBase64, lastMeeting]);

  const onResolveTechStack = (approved: boolean, modifications?: string) =>
    resolveGate({ approved, modifications: modifications?.trim() || null });
  const onResolveBlueprint = onResolveTechStack;
  const onResolvePdfReport = onResolveTechStack;
  const onResolvePptProposal = onResolveTechStack;
  const onResolveWbsSkeleton = onResolveTechStack;
  const onResolveWbs = onResolveTechStack;
  const onResolveResult = (satisfied: boolean, feedback?: string) =>
    resolveGate({ satisfied, feedback: feedback?.trim() || null });
  const onResolveEmail = (approved: boolean) => resolveGate({ approved });
  const onResolveMeeting = onResolveEmail;
  const onResolveWbsExcel = onResolveEmail;
  const onResolveDeliveryExport = onResolveEmail;
  const onResolveMeetingSlot = (
    approved: boolean,
    selectedSlot?: { start: string; end: string; display_day: string; display_time: string },
  ) => resolveGate({ approved, selected_slot: selectedSlot });
  const onResolveDecision = (payload: DecisionPayload) => resolveGate({ ...payload });

  const previewPdf = () => {
    if (pdfBase64) openBase64InNewTab(pdfBase64, MIME_TYPES.pdf);
  };
  const downloadPdf = () => {
    if (pdfBase64) downloadBase64File(pdfBase64, "architecture_report.pdf", MIME_TYPES.pdf);
  };
  const downloadWbsXlsx = () => {
    if (wbsXlsxBase64) downloadBase64File(wbsXlsxBase64, "wbs_filled.xlsx", MIME_TYPES.xlsx);
  };
  const downloadPptx = () => {
    if (pptxBase64) downloadBase64File(pptxBase64, "architecture_proposal.pptx", MIME_TYPES.pptx);
  };

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-5 py-5">
      {messages.length === 0 && !isRunning && (
        <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-white/8 bg-white/4">
            <svg
              className="h-7 w-7 text-slate-700"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z"
              />
            </svg>
          </div>
          <div>
            <p className="text-sm font-medium text-slate-500">Describe your architecture</p>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-700">
              e.g. "Microservices with API gateway, auth service,
              <br />
              Postgres database, and Redis cache"
            </p>
          </div>
        </div>
      )}

      {messages.map((msg, i) => (
        <Fragment key={msg.id}>
          {gateHistory
            .filter((g) => g.afterMessageIndex === i)
            .map((g) => (
              <ResolvedGateCard key={g.id} gate={g} />
            ))}
          <div className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            {msg.role === "assistant" && (
              <div className="mt-1 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-blue-600/20">
                <svg className="h-3 w-3 text-blue-400" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z" />
                </svg>
              </div>
            )}
            <div
              className={`max-w-[82%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                msg.role === "user"
                  ? "rounded-tr-sm bg-blue-600 text-white shadow-lg shadow-blue-900/30"
                  : "rounded-tl-sm border border-white/8 bg-white/5 text-slate-200"
              }`}
            >
              {msg.content || (
                <span className="inline-flex gap-1 text-slate-500">
                  <span className="animate-bounce [animation-delay:0ms]">·</span>
                  <span className="animate-bounce [animation-delay:150ms]">·</span>
                  <span className="animate-bounce [animation-delay:300ms]">·</span>
                </span>
              )}
            </div>
          </div>
        </Fragment>
      ))}
      {gateHistory
        .filter((g) => g.afterMessageIndex === messages.length)
        .map((g) => (
          <ResolvedGateCard key={g.id} gate={g} />
        ))}

      {/* HITL gate cards */}
      {pendingInterrupt?.data.type === "techstack_approval" && (
        <div className="mt-1">
          <TechStackApproval
            interrupt={pendingInterrupt}
            onResolve={onResolveTechStack}
            onDecision={onResolveDecision}
            disabled={isRunning}
          />
        </div>
      )}
      {pendingInterrupt?.data.type === "blueprint_approval" && (
        <div className="mt-1">
          <BlueprintApproval
            interrupt={pendingInterrupt}
            onResolve={onResolveBlueprint}
            onDecision={onResolveDecision}
            disabled={isRunning}
          />
        </div>
      )}
      {pendingInterrupt?.data.type === "result_review" && (
        <div className="mt-1">
          <DiagramFeedback
            interrupt={pendingInterrupt}
            onResolve={onResolveResult}
            disabled={isRunning}
            iteration={iteration ?? pendingInterrupt.data.iteration ?? 1}
          />
        </div>
      )}
      {pendingInterrupt?.data.type === "pdf_report_approval" && (
        <div className="mt-1">
          <PdfReportApproval
            interrupt={pendingInterrupt}
            onResolve={onResolvePdfReport}
            onDecision={onResolveDecision}
            disabled={isRunning}
          />
        </div>
      )}
      {pendingInterrupt?.data.type === "ppt_proposal_approval" && (
        <div className="mt-1">
          <PptProposalApproval
            interrupt={pendingInterrupt}
            onResolve={onResolvePptProposal}
            onDecision={onResolveDecision}
            disabled={isRunning}
          />
        </div>
      )}
      {pendingInterrupt?.data.type === "email_approval" && (
        <div className="mt-1">
          <EmailApproval
            interrupt={pendingInterrupt}
            onResolve={onResolveEmail}
            disabled={isRunning}
          />
        </div>
      )}
      {pendingInterrupt?.data.type === "slot_picker" && (
        <div className="mt-1">
          <MeetingSlotPicker
            interrupt={pendingInterrupt}
            onResolve={onResolveMeetingSlot}
            disabled={isRunning}
          />
        </div>
      )}
      {pendingInterrupt?.data.type === "meeting_approval" && (
        <div className="mt-1">
          <MeetingApproval
            interrupt={pendingInterrupt}
            onResolve={onResolveMeeting}
            disabled={isRunning}
          />
        </div>
      )}
      {pendingInterrupt?.data.type === "wbs_skeleton_approval" && (
        <div className="mt-1">
          <WbsSkeletonApproval
            interrupt={pendingInterrupt}
            onResolve={onResolveWbsSkeleton}
            onDecision={onResolveDecision}
            disabled={isRunning}
          />
        </div>
      )}
      {pendingInterrupt?.data.type === "wbs_approval" && (
        <div className="mt-1">
          <WbsApproval
            interrupt={pendingInterrupt}
            onResolve={onResolveWbs}
            onDecision={onResolveDecision}
            disabled={isRunning}
          />
        </div>
      )}
      {pendingInterrupt?.data.type === "wbs_excel_approval" && (
        <div className="mt-1">
          <WbsExcelApproval
            interrupt={pendingInterrupt}
            onResolve={onResolveWbsExcel}
            onDecision={onResolveDecision}
            disabled={isRunning}
          />
        </div>
      )}
      {pendingInterrupt?.data.type === "delivery_export_approval" && (
        <div className="mt-1">
          <DeliveryExportApproval
            interrupt={pendingInterrupt}
            onResolve={onResolveDeliveryExport}
            onDecision={onResolveDecision}
            disabled={isRunning}
          />
        </div>
      )}

      {pdfBase64 && (
        <div className="ml-9 max-w-[82%] rounded-2xl rounded-tl-sm border border-cyan-500/20 bg-cyan-950/20 px-4 py-3">
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl bg-cyan-500/15">
              <svg
                className="h-4 w-4 text-cyan-300"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M7 3h7l5 5v13H7z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M14 3v5h5M9 13h8M9 17h5" />
              </svg>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-white">PDF report ready</p>
              <p className="mt-1 text-xs text-slate-500">
                Preview it in a new tab or download the file.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  onClick={previewPdf}
                  className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-xs font-semibold text-cyan-200 transition-colors hover:bg-cyan-500/20"
                >
                  Preview PDF
                </button>
                <button
                  onClick={downloadPdf}
                  className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-semibold text-slate-200 transition-colors hover:bg-white/10"
                >
                  Download PDF
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {pptxBase64 && (
        <div className="ml-9 max-w-[82%] rounded-2xl rounded-tl-sm border border-orange-500/20 bg-orange-950/20 px-4 py-3">
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl bg-orange-500/15">
              <svg
                className="h-4 w-4 text-orange-300"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 4h16v16H4z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M8 8h8M8 12h5M8 16h3" />
              </svg>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-white">PPT proposal ready</p>
              <p className="mt-1 text-xs text-slate-500">
                Download the editable BnK PowerPoint deck.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  onClick={downloadPptx}
                  className="rounded-lg border border-orange-500/30 bg-orange-500/10 px-3 py-1.5 text-xs font-semibold text-orange-200 transition-colors hover:bg-orange-500/20"
                >
                  Download PPT
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {wbsXlsxBase64 && (
        <div className="ml-9 max-w-[82%] rounded-2xl rounded-tl-sm border border-emerald-500/20 bg-emerald-950/20 px-4 py-3">
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl bg-emerald-500/15">
              <svg
                className="h-4 w-4 text-emerald-300"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M9 17v-6h6v6M9 11V5h6v6M3 3h18v18H3z"
                />
              </svg>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-white">WBS Excel ready</p>
              <p className="mt-1 text-xs text-slate-500">
                Download the filled .xlsx file or preview effort breakdown.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  onClick={() => setWbsPreviewOpen((v) => !v)}
                  className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-200 transition-colors hover:bg-emerald-500/20"
                >
                  {wbsPreviewOpen ? "Hide Preview" : "Preview WBS"}
                </button>
                <button
                  onClick={downloadWbsXlsx}
                  className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-semibold text-slate-200 transition-colors hover:bg-white/10"
                >
                  Download .xlsx
                </button>
              </div>
              {wbsPreviewOpen && wbsSummary && (
                <div className="mt-3 space-y-3">
                  <div className="flex flex-wrap gap-2">
                    <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-300">
                      {fmtMd(wbsSummary.total_mandays)} MD
                    </span>
                    <span className="rounded-full border border-teal-500/30 bg-teal-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-teal-300">
                      {fmtMd(wbsSummary.total_manmonths)} MM
                    </span>
                    <span className="rounded-full border border-sky-500/30 bg-sky-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-sky-300">
                      {wbsSummary.months} months
                    </span>
                    <span className="rounded-full border border-slate-500/30 bg-slate-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-slate-300">
                      {wbsSummary.weeks} weeks
                    </span>
                  </div>
                  {Object.keys(wbsSummary.effort_by_role).length > 0 && (
                    <div>
                      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                        Effort by Role
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {Object.entries(wbsSummary.effort_by_role).map(([role, md]) => (
                          <span
                            key={role}
                            className="rounded border border-white/8 bg-white/5 px-2 py-0.5 text-[11px] text-slate-300"
                          >
                            <span className="font-semibold text-white">{role}</span> {fmtMd(md)} MD
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {wbsSummary.effort_by_module.length > 0 && (
                    <div>
                      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                        Effort by Module
                      </p>
                      <table className="w-full text-[11px]">
                        <tbody>
                          {wbsSummary.effort_by_module.map((m) => (
                            <tr key={m.code} className="border-b border-white/5">
                              <td className="py-0.5 pr-2 font-mono text-slate-500">{m.code}</td>
                              <td className="py-0.5 pr-2 text-slate-300">{m.name}</td>
                              <td className="py-0.5 text-right font-semibold text-emerald-300">
                                {fmtMd(m.total_md)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {lastMeeting && (
        <div className="ml-9 max-w-[82%] rounded-2xl rounded-tl-sm border border-violet-500/20 bg-violet-950/20 px-4 py-3">
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl bg-violet-500/15">
              <svg
                className="h-4 w-4 text-violet-300"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <rect x="3" y="5" width="14" height="14" rx="2" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M17 9.5l4-2.25v9.5l-4-2.25" />
              </svg>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-white">
                Meeting scheduled: {lastMeeting.title}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                {lastMeeting.attendee_name} &lt;{lastMeeting.attendee_email}&gt; ·{" "}
                {lastMeeting.timezone}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {lastMeeting.event_link && (
                  <a
                    href={lastMeeting.event_link}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-lg border border-violet-500/30 bg-violet-500/10 px-3 py-1.5 text-xs font-semibold text-violet-200 transition-colors hover:bg-violet-500/20"
                  >
                    Open Calendar Event
                  </a>
                )}
                {lastMeeting.meet_link && (
                  <a
                    href={lastMeeting.meet_link}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-semibold text-slate-200 transition-colors hover:bg-white/10"
                  >
                    Join Google Meet
                  </a>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {isRunning && !pendingInterrupt && (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <svg
            className="h-3.5 w-3.5 animate-spin text-blue-400 flex-shrink-0"
            viewBox="0 0 24 24"
            fill="none"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
            />
          </svg>
          {activeSubagent && (
            <span className="inline-flex items-center rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-300 flex-shrink-0">
              {activeSubagent}
            </span>
          )}
          <span className="truncate">{activity ?? "Thinking…"}</span>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-3 rounded-xl border border-red-500/20 bg-red-500/8 px-4 py-3">
          <svg
            className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-400"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
            />
          </svg>
          <p className="text-xs leading-relaxed text-red-300">{error}</p>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
