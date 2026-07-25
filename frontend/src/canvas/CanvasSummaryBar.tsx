import type { AgentState } from "../hooks/agent-utils";
import { fmtMd } from "../hooks/agent-utils";
import MetricTile from "../ui/MetricTile";
import type { Severity } from "../ui/Stripe";

/** "Summary before detail" (plan §D.7/§G): iteration/quality/findings/mandays
 * as scannable tiles above the tab bar. Tiles with no data render an em-dash
 * (MetricTile's own behavior) rather than disappearing, so the bar's
 * geometry stays stable turn over turn. */
export default function CanvasSummaryBar({
  agentState,
  onSelectTab,
}: {
  agentState: AgentState;
  onSelectTab: (tab: string) => void;
}) {
  const { iteration, quality, wbs_summary } = agentState;
  const qualityScore = quality?.quality_score;
  const openFindings = quality?.findings_open;
  const mandays = wbs_summary?.total_mandays;

  const qualitySeverity: Severity = qualityScore == null ? "neutral" : qualityScore >= 80 ? "ok" : qualityScore >= 60 ? "warn" : "danger";
  const findingsSeverity: Severity = openFindings == null ? "neutral" : openFindings > 0 ? "warn" : "ok";

  return (
    <div className="flex items-stretch divide-x divide-line border-b border-line bg-raised px-3">
      <MetricTile label="Iteration" value={iteration ?? null} />
      <MetricTile
        label="Quality"
        value={qualityScore ?? null}
        suffix={qualityScore != null ? "/100" : undefined}
        severity={qualitySeverity}
        onClick={quality ? () => onSelectTab("quality") : undefined}
      />
      <MetricTile
        label="Open Findings"
        value={openFindings ?? null}
        severity={findingsSeverity}
        onClick={quality ? () => onSelectTab("quality") : undefined}
      />
      <MetricTile label="Mandays" value={mandays != null ? fmtMd(mandays) : null} onClick={wbs_summary ? () => onSelectTab("wbs") : undefined} />
    </div>
  );
}
