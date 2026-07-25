import type { ReactNode } from "react";
import Stripe, { type Severity } from "./Stripe";

/**
 * "Summary before detail" (plan §D.7): a single scannable number with a 2xs
 * uppercase label and a severity stripe. Tiles with no data render an em-dash
 * rather than disappearing — the bar's geometry stays stable and the absence
 * is itself information. Clickable tiles (onClick set) get hover + a real
 * button role so they read as interactive.
 */
export default function MetricTile({
  label,
  value,
  suffix,
  severity = "neutral",
  onClick,
}: {
  label: string;
  value: ReactNode | null | undefined;
  suffix?: string;
  severity?: Severity;
  onClick?: () => void;
}) {
  const hasValue = value !== null && value !== undefined && value !== "";
  const content = (
    <>
      <Stripe severity={hasValue ? severity : "neutral"} />
      <div className="pl-3">
        <div className="label-caps text-2xs text-muted">{label}</div>
        <div className="tnum mt-0.5 text-xl font-semibold leading-none text-fg">
          {hasValue ? value : <span className="text-muted">—</span>}
          {hasValue && suffix ? <span className="ml-1 text-xs font-normal text-secondary">{suffix}</span> : null}
        </div>
      </div>
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className="relative flex-1 rounded-sm py-1.5 pr-3 text-left transition-colors hover:bg-well"
      >
        {content}
      </button>
    );
  }

  return <div className="relative flex-1 py-1.5 pr-3">{content}</div>;
}
