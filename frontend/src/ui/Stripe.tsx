export type Severity = "neutral" | "accent" | "ok" | "warn" | "danger" | "info";

const SEVERITY_BG: Record<Severity, string> = {
  neutral: "bg-line",
  accent: "bg-accent",
  ok: "bg-ok",
  warn: "bg-warn",
  danger: "bg-danger",
  info: "bg-info",
};

/**
 * A 2px severity stripe — the recurring "instrument label plate" motif that
 * replaces the old app's accent-rail-on-rounded-card pattern (plan §C.1).
 * Used on the left edge of gate cards (tone) and metric tiles (severity).
 */
export default function Stripe({
  severity = "neutral",
  className = "",
}: {
  severity?: Severity;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={`absolute inset-y-0 left-0 w-0.5 rounded-full ${SEVERITY_BG[severity]} ${className}`}
    />
  );
}
