import { useEffect, useRef, useState } from "react";
import type { ChatMessage, PendingInterrupt, UploadedFile } from "../hooks/useDiagramAgent";
import TechStackApproval from "./TechStackApproval";
import BlueprintApproval from "./BlueprintApproval";
import DiagramFeedback from "./DiagramFeedback";
import PdfReportApproval from "./PdfReportApproval";
import FileUpload from "./FileUpload";

interface ChatSidebarProps {
  messages: ChatMessage[];
  pendingInterrupt: PendingInterrupt | null;
  isRunning: boolean;
  pdfBase64?: string;
  activity?: string | null;
  activeSubagent?: string | null;
  error: string | null;
  onSend: (content: string) => void;
  // HITL resolvers
  onResolveTechStack: (approved: boolean, modifications?: string) => void;
  onResolveBlueprint: (approved: boolean, modifications?: string) => void;
  onResolveResult: (satisfied: boolean, feedback?: string) => void;
  onResolvePdfReport: (approved: boolean, modifications?: string) => void;
  iteration?: number;
  // File upload
  uploadedFiles: UploadedFile[];
  isUploading: boolean;
  onUploadFile: (file: File) => void;
  onClearFiles: () => void;
}

export default function ChatSidebar({
  messages,
  pendingInterrupt,
  isRunning,
  pdfBase64,
  activity,
  activeSubagent,
  error,
  onSend,
  onResolveTechStack,
  onResolveBlueprint,
  onResolveResult,
  onResolvePdfReport,
  iteration,
  uploadedFiles,
  isUploading,
  onUploadFile,
  onClearFiles,
}: ChatSidebarProps) {
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, error, pendingInterrupt, pdfBase64]);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setDraft(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
  };

  const handleSend = () => {
    const trimmed = draft.trim();
    if (!trimmed || isRunning) return;
    setDraft("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    onSend(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const createPdfUrl = () => {
    if (!pdfBase64) return null;
    const bytes = Uint8Array.from(atob(pdfBase64), (char) => char.charCodeAt(0));
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
    a.href = url;
    a.download = "architecture_report.pdf";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <aside className="flex h-full w-full flex-col border-r border-white/8 bg-[#0c1015]">
      {/* Header */}
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

      {/* Messages */}
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

        {/* HITL gate cards — shown inline in chat */}
        {pendingInterrupt?.data.type === "techstack_approval" && (
          <div className="mt-1">
            <TechStackApproval interrupt={pendingInterrupt} onResolve={onResolveTechStack} disabled={isRunning} />
          </div>
        )}
        {pendingInterrupt?.data.type === "blueprint_approval" && (
          <div className="mt-1">
            <BlueprintApproval interrupt={pendingInterrupt} onResolve={onResolveBlueprint} disabled={isRunning} />
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
              disabled={isRunning}
            />
          </div>
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

        {/* Running indicator — shows the agent's current action live */}
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

        {/* Error */}
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

      {/* Input */}
      <div className="border-t border-white/8 px-4 py-4">
        {/* Requirement document upload */}
        <div className="mb-3">
          <FileUpload
            uploadedFiles={uploadedFiles}
            isUploading={isUploading}
            onUpload={onUploadFile}
            onClear={onClearFiles}
          />
        </div>

        <div className={`flex items-end gap-3 rounded-2xl border bg-white/4 px-4 py-3 transition-colors ${
          isRunning ? "border-white/5 opacity-60" : "border-white/10 focus-within:border-blue-500/40"
        }`}>
          <textarea
            ref={textareaRef}
            className="flex-1 resize-none bg-transparent text-sm leading-relaxed text-slate-200 placeholder:text-slate-700 focus:outline-none"
            rows={1}
            placeholder="Describe your architecture..."
            value={draft}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            disabled={isRunning}
          />
          <button
            className="mb-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white shadow-md transition-all hover:bg-blue-500 active:scale-95 disabled:cursor-not-allowed disabled:opacity-30"
            onClick={handleSend}
            disabled={!draft.trim() || isRunning}
            aria-label="Send"
          >
            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor">
              <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
            </svg>
          </button>
        </div>
        <p className="mt-2 px-1 text-[11px] text-slate-800">Enter to send · Shift+Enter for new line</p>
      </div>
    </aside>
  );
}
