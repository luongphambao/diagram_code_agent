import type { ChipVariant } from "../ui/Chip";

/**
 * Generalises the old app's per-key rainbow maps (BlueprintApproval's
 * PATTERN_COLORS/TIER_DOT, WbsApproval's ROLE_COLORS, SubagentPanel's
 * COLORS — plan §F.5's "ColorScale, generalised from the only existing
 * variant map") into ONE deterministic key -> Chip variant assignment.
 *
 * Deliberately restrained to the design system's semantic palette (plan
 * §C.1: "the accent is used for exactly three things... nothing
 * decorative") rather than reproducing the old blue/violet/amber/emerald/
 * rose confetti — distinctness between categories comes from the label
 * text + this rotation, not from inventing new hues.
 */
const SCALE: readonly ChipVariant[] = ["accent", "info", "ok", "warn", "neutral"];

function hash(key: string): number {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
  return Math.abs(h);
}

export function colorForKey(key: string): ChipVariant {
  return SCALE[hash(key) % SCALE.length];
}
