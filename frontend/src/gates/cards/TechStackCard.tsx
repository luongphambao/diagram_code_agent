import { useState } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import type { DecisionAction, DecisionPayload, SolutionAssumptions, TechStackLayer } from "../../hooks/agent-utils";
import GateFrame from "../GateFrame";
import DecisionBar from "../DecisionBar";
import LayerList from "../LayerList";
import Chip from "../../ui/Chip";
import Button from "../../ui/Button";
import { fmtUsd } from "../format";
import type { GateCardProps } from "../types";

/** Ported from components/TechStackApproval.tsx (plan §F) onto GateFrame +
 * DecisionBar + LayerList. Field order/emphasis preserved exactly — this is
 * a refactor onto shared primitives, not a redesign of what the gate says. */
export default function TechStackCard({ args, status, respond }: GateCardProps) {
  const [modifications, setModifications] = useState("");
  const [decided, setDecided] = useState(false);

  const techStack = (args.tech_stack as Record<string, TechStackLayer>) ?? {};
  const assumptions = args.assumptions as SolutionAssumptions | undefined;
  const scalingRoadmap = Array.isArray(args.scaling_roadmap) ? args.scaling_roadmap : [];
  const totalCost = args.estimated_total_monthly_cost_usd as { min_usd: number; max_usd: number } | undefined;
  const question = typeof args.question === "string" ? args.question : "Review the recommended tech stack.";
  const allowedDecisions = (args.allowed_decisions as DecisionAction[]) ?? [];
  const useDecisionMenu = allowedDecisions.some((a) => a !== "approve" && a !== "reject");
  const invalidProposal = Object.keys(techStack).length === 0;

  const assumptionChips: string[] = [];
  if (assumptions) {
    if (assumptions.project_phase) assumptionChips.push(assumptions.project_phase.toUpperCase());
    if (assumptions.monthly_budget_range_usd) assumptionChips.push(fmtUsd(assumptions.monthly_budget_range_usd) + " budget");
    if (assumptions.users?.mau) assumptionChips.push(`${(assumptions.users.mau / 1000).toFixed(0)}k MAU`);
    if (assumptions.users?.peak_concurrent) assumptionChips.push(`~${assumptions.users.peak_concurrent.toLocaleString()} concurrent`);
    if (assumptions.users?.peak_rps) assumptionChips.push(`~${assumptions.users.peak_rps} RPS`);
    if (assumptions.availability_target) assumptionChips.push(assumptions.availability_target);
    if (assumptions.latency_target_p99_ms) assumptionChips.push(`p99 ≤${assumptions.latency_target_p99_ms}ms`);
    if (assumptions.team) {
      const parts = [assumptions.team.size ? `Team ${assumptions.team.size}` : null, assumptions.team.skill_level || null].filter(Boolean);
      if (parts.length) assumptionChips.push(parts.join(" "));
    }
    if (assumptions.primary_region) assumptionChips.push(assumptions.primary_region);
    if (Array.isArray(assumptions.compliance) && assumptions.compliance.length) assumptionChips.push(...assumptions.compliance);
  }

  function decide(payload: DecisionPayload | Record<string, unknown>) {
    setDecided(true);
    void respond?.(payload);
  }

  const approve = () => decide({ action: "approve", approved: true, modifications: modifications.trim() || undefined });
  const reject = () => decide({ action: "reject", approved: false });

  if (decided && status === ToolCallStatus.Executing) {
    return (
      <GateFrame label="Tech Stack Recommendation" tone="decision" status={status}>
        <p className="text-xs text-muted">Response sent — designing architecture…</p>
      </GateFrame>
    );
  }

  return (
    <GateFrame label="Tech Stack Recommendation" tone="decision" status={status}>
      <p className="text-sm text-secondary">{question}</p>

      {invalidProposal && (
        <div className="rounded-sm border border-danger/30 bg-danger/10 px-3 py-2 text-xs leading-relaxed text-danger-text">
          This tech stack proposal is empty or malformed. Request regeneration instead of approving it.
        </div>
      )}

      {assumptions && (assumptionChips.length > 0 || (Array.isArray(assumptions.confirm_with_customer) && assumptions.confirm_with_customer.length > 0)) && (
        <div className="rounded-sm border border-line bg-well px-3 py-2.5">
          <p className="label-caps mb-2 text-2xs font-semibold text-muted">Design Assumptions</p>
          {assumptionChips.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {assumptionChips.map((chip, i) => (
                <Chip key={i} variant="info">
                  {chip}
                </Chip>
              ))}
            </div>
          )}
          {Array.isArray(assumptions.confirm_with_customer) && assumptions.confirm_with_customer.length > 0 && (
            <div className="mt-2.5">
              <p className="mb-1 text-2xs font-semibold text-warn-text">Confirm with customer</p>
              <ul className="space-y-0.5">
                {assumptions.confirm_with_customer.map((item, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-2xs leading-relaxed text-warn-text">
                    <span className="mt-1 shrink-0">•</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <LayerList techStack={techStack} />

      {(totalCost || scalingRoadmap.length > 0) && (
        <div className="rounded-sm border border-line bg-well px-3 py-2.5">
          {totalCost && (
            <p className="text-xs font-semibold text-secondary">
              Estimated total: <span className="text-accent-text">{fmtUsd(totalCost)}</span>
              <span className="ml-1 text-2xs font-normal text-muted">(assumption-based, infra only)</span>
            </p>
          )}
          {scalingRoadmap.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-2xs font-semibold uppercase tracking-widest text-muted hover:text-secondary">
                Scaling roadmap
              </summary>
              <div className="mt-2 space-y-2">
                {scalingRoadmap.map((phase, i) => (
                  <div key={i} className="text-2xs leading-relaxed">
                    <span className="font-semibold text-secondary">{phase.phase}</span>
                    {phase.trigger && <span className="ml-2 text-muted">when: {phase.trigger}</span>}
                    {phase.est_monthly_cost_usd && <span className="ml-2 text-muted">{fmtUsd(phase.est_monthly_cost_usd)}</span>}
                    {Array.isArray(phase.changes) && phase.changes.length > 0 && (
                      <p className="mt-0.5 text-muted">{phase.changes.join(", ")}</p>
                    )}
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}

      {invalidProposal ? (
        <Button
          variant="danger"
          size="sm"
          onClick={() => decide({ action: "reject", approved: false, modifications: "The tech stack proposal was empty or malformed. Regenerate it with concrete layers." })}
        >
          Regenerate stack
        </Button>
      ) : useDecisionMenu ? (
        <DecisionBar
          allowedDecisions={allowedDecisions}
          approveLabel="Approve Stack"
          onApprove={approve}
          onReject={(t) => decide({ action: "reject", approved: false, modifications: t || undefined })}
          onDecision={decide}
        />
      ) : (
        <>
          <label className="block text-xs font-medium text-muted">
            Suggest changes (optional)
            <textarea
              className="mt-1.5 w-full resize-none rounded-sm border border-line bg-app px-3 py-2.5 text-xs leading-relaxed text-fg placeholder:text-muted focus:border-accent-hi focus:outline-none"
              rows={2}
              placeholder="e.g. Replace MongoDB with PostgreSQL for the data layer..."
              value={modifications}
              onChange={(e) => setModifications(e.target.value)}
            />
          </label>
          <div className="flex gap-2.5">
            <Button variant="primary" size="md" onClick={approve} className="flex-1">
              Approve Stack
            </Button>
            <Button variant="secondary" size="md" onClick={reject}>
              Reject
            </Button>
          </div>
        </>
      )}
    </GateFrame>
  );
}
