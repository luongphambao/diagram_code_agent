import type { ReactNode } from "react";

export type ChipVariant = "neutral" | "accent" | "ok" | "warn" | "danger" | "info";

const VARIANT_CLASSES: Record<ChipVariant, string> = {
  neutral: "border-line bg-well text-secondary",
  accent: "border-accent/30 bg-accent/10 text-accent-text",
  ok: "border-ok/30 bg-ok/10 text-ok-text",
  warn: "border-warn/30 bg-warn/10 text-warn-text",
  danger: "border-danger/30 bg-danger/10 text-danger-text",
  info: "border-info/30 bg-info/10 text-info-text",
};

/**
 * The small pill primitive replacing ~9 bespoke pill spans across the old
 * components (plan §F.5). `numeric` applies `.tnum` — pass it whenever the
 * content is a count so digits stay aligned across renders.
 */
export default function Chip({
  variant = "neutral",
  numeric = false,
  className = "",
  children,
  ...rest
}: {
  variant?: ChipVariant;
  numeric?: boolean;
  className?: string;
  children: ReactNode;
} & React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-xs border px-1.5 py-0.5 text-2xs font-medium ${
        numeric ? "tnum" : ""
      } ${VARIANT_CLASSES[variant]} ${className}`}
      {...rest}
    >
      {children}
    </span>
  );
}
