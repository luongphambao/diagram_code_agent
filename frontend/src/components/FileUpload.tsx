import { useRef } from "react";
import type { UploadedFile } from "../hooks/agent-utils";
import Chip from "../ui/Chip";

interface FileUploadProps {
  uploadedFiles: UploadedFile[];
  isUploading: boolean;
  onUpload: (file: File) => void;
  onClear: () => void;
}

const ACCEPTED = ".pdf,.docx,.doc,.md,.txt";

export default function FileUpload({ uploadedFiles, isUploading, onUpload, onClear }: FileUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    Array.from(e.dataTransfer.files).forEach(onUpload);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    Array.from(e.target.files ?? []).forEach(onUpload);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="flex flex-col gap-2">
      {/* Drop zone — role="button"+tabIndex+onKeyDown so it's reachable and
          operable without a mouse (plan §D.7/§E.6: "dropzone is click-only"
          was a real a11y gap, not just cosmetic). */}
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload a requirements document (PDF, DOCX, or text)"
        onDrop={handleDrop}
        onDragOver={(e) => e.preventDefault()}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        className="flex cursor-pointer flex-col items-center gap-2 rounded-sm border border-dashed border-line bg-well px-4 py-3 transition-colors hover:border-accent-hi/50 hover:bg-app"
      >
        <input ref={inputRef} type="file" accept={ACCEPTED} multiple onChange={handleChange} className="hidden" tabIndex={-1} />
        {isUploading ? (
          <div className="flex items-center gap-2">
            <svg className="h-3.5 w-3.5 animate-spin text-accent" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
            </svg>
            <span className="text-xs text-secondary">Uploading…</span>
          </div>
        ) : (
          <>
            <svg className="h-5 w-5 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
              />
            </svg>
            <p className="text-xs text-muted">
              Drop PDF/DOCX/TXT or <span className="font-medium text-accent-text underline-offset-2 hover:underline">click to browse</span>
            </p>
          </>
        )}
      </div>

      {/* Uploaded file pills */}
      {uploadedFiles.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {uploadedFiles.map((f) => (
            <div key={f.file_id} className="flex items-center gap-2 rounded-sm border border-line bg-well px-3 py-2">
              <svg className="h-3.5 w-3.5 flex-shrink-0 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
                />
              </svg>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-fg">{f.filename}</p>
                <p className="text-2xs text-muted">
                  {f.kind.toUpperCase()} · {f.char_count.toLocaleString()} chars
                </p>
              </div>
              <Chip variant="ok">ready</Chip>
            </div>
          ))}
          <button onClick={onClear} className="self-end text-2xs text-muted hover:text-secondary">
            Clear files
          </button>
        </div>
      )}
    </div>
  );
}
