import { useEffect, useRef, useState } from "react";
import type { ChatMessage, DecisionPayload, PendingInterrupt, UploadedFile, WbsSummary } from "../hooks/useDiagramAgent";
import MessageList from "./chat/MessageList";
import ChatInput from "./chat/ChatInput";

interface ChatSidebarProps {
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
  uploadedFiles: UploadedFile[];
  isUploading: boolean;
  onSend: (content: string) => void;
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
  onUploadFile: (file: File) => void;
  onClearFiles: () => void;
}

export default function ChatSidebar({
  messages, pendingInterrupt, isRunning, pdfBase64, pptxBase64, wbsXlsxBase64, wbsSummary,
  activity, activeSubagent, error, iteration,
  uploadedFiles, isUploading,
  onSend, onResolveTechStack, onResolveBlueprint, onResolveResult, onResolvePdfReport,
  onResolvePptProposal, onResolveEmail, onResolveMeeting, onResolveMeetingSlot,
  onResolveWbsSkeleton, onResolveWbs, onResolveWbsExcel, onResolveDecision,
  onUploadFile, onClearFiles,
}: ChatSidebarProps) {
  const [wbsPreviewOpen, setWbsPreviewOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, error, pendingInterrupt, pdfBase64, pptxBase64, wbsXlsxBase64]);

  const createPdfUrl = () => {
    if (!pdfBase64) return null;
    const bytes = Uint8Array.from(atob(pdfBase64), (c) => c.charCodeAt(0));
    return URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
  };

  const previewPdf = () => {
    const url = createPdfUrl();
    if (!url) return;
    window.open(url, "_blank", "noopener,noreferrer");
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  };

  const downloadPdf = () => {
    const url = createPdfUrl();
    if (!url) return;
    const a = document.createElement("a");
    a.href = url; a.download = "architecture_report.pdf"; a.click();
    URL.revokeObjectURL(url);
  };

  const downloadWbsXlsx = () => {
    if (!wbsXlsxBase64) return;
    const bytes = Uint8Array.from(atob(wbsXlsxBase64), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
    const a = document.createElement("a");
    a.href = url; a.download = "wbs_filled.xlsx"; a.click();
    URL.revokeObjectURL(url);
  };

  const downloadPptx = () => {
    if (!pptxBase64) return;
    const bytes = Uint8Array.from(atob(pptxBase64), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.presentationml.presentation" }));
    const a = document.createElement("a");
    a.href = url; a.download = "architecture_proposal.pptx"; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <aside className="flex h-full w-full flex-col border-r border-white/8 bg-[#0c1015]">
      <div className="flex items-center justify-between border-b border-white/8 px-5 py-3.5">
        <div className="flex items-center gap-2">
          <svg className="h-4 w-4 text-slate-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
          <span className="text-xs font-semibold uppercase tracking-widest text-slate-600">Conversation</span>
        </div>
        {isRunning && (
          <span className="flex items-center gap-1.5 text-[11px] text-slate-600">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400" />
            thinking...
          </span>
        )}
      </div>

      <MessageList
        messages={messages}
        pendingInterrupt={pendingInterrupt}
        isRunning={isRunning}
        pdfBase64={pdfBase64}
        pptxBase64={pptxBase64}
        wbsXlsxBase64={wbsXlsxBase64}
        wbsSummary={wbsSummary}
        activity={activity}
        activeSubagent={activeSubagent}
        error={error}
        iteration={iteration}
        bottomRef={bottomRef}
        onPreviewPdf={previewPdf}
        onDownloadPdf={downloadPdf}
        onDownloadPptx={downloadPptx}
        onDownloadWbsXlsx={downloadWbsXlsx}
        wbsPreviewOpen={wbsPreviewOpen}
        onToggleWbsPreview={() => setWbsPreviewOpen((v) => !v)}
        onResolveTechStack={onResolveTechStack}
        onResolveBlueprint={onResolveBlueprint}
        onResolveResult={onResolveResult}
        onResolvePdfReport={onResolvePdfReport}
        onResolvePptProposal={onResolvePptProposal}
        onResolveEmail={onResolveEmail}
        onResolveMeeting={onResolveMeeting}
        onResolveMeetingSlot={onResolveMeetingSlot}
        onResolveWbsSkeleton={onResolveWbsSkeleton}
        onResolveWbs={onResolveWbs}
        onResolveWbsExcel={onResolveWbsExcel}
        onResolveDecision={onResolveDecision}
      />

      <ChatInput
        isRunning={isRunning}
        uploadedFiles={uploadedFiles}
        isUploading={isUploading}
        onSend={onSend}
        onUploadFile={onUploadFile}
        onClearFiles={onClearFiles}
      />
    </aside>
  );
}
