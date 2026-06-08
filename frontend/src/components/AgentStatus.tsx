interface AgentStatusProps {
  step: string;
  iteration?: number;
}

const LABELS: Record<string, string> = {
  // Diagram agent
  planning: "Planning diagram structure...",
  awaiting_approval: "Waiting for your approval...",
  generating: "Generating diagram (1–3 min)...",
  reviewing: "Reviewing generated diagram...",
  regenerating: "Regenerating with your feedback...",
  done: "Done!",
  cancelled: "Generation cancelled.",
  error: "An error occurred.",
  // SA agent
  extracting: "Reading and extracting requirements...",
  analyzing_gaps: "Analyzing information gaps...",
  clarifying: "Waiting for your answers...",
  recommending: "Researching and recommending tech stack...",
  awaiting_techstack: "Waiting for tech stack approval...",
  designing: "Designing architecture blueprint...",
  awaiting_blueprint: "Waiting for blueprint approval...",
  synthesizing: "Finalizing architecture...",
};

const SPINNING = new Set([
  "planning", "generating", "regenerating", "reviewing",
  "extracting", "analyzing_gaps", "recommending", "designing", "synthesizing",
]);

export default function AgentStatus({ step, iteration }: AgentStatusProps) {
  const label = LABELS[step] ?? `Step: ${step}`;
  const spinning = SPINNING.has(step);

  return (
    <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-slate-300 shadow-lg backdrop-blur-sm">
      {spinning ? (
        <svg className="h-4 w-4 animate-spin text-blue-400" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
        </svg>
      ) : step === "done" ? (
        <svg className="h-4 w-4 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      ) : (
        <svg className="h-4 w-4 text-red-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      )}
      <span>{label}</span>
      {iteration && iteration > 1 && (
        <span className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] text-slate-500">
          Iteration {iteration}
        </span>
      )}
    </div>
  );
}
