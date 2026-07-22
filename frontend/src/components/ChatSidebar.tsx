import { useAgentContext } from "../context/AgentContext";
import MessageList from "./chat/MessageList";
import ChatInput from "./chat/ChatInput";

export default function ChatSidebar() {
  const { isRunning, uploadedFiles, isUploading, sendMessage, uploadFile, clearFiles } =
    useAgentContext();

  return (
    <aside className="flex h-full w-full flex-col border-r border-white/8 bg-surface-panel">
      <div className="flex items-center justify-between border-b border-white/8 px-5 py-3.5">
        <div className="flex items-center gap-2">
          <svg
            className="h-4 w-4 text-slate-600"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
            />
          </svg>
          <span className="text-xs font-semibold uppercase tracking-widest text-slate-600">
            Conversation
          </span>
        </div>
        {isRunning && (
          <span className="flex items-center gap-1.5 text-[11px] text-slate-600">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400" />
            thinking...
          </span>
        )}
      </div>

      <MessageList />

      <ChatInput
        isRunning={isRunning}
        uploadedFiles={uploadedFiles}
        isUploading={isUploading}
        onSend={sendMessage}
        onUploadFile={uploadFile}
        onClearFiles={clearFiles}
      />
    </aside>
  );
}
