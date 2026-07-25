import { useState } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import type { DecisionAction } from "../../hooks/agent-utils";
import GateFrame from "../GateFrame";
import DecisionBar from "../DecisionBar";
import KeyValueGrid from "../KeyValueGrid";
import Chip from "../../ui/Chip";
import { fmtUsdFlat } from "../format";
import type { GateCardProps } from "../types";

interface CashFlowYear {
  year: number;
  net_cash_flow_usd: number;
  cumulative_usd: number;
}

interface ComputedBusinessCase {
  cash_flow_by_year?: CashFlowYear[];
  total_cost_usd?: number;
  total_benefit_usd?: number;
  net_benefit_usd?: number;
  roi_pct?: number | null;
  payback_period_years?: number | null;
}

/**
 * New card (plan §F: "business_case_approval added — in the backend's card
 * types with no component today"). Renders the deterministic ROI/TCO/
 * payback figures from domain/reporting/business_case.py::compute_business_case
 * — never the model's own prose claim about them (same discipline as
 * TechStackCard's server-summed total cost).
 */
export default function BusinessCaseCard({ args, status, respond }: GateCardProps) {
  const [decided, setDecided] = useState(false);

  const allowedDecisions = (args.allowed_decisions as DecisionAction[]) ?? [];
  const benefitBasis = typeof args.benefit_basis === "string" ? args.benefit_basis : "";
  const implCost = typeof args.implementation_cost_usd === "number" ? args.implementation_cost_usd : null;
  const implSource = typeof args.implementation_cost_source === "string" ? args.implementation_cost_source : "";
  const opCost = typeof args.annual_operating_cost_usd === "number" ? args.annual_operating_cost_usd : null;
  const opSource = typeof args.annual_operating_cost_source === "string" ? args.annual_operating_cost_source : "";
  const annualBenefit = typeof args.annual_benefit_usd === "number" ? args.annual_benefit_usd : null;
  const horizon = typeof args.analysis_horizon_years === "number" ? args.analysis_horizon_years : 3;
  const computed = (args.computed ?? null) as ComputedBusinessCase | null;

  function decide(payload: Record<string, unknown>) {
    setDecided(true);
    void respond?.(payload);
  }
  const approve = () => decide({ action: "approve", approved: true });

  if (decided && status === ToolCallStatus.Executing) {
    return (
      <GateFrame label="Business Case" tone="decision" status={status}>
        <p className="text-xs text-muted">Response sent — continuing…</p>
      </GateFrame>
    );
  }

  return (
    <GateFrame label="Business Case" tone="decision" status={status}>
      <p className="text-sm text-secondary">
        {typeof args.question === "string" ? args.question : "Review the business case (ROI/TCO/payback)."}
      </p>

      {computed && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div className="rounded-sm border border-line bg-well px-2.5 py-2">
            <p className="label-caps text-2xs text-muted">ROI</p>
            <p className="tnum text-lg font-semibold text-accent-text">
              {computed.roi_pct != null ? `${computed.roi_pct}%` : "—"}
            </p>
          </div>
          <div className="rounded-sm border border-line bg-well px-2.5 py-2">
            <p className="label-caps text-2xs text-muted">Payback</p>
            <p className="tnum text-lg font-semibold text-fg">
              {computed.payback_period_years != null ? `${computed.payback_period_years}y` : "Never"}
            </p>
          </div>
          <div className="rounded-sm border border-line bg-well px-2.5 py-2">
            <p className="label-caps text-2xs text-muted">Total Cost</p>
            <p className="tnum text-lg font-semibold text-fg">{fmtUsdFlat(computed.total_cost_usd)}</p>
          </div>
          <div className="rounded-sm border border-line bg-well px-2.5 py-2">
            <p className="label-caps text-2xs text-muted">Net Benefit</p>
            <p className={`tnum text-lg font-semibold ${(computed.net_benefit_usd ?? 0) >= 0 ? "text-ok-text" : "text-danger-text"}`}>
              {fmtUsdFlat(computed.net_benefit_usd)}
            </p>
          </div>
        </div>
      )}

      <KeyValueGrid
        items={[
          { label: "Benefit basis", value: benefitBasis },
          { label: "Implementation cost", value: implCost != null ? `${fmtUsdFlat(implCost)} (${implSource})` : "" },
          { label: "Annual operating cost", value: opCost != null ? `${fmtUsdFlat(opCost)} (${opSource})` : "" },
          { label: "Annual benefit", value: annualBenefit != null ? fmtUsdFlat(annualBenefit) : "" },
          { label: "Horizon", value: `${horizon} years` },
        ]}
      />

      {computed?.cash_flow_by_year && computed.cash_flow_by_year.length > 0 && (
        <details>
          <summary className="cursor-pointer text-2xs font-semibold uppercase tracking-widest text-muted hover:text-secondary">
            Cash flow by year
          </summary>
          <table className="mt-2 w-full text-xs">
            <thead>
              <tr className="border-b border-line text-left">
                <th className="px-2 py-1 font-semibold text-muted">Year</th>
                <th className="px-2 py-1 text-right font-semibold text-muted">Net</th>
                <th className="px-2 py-1 text-right font-semibold text-muted">Cumulative</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {computed.cash_flow_by_year.map((row) => (
                <tr key={row.year}>
                  <td className="px-2 py-1 tnum text-secondary">Y{row.year}</td>
                  <td className="px-2 py-1 text-right tnum text-secondary">{fmtUsdFlat(row.net_cash_flow_usd)}</td>
                  <td className={`px-2 py-1 text-right tnum ${row.cumulative_usd >= 0 ? "text-ok-text" : "text-danger-text"}`}>
                    {fmtUsdFlat(row.cumulative_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {implCost == null && (
        <div className="rounded-sm border border-warn/30 bg-warn/10 px-3 py-2">
          <Chip variant="warn">No implementation cost could be computed — figures below are incomplete.</Chip>
        </div>
      )}

      <DecisionBar allowedDecisions={allowedDecisions} approveLabel="Approve Business Case" onApprove={approve} onReject={(t) => decide({ action: "reject", approved: false, comment: t })} onDecision={decide} />
    </GateFrame>
  );
}
