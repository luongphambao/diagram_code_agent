import { useState } from "react";
import type { PendingInterrupt, DecisionPayload } from "../hooks/useDiagramAgent";
import DecisionActions from "./DecisionActions";

interface PdfReportApprovalProps {
  interrupt: PendingInterrupt;
  onResolve: (approved: boolean, modifications?: string) => void;
  onDecision?: (payload: DecisionPayload) => void;
  disabled?: boolean;
}

const SECTION_LABELS: Record<string, string> = {
  cover: "Cover",
  executive_summary: "Executive Summary",
  requirements_analysis: "Requirements Analysis",
  traceability: "Traceability",
  solution: "Solution",
  techstack: "Tech Stack",
  architecture_analysis: "Architecture Blueprint",
  step_results: "Step Results",
  risks: "Risks",
  blueprint: "Blueprint",
  diagram: "Diagram",
};

const DEFAULT_REPORT_SECTIONS = [
  "cover",
  "executive_summary",
  "requirements_analysis",
  "traceability",
  "solution",
  "techstack",
  "architecture_analysis",
  "step_results",
  "risks",
  "diagram",
];

export default function PdfReportApproval({
  interrupt,
  onResolve,
  onDecision,
  disabled = false,
}: PdfReportApprovalProps) {
  const [mode, setMode] = useState<"idle" | "feedback">("idle");
  const [modifications, setModifications] = useState("");
  const [decided, setDecided] = useState(false);

  const allowedDecisions = interrupt.data.allowed_decisions ?? [];
  const useDecisionMenu =
    onDecision != null && allowedDecisions.some((a: string) => a !== "approve" && a !== "reject");

  const title = interrupt.data.title?.trim() || "Architecture Blueprint";
  const subtitle = interrupt.data.subtitle?.trim() || "Architecture Report";
  const brand = interrupt.data.brand?.trim();
  const sections = interrupt.data.include_sections?.length
    ? interrupt.data.include_sections
    : DEFAULT_REPORT_SECTIONS;
  const missingSections: string[] = interrupt.data.missing_sections ?? [];

  const approve = () => {
    setDecided(true);
    onResolve(true);
  };

  const requestChanges = () => {
    if (!modifications.trim()) return;
    setDecided(true);
    onResolve(false, modifications.trim());
  };

  return (
    <div className="flex w-full flex-col overflow-hidden rounded-2xl border border-cyan-500/20 bg-cyan-950/15">
      <div className="flex items-center gap-2.5 border-b border-white/8 bg-white/4 px-4 py-3">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-cyan-500/20">
          <svg
            className="h-3.5 w-3.5 text-cyan-300"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M7 3h7l5 5v13H7z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M14 3v5h5M9 13h8M9 17h5" />
          </svg>
        </div>
        <p className="flex-1 text-sm font-semibold text-white">PDF Report</p>
        <span className="rounded-full border border-cyan-500/25 bg-cyan-500/10 px-2 py-0.5 text-[11px] font-medium text-cyan-300">
          {sections.length} sections
        </span>
      </div>

      {decided ? (
        <div className="px-4 py-3">
          <p className="text-xs text-slate-600">
            {mode === "feedback"
              ? "Feedback sent - updating report settings..."
              : "Approved - generating PDF..."}
          </p>
        </div>
      ) : mode === "idle" ? (
        <div className="flex flex-col gap-3 px-4 py-4">
          <p className="text-xs leading-relaxed text-slate-400">{interrupt.data.question}</p>
          <div className="rounded-xl border border-white/8 bg-white/4 px-3 py-3">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-cyan-300/70">
              Title
            </p>
            <p className="mt-1 text-sm font-semibold text-slate-100">{title}</p>
            <p className="mt-1 text-xs text-slate-500">{subtitle}</p>
            {brand && <p className="mt-1 text-xs text-slate-600">Brand: {brand}</p>}
          </div>
          <div>
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-cyan-300/70">
              Included Sections
            </p>
            <div className="flex flex-wrap gap-1.5">
              {sections.map((section) => (
                <span
                  key={section}
                  className="rounded-md border border-white/8 bg-black/25 px-2 py-1 text-[11px] text-slate-300"
                >
                  {SECTION_LABELS[section] ?? section}
                </span>
              ))}
            </div>
          </div>
          {missingSections.length > 0 && (
            <div className="rounded-xl border border-yellow-500/30 bg-yellow-500/8 px-3 py-2.5">
              <p className="text-[11px] font-semibold text-yellow-300">
                ⚠ {missingSections.length} section{missingSections.length > 1 ? "s" : ""} will be
                missing from this PDF
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {missingSections.map((s) => (
                  <span
                    key={s}
                    className="rounded border border-yellow-500/25 bg-yellow-500/10 px-1.5 py-0.5 text-[10px] text-yellow-400"
                  >
                    {SECTION_LABELS[s] ?? s}
                  </span>
                ))}
              </div>
              <p className="mt-1.5 text-[10px] text-yellow-300/60">
                Reject and ask the agent to call generate_pdf_report with no arguments to include
                all sections.
              </p>
            </div>
          )}
          {useDecisionMenu ? (
            <DecisionActions
              allowedDecisions={allowedDecisions}
              disabled={disabled}
              approveLabel="Generate PDF"
              onApprove={approve}
              onReject={(t) => {
                setDecided(true);
                onResolve(false, t || undefined);
              }}
              onDecision={onDecision!}
            />
          ) : (
            <div className="flex gap-2.5">
              <button
                onClick={approve}
                disabled={disabled}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-cyan-700 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-cyan-900/30 transition-all hover:bg-cyan-600 active:scale-98 disabled:opacity-50"
              >
                <svg
                  className="h-3.5 w-3.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                Generate PDF
              </button>
              <button
                onClick={() => setMode("feedback")}
                disabled={disabled}
                className="rounded-xl border border-white/10 bg-white/4 px-4 py-2.5 text-xs font-semibold text-slate-300 transition-all hover:bg-white/8 disabled:opacity-50"
              >
                Change settings
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-3 px-4 py-4">
          <div className="flex items-center gap-2">
            <button onClick={() => setMode("idle")} className="text-slate-600 hover:text-slate-400">
              Back
            </button>
            <p className="text-xs text-slate-500">What should change in the report?</p>
          </div>
          <textarea
            className="w-full resize-none rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-xs leading-relaxed text-slate-200 placeholder:text-slate-700 focus:border-cyan-500/40 focus:outline-none"
            rows={3}
            placeholder="e.g. Use the client name as brand, remove the tech stack page, or change the report title..."
            value={modifications}
            onChange={(e) => setModifications(e.target.value)}
            disabled={disabled}
            autoFocus
          />
          <button
            onClick={requestChanges}
            disabled={disabled || !modifications.trim()}
            className="rounded-xl bg-cyan-700 px-4 py-2.5 text-xs font-semibold text-white transition-all hover:bg-cyan-600 disabled:opacity-40"
          >
            Send report changes
          </button>
        </div>
      )}
    </div>
  );
}
