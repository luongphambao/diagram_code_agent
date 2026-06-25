import type { AgentState, PendingInterrupt } from "../hooks/useDiagramAgent";
import AgentStatus from "./AgentStatus";
import SubagentPanel from "./SubagentPanel";
import ArtifactTabs from "./canvas/ArtifactTabs";

interface DiagramCanvasProps {
  agentState: AgentState;
  pendingInterrupt: PendingInterrupt | null;
  isRunning: boolean;
  activeSubagent?: string | null;
  activity?: string | null;
}

export default function DiagramCanvas({ agentState, pendingInterrupt, isRunning, activeSubagent, activity }: DiagramCanvasProps) {
  const { current_step, png_base64, error, iteration, delegations, logs } = agentState;

  // Empty / idle
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

  // Diagram ready — delegate to ArtifactTabs
  if (png_base64) {
    return (
      <ArtifactTabs
        agentState={agentState}
        isRunning={isRunning}
        activeSubagent={activeSubagent}
        activity={activity}
      />
    );
  }

  // In-progress / waiting
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 overflow-y-auto bg-[#0f1117] p-10">
      {(isRunning || current_step) && (
        <AgentStatus
          step={current_step ?? (isRunning ? "planning" : "done")}
          iteration={iteration}
        />
      )}

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
