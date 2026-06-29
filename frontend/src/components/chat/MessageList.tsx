import type { ChatMessage, DecisionPayload, PendingInterrupt, WbsSummary } from "../../hooks/useDiagramAgent";
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

interface MessageListProps {
  messages: ChatMessage[];
  pendingInterrupt: PendingInterrupt | null;
  isRunning: boolean;
  pdfBase64?: string;
  pptxBase64?: string;
  wbsXlsxBase64?: string;
  wbsSummary?: WbsSummary;
  activity?: string | null;
  activeSubagent?: string | null;
  error: string | null;
  iteration?: number;
  bottomRef: React.RefObject<HTMLDivElement | null>;
  onPreviewPdf: () => void;
  onDownloadPdf: () => void;
  onDownloadPptx: () => void;
  onDownloadWbsXlsx: () => void;
  wbsPreviewOpen: boolean;
  onToggleWbsPreview: () => void;
  onResolveTechStack: (approved: boolean, modifications?: string) => void;
  onResolveBlueprint: (approved: boolean, modifications?: string) => void;
  onResolveResult: (satisfied: boolean, feedback?: string) => void;
  onResolvePdfReport: (approved: boolean, modifications?: string) => void;
  onResolvePptProposal: (approved: boolean, modifications?: string) => void;
  onResolveEmail: (approved: boolean) => void;
  onResolveMeeting: (approved: boolean) => void;
  onResolveMeetingSlot: (approved: boolean, selectedSlot?: { start: string; end: string; display_day: string; display_time: string }) => void;
  onResolveWbsSkeleton: (approved: boolean, modifications?: string) => void;
  onResolveWbs: (approved: boolean, modifications?: string) => void;
  onResolveWbsExcel: (approved: boolean) => void;
  onResolveDecision: (payload: DecisionPayload) => void;
}

export default function MessageList({
  messages, pendingInterrupt, isRunning, pdfBase64, pptxBase64, wbsXlsxBase64, wbsSummary,
  activity, activeSubagent, error, iteration, bottomRef,
  onPreviewPdf, onDownloadPdf, onDownloadPptx, onDownloadWbsXlsx,
  wbsPreviewOpen, onToggleWbsPreview,
  onResolveTechStack, onResolveBlueprint, onResolveResult, onResolvePdfReport,
  onResolvePptProposal, onResolveEmail, onResolveMeeting, onResolveMeetingSlot,
  onResolveWbsSkeleton, onResolveWbs, onResolveWbsExcel, onResolveDecision,
}: MessageListProps) {
  return (
    <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-5 py-5">
      {messages.length === 0 && !isRunning && (
        <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-white/8 bg-white/4">
            <svg className="h-7 w-7 text-slate-700" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-medium text-slate-500">Describe your architecture</p>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-700">
              e.g. "Microservices with API gateway, auth service,<br />Postgres database, and Redis cache"
            </p>
          </div>
        </div>
      )}

      {messages.map((msg) => (
        <div key={msg.id} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
          {msg.role === "assistant" && (
            <div className="mt-1 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-blue-600/20">
              <svg className="h-3 w-3 text-blue-400" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z" />
              </svg>
            </div>
          )}
          <div className={`max-w-[82%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
            msg.role === "user"
              ? "rounded-tr-sm bg-blue-600 text-white shadow-lg shadow-blue-900/30"
              : "rounded-tl-sm border border-white/8 bg-white/5 text-slate-200"
          }`}>
            {msg.content || (
              <span className="inline-flex gap-1 text-slate-500">
                <span className="animate-bounce [animation-delay:0ms]">·</span>
                <span className="animate-bounce [animation-delay:150ms]">·</span>
                <span className="animate-bounce [animation-delay:300ms]">·</span>
              </span>
            )}
          </div>
        </div>
      ))}

      {/* HITL gate cards */}
      {pendingInterrupt?.data.type === "techstack_approval" && (
        <div className="mt-1"><TechStackApproval interrupt={pendingInterrupt} onResolve={onResolveTechStack} disabled={isRunning} /></div>
      )}
      {pendingInterrupt?.data.type === "blueprint_approval" && (
        <div className="mt-1"><BlueprintApproval interrupt={pendingInterrupt} onResolve={onResolveBlueprint} onDecision={onResolveDecision} disabled={isRunning} /></div>
      )}
      {pendingInterrupt?.data.type === "result_review" && (
        <div className="mt-1">
          <DiagramFeedback interrupt={pendingInterrupt} onResolve={onResolveResult} disabled={isRunning}
            iteration={iteration ?? pendingInterrupt.data.iteration ?? 1} />
        </div>
      )}
      {pendingInterrupt?.data.type === "pdf_report_approval" && (
        <div className="mt-1"><PdfReportApproval interrupt={pendingInterrupt} onResolve={onResolvePdfReport} disabled={isRunning} /></div>
      )}
      {pendingInterrupt?.data.type === "ppt_proposal_approval" && (
        <div className="mt-1"><PptProposalApproval interrupt={pendingInterrupt} onResolve={onResolvePptProposal} disabled={isRunning} /></div>
      )}
      {pendingInterrupt?.data.type === "email_approval" && (
        <div className="mt-1"><EmailApproval interrupt={pendingInterrupt} onResolve={onResolveEmail} disabled={isRunning} /></div>
      )}
      {pendingInterrupt?.data.type === "slot_picker" && (
        <div className="mt-1"><MeetingSlotPicker interrupt={pendingInterrupt} onResolve={onResolveMeetingSlot} disabled={isRunning} /></div>
      )}
      {pendingInterrupt?.data.type === "meeting_approval" && (
        <div className="mt-1"><MeetingApproval interrupt={pendingInterrupt} onResolve={onResolveMeeting} disabled={isRunning} /></div>
      )}
      {pendingInterrupt?.data.type === "wbs_skeleton_approval" && (
        <div className="mt-1"><WbsSkeletonApproval interrupt={pendingInterrupt} onResolve={onResolveWbsSkeleton} disabled={isRunning} /></div>
      )}
      {pendingInterrupt?.data.type === "wbs_approval" && (
        <div className="mt-1"><WbsApproval interrupt={pendingInterrupt} onResolve={onResolveWbs} disabled={isRunning} /></div>
      )}
      {pendingInterrupt?.data.type === "wbs_excel_approval" && (
        <div className="mt-1"><WbsExcelApproval interrupt={pendingInterrupt} onResolve={onResolveWbsExcel} disabled={isRunning} /></div>
      )}

      {pdfBase64 && (
        <div className="ml-9 max-w-[82%] rounded-2xl rounded-tl-sm border border-cyan-500/20 bg-cyan-950/20 px-4 py-3">
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl bg-cyan-500/15">
              <svg className="h-4 w-4 text-cyan-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path strokeLinecap="round" strokeLinejoin="round" d="M7 3h7l5 5v13H7z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M14 3v5h5M9 13h8M9 17h5" />
              </svg>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-white">PDF report ready</p>
              <p className="mt-1 text-xs text-slate-500">Preview it in a new tab or download the file.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button onClick={onPreviewPdf}
                  className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-xs font-semibold text-cyan-200 transition-colors hover:bg-cyan-500/20">
                  Preview PDF
                </button>
                <button onClick={onDownloadPdf}
                  className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-semibold text-slate-200 transition-colors hover:bg-white/10">
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
              <svg className="h-4 w-4 text-orange-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 4h16v16H4z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M8 8h8M8 12h5M8 16h3" />
              </svg>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-white">PPT proposal ready</p>
              <p className="mt-1 text-xs text-slate-500">Download the editable BnK PowerPoint deck.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button onClick={onDownloadPptx}
                  className="rounded-lg border border-orange-500/30 bg-orange-500/10 px-3 py-1.5 text-xs font-semibold text-orange-200 transition-colors hover:bg-orange-500/20">
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
              <svg className="h-4 w-4 text-emerald-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 17v-6h6v6M9 11V5h6v6M3 3h18v18H3z" />
              </svg>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-white">WBS Excel ready</p>
              <p className="mt-1 text-xs text-slate-500">Download the filled .xlsx file or preview effort breakdown.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button onClick={onToggleWbsPreview}
                  className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-200 transition-colors hover:bg-emerald-500/20">
                  {wbsPreviewOpen ? "Hide Preview" : "Preview WBS"}
                </button>
                <button onClick={onDownloadWbsXlsx}
                  className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-semibold text-slate-200 transition-colors hover:bg-white/10">
                  Download .xlsx
                </button>
              </div>
              {wbsPreviewOpen && wbsSummary && (
                <div className="mt-3 space-y-3">
                  <div className="flex flex-wrap gap-2">
                    <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-300">{wbsSummary.total_mandays.toFixed(1)} MD</span>
                    <span className="rounded-full border border-teal-500/30 bg-teal-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-teal-300">{wbsSummary.total_manmonths.toFixed(1)} MM</span>
                    <span className="rounded-full border border-sky-500/30 bg-sky-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-sky-300">{wbsSummary.months} months</span>
                    <span className="rounded-full border border-slate-500/30 bg-slate-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-slate-300">{wbsSummary.weeks} weeks</span>
                  </div>
                  {Object.keys(wbsSummary.effort_by_role).length > 0 && (
                    <div>
                      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Effort by Role</p>
                      <div className="flex flex-wrap gap-1.5">
                        {Object.entries(wbsSummary.effort_by_role).map(([role, md]) => (
                          <span key={role} className="rounded border border-white/8 bg-white/5 px-2 py-0.5 text-[11px] text-slate-300">
                            <span className="font-semibold text-white">{role}</span> {(md as number).toFixed(1)} MD
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {wbsSummary.effort_by_module.length > 0 && (
                    <div>
                      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Effort by Module</p>
                      <table className="w-full text-[11px]">
                        <tbody>
                          {wbsSummary.effort_by_module.map((m) => (
                            <tr key={m.code} className="border-b border-white/5">
                              <td className="py-0.5 pr-2 font-mono text-slate-500">{m.code}</td>
                              <td className="py-0.5 pr-2 text-slate-300">{m.name}</td>
                              <td className="py-0.5 text-right font-semibold text-emerald-300">{m.total_md.toFixed(1)}</td>
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

      {isRunning && !pendingInterrupt && (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <svg className="h-3.5 w-3.5 animate-spin text-blue-400 flex-shrink-0" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
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
          <svg className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          </svg>
          <p className="text-xs leading-relaxed text-red-300">{error}</p>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
