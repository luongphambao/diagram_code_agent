#!/usr/bin/env node
/**
 * Emits src/styles/tokens.css from src/styles/tokens.ts (plan §C.5).
 *
 * Three-layer cascade so the theme resolves correctly in every situation:
 *   1. :root                                           — dark is the authored default
 *   2. @media (prefers-color-scheme: light) :root:not([data-theme])  — honour the OS
 *      when the user has not made an explicit in-app choice
 *   3. [data-theme="light"] / [data-theme="dark"]       — an explicit choice always wins
 *
 * Generated (not hand-duplicated) so the light block is written once and the
 * contrast-check script and this file can never drift from tokens.ts.
 * Re-run after any tokens.ts edit: `npm run build-tokens`.
 */

import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dark, light } from "../src/styles/tokens.ts";

const OUT_PATH = fileURLToPath(new URL("../src/styles/tokens.css", import.meta.url));

function themeBlock(t) {
  return `  --ink-950: ${t.ink[950]};
  --ink-900: ${t.ink[900]};
  --ink-850: ${t.ink[850]};
  --ink-800: ${t.ink[800]};
  --ink-700: ${t.ink[700]};
  --ink-500: ${t.ink[500]};
  --ink-300: ${t.ink[300]};
  --ink-100: ${t.ink[100]};

  --accent-600: ${t.accent[600]};
  --accent-500: ${t.accent[500]};
  --accent-400: ${t.accent[400]};
  --accent-300: ${t.accent[300]};
  --accent-fg: ${t.accent.fg};
  --accent-text: ${t.accent.text};

  --ok: ${t.semantic.ok};
  --ok-fg: ${t.semantic.okFg};
  --warn: ${t.semantic.warn};
  --warn-fg: ${t.semantic.warnFg};
  --danger: ${t.semantic.danger};
  --danger-fg: ${t.semantic.dangerFg};
  --info: ${t.semantic.info};
  --info-fg: ${t.semantic.infoFg};

  --radius-xs: ${t.radius.xs};
  --radius-sm: ${t.radius.sm};
  --radius-md: ${t.radius.md};
  --radius-lg: ${t.radius.lg};
  --radius-full: ${t.radius.full};
  --shadow-sm: ${t.shadowSm};`;
}

const css = `/* GENERATED FILE — do not edit by hand.
 * Source of truth: src/styles/tokens.ts. Regenerate with \`npm run build-tokens\`.
 * See plan §C.5 (giao-dien-thiet-ke-jaunty-rain.md) for the three-layer cascade
 * this implements and §C.1/C.2 for the palette rationale. */

:root {
  color-scheme: dark;
${themeBlock(dark)}
}

@media (prefers-color-scheme: light) {
  :root:not([data-theme]) {
    color-scheme: light;
${themeBlock(light)}
  }
}

[data-theme="light"] {
  color-scheme: light;
${themeBlock(light)}
}

[data-theme="dark"] {
  color-scheme: dark;
${themeBlock(dark)}
}
`;

writeFileSync(OUT_PATH, css, "utf-8");
console.log(`wrote ${OUT_PATH}`);
