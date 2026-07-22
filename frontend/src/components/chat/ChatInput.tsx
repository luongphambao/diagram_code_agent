import { useRef, useState } from "react";
import type { UploadedFile } from "../../hooks/useDiagramAgent";
import FileUpload from "../FileUpload";

interface ChatInputProps {
  isRunning: boolean;
  uploadedFiles: UploadedFile[];
  isUploading: boolean;
  onSend: (content: string) => void;
  onUploadFile: (file: File) => void;
  onClearFiles: () => void;
}

export default function ChatInput({
  isRunning,
  uploadedFiles,
  isUploading,
  onSend,
  onUploadFile,
  onClearFiles,
}: ChatInputProps) {
  const [draft, setDraft] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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

  return (
    <div className="border-t border-white/8 px-4 py-4">
      <div className="mb-3">
        <FileUpload
          uploadedFiles={uploadedFiles}
          isUploading={isUploading}
          onUpload={onUploadFile}
          onClear={onClearFiles}
        />
      </div>
      <div
        className={`flex items-end gap-3 rounded-2xl border bg-white/4 px-4 py-3 transition-colors ${
          isRunning
            ? "border-white/5 opacity-60"
            : "border-white/10 focus-within:border-blue-500/40"
        }`}
      >
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
      <p className="mt-2 px-1 text-[11px] text-slate-800">
        Enter to send · Shift+Enter for new line
      </p>
    </div>
  );
}
