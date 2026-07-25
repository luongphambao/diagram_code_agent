import { useState } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import type { DecisionAction } from "../../hooks/agent-utils";
import GateFrame from "../GateFrame";
import DecisionBar from "../DecisionBar";
import KeyValueGrid from "../KeyValueGrid";
import Chip from "../../ui/Chip";
import Button from "../../ui/Button";
import type { GateCardProps } from "../types";

const SECTION_LABELS: Record<string, string> = {
  cover: "Cover",
  executive_summary: "Executive Summary",
  solution_overview: "Solution Overview",
  scope: "Scope",
  architecture_diagram: "Architecture Diagram",
  technical_stack: "Technical Stack",
  key_decisions: "Key Decisions",
  delivery_plan: "Delivery Plan",
  risks: "Risks",
  appendix: "Appendix",
};

/** Ported from components/PptProposalApproval.tsx (plan §F). */
export default function PptProposalCard({ args, status, respond }: GateCardProps) {
  const [mode, setMode] = useState<"idle" | "feedback">("idle");
  const [modifications, setModifications] = useState("");
  const [decided, setDecided] = useState(false);

  const allowedDecisions = (args.allowed_decisions as DecisionAction[]) ?? [];
  const useDecisionMenu = allowedDecisions.some((a) => a !== "approve" && a !== "reject");
  const title = (typeof args.title === "string" && args.title.trim()) || "Architecture Proposal";
  const subtitle = (typeof args.subtitle === "string" && args.subtitle.trim()) || "BnK PowerPoint Proposal";
  const brand = typeof args.brand === "string" ? args.brand.trim() : "";
  const sections = (Array.isArray(args.include_sections) && args.include_sections.length ? args.include_sections : []) as string[];
  const missingSections = (Array.isArray(args.missing_sections) ? args.missing_sections : []) as string[];

  function decide(payload: Record<string, unknown>) {
    setDecided(true);
    void respond?.(payload);
  }
  const approve = () => decide({ action: "approve", approved: true });
  const requestChanges = () => {
    if (!modifications.trim()) return;
    decide({ action: "reject", approved: false, modifications: modifications.trim() });
  };

  if (decided && status === ToolCallStatus.Executing) {
    return (
      <GateFrame label="PPT Proposal" tone="export" status={status}>
        <p className="text-xs text-muted">{mode === "feedback" ? "Feedback sent — updating proposal settings…" : "Approved — generating PPT…"}</p>
      </GateFrame>
    );
  }

  return (
    <GateFrame label="PPT Proposal" tone="export" status={status} badge={<Chip variant="info" numeric>{sections.length} sections</Chip>}>
      {mode === "idle" ? (
        <>
          <p className="text-sm text-secondary">{typeof args.question === "string" ? args.question : "Generate the BnK PowerPoint proposal?"}</p>
          <KeyValueGrid items={[{ label: "Title", value: title }, { label: "Subtitle", value: subtitle }, { label: "Brand", value: brand }]} />
          <div>
            <p className="label-caps mb-1.5 text-2xs font-semibold text-info-text">Included Sections</p>
            <div className="flex flex-wrap gap-1.5">
              {sections.map((s) => (
                <Chip key={s} variant="neutral">
                  {SECTION_LABELS[s] ?? s}
                </Chip>
              ))}
            </div>
          </div>
          {missingSections.length > 0 && (
            <div className="rounded-sm border border-warn/30 bg-warn/10 px-3 py-2.5">
              <p className="text-xs font-semibold text-warn-text">
                {missingSections.length} section{missingSections.length > 1 ? "s" : ""} will be missing from this PPT
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {missingSections.map((s) => (
                  <Chip key={s} variant="warn">
                    {SECTION_LABELS[s] ?? s}
                  </Chip>
                ))}
              </div>
            </div>
          )}
          {useDecisionMenu ? (
            <DecisionBar
              allowedDecisions={allowedDecisions}
              approveLabel="Generate PPT"
              onApprove={approve}
              onReject={(t) => decide({ action: "reject", approved: false, modifications: t || undefined })}
              onDecision={decide}
            />
          ) : (
            <div className="flex gap-2.5">
              <Button variant="primary" size="md" onClick={approve} className="flex-1">
                Generate PPT
              </Button>
              <Button variant="secondary" size="md" onClick={() => setMode("feedback")}>
                Change settings
              </Button>
            </div>
          )}
        </>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <button onClick={() => setMode("idle")} className="text-xs text-muted hover:text-secondary">
              ← Back
            </button>
            <p className="text-xs text-secondary">What should change in the proposal?</p>
          </div>
          <textarea
            className="w-full resize-none rounded-sm border border-line bg-app px-3 py-2.5 text-xs leading-relaxed text-fg placeholder:text-muted focus:border-accent-hi focus:outline-none"
            rows={3}
            placeholder="e.g. Change the cover title, remove delivery plan, or use Vietnamese wording..."
            value={modifications}
            onChange={(e) => setModifications(e.target.value)}
            autoFocus
          />
          <Button variant="primary" size="md" onClick={requestChanges} disabled={!modifications.trim()}>
            Send proposal changes
          </Button>
        </>
      )}
    </GateFrame>
  );
}
