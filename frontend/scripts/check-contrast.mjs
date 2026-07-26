#!/usr/bin/env node
/**
 * Stage 0 guardrail (plan §H): reads the CONTRAST_PAIRS contract out of
 * src/styles/tokens.ts and fails the build if any documented foreground/
 * background pair drops below its target WCAG ratio. This is what keeps
 * defect 4 (the ~20 text-slate-700/800-on-near-black failures in the current
 * app) from ever coming back once Stage 1 lands the real token system.
 *
 * Relies on Node's native TypeScript type-stripping (Node >=22.6 experimental,
 * unflagged default since Node 23.6) to import tokens.ts directly — no build
 * step, no extra dependency. tokens.ts only uses type annotations/interfaces
 * (no enums/namespaces), which is exactly what stripping supports.
 */

import { CONTRAST_PAIRS } from "../src/styles/tokens.ts";

function srgbToLinear(c) {
  const cs = c / 255;
  return cs <= 0.03928 ? cs / 12.92 : ((cs + 0.055) / 1.055) ** 2.4;
}

function relativeLuminance(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) throw new Error(`not a 6-digit hex color: ${hex}`);
  const int = parseInt(m[1], 16);
  const r = srgbToLinear((int >> 16) & 0xff);
  const g = srgbToLinear((int >> 8) & 0xff);
  const b = srgbToLinear(int & 0xff);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(hexA, hexB) {
  const lA = relativeLuminance(hexA);
  const lB = relativeLuminance(hexB);
  const lighter = Math.max(lA, lB);
  const darker = Math.min(lA, lB);
  return (lighter + 0.05) / (darker + 0.05);
}

let failures = 0;
const rows = [];

for (const pair of CONTRAST_PAIRS) {
  const ratio = contrastRatio(pair.fg, pair.bg);
  const pass = ratio >= pair.min;
  if (!pass) failures += 1;
  rows.push({
    theme: pair.theme,
    label: pair.label,
    fg: pair.fg,
    bg: pair.bg,
    ratio: ratio.toFixed(2),
    min: pair.min,
    status: pass ? "PASS" : "FAIL",
  });
}

const width = Math.max(...rows.map((r) => r.label.length)) + 2;
for (const r of rows) {
  const marker = r.status === "PASS" ? "✓" : "✗";
  const line = `${marker} [${r.theme.padEnd(5)}] ${r.label.padEnd(width)} ${r.fg} on ${r.bg}  ${r.ratio}:1 (min ${r.min}:1)`;
  console.log(r.status === "PASS" ? line : line);
}

console.log(`\n${rows.length - failures}/${rows.length} pairs pass.`);

if (failures > 0) {
  console.error(`\n${failures} contrast pair(s) below their documented minimum — see src/styles/tokens.ts CONTRAST_PAIRS.`);
  process.exit(1);
}
