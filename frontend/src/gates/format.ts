import type { CostRange } from "../hooks/agent-utils";

/** Shared USD formatter (plan §F.5 "CostRange" primitive) — ported verbatim
 * from TechStackApproval.tsx so techstack/business-case/scaling-roadmap all
 * render cost figures identically. */
export function fmtUsd(r?: CostRange | null): string {
  if (!r) return "";
  const fmt = (n: number) => (n >= 1000 ? `$${(n / 1000).toFixed(n % 1000 === 0 ? 0 : 1)}k` : `$${n}`);
  return `${fmt(r.min_usd)}–${fmt(r.max_usd)}/mo`;
}

/** Plain USD (no /mo suffix) for one-off figures like implementation cost. */
export function fmtUsdFlat(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return n >= 1000 ? `$${(n / 1000).toFixed(n % 1000 === 0 ? 0 : 1)}k` : `$${n}`;
}
