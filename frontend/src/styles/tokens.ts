/**
 * "Technical-instrument dark" design system — the single machine-readable source
 * of truth for both themes. See plan §C (C.1 dark palette, C.2 light theme) at
 * C:\Users\luong\.claude\plans\giao-dien-thiet-ke-jaunty-rain.md for the full
 * rationale (hue-biased neutrals, accent used for exactly three things, semantic
 * status kept separate from the accent, etc).
 *
 * scripts/build-tokens.mjs (Stage 1) reads this to emit tokens.css with the
 * three-layer theming cascade (:root → prefers-color-scheme → [data-theme]).
 * scripts/check-contrast.mjs (Stage 0) reads CONTRAST_PAIRS below and fails the
 * build if any documented foreground/background pair drops below its target
 * ratio — this file IS the contrast contract, not just a color list.
 */

export interface ThemeTokens {
  ink: {
    950: string; // viewport floor
    900: string; // canvas + chat column
    850: string; // raised: toolbar, rail, gate cards, tab strip
    800: string; // wells + hovers
    700: string; // hairlines — all borders
    500: string; // muted foreground
    300: string; // secondary foreground
    100: string; // primary foreground
  };
  accent: {
    600: string; // pressed
    500: string; // primary fill, active tab
    400: string; // hover, focus ring, live indicator
    300: string; // accent text on dark/light ground
    fg: string; // text on an accent fill
  };
  semantic: {
    ok: string;
    okFg: string;
    warn: string;
    warnFg: string;
    danger: string;
    dangerFg: string;
    info: string;
    infoFg: string;
  };
  radius: {
    xs: string;
    sm: string;
    md: string;
    lg: string;
    full: string;
  };
  shadowSm: string;
}

export const dark: ThemeTokens = {
  ink: {
    950: "#0A0D13",
    900: "#0E131B",
    850: "#131922",
    800: "#1A212C",
    700: "#26313F",
    500: "#7E8795", // tuned to clear 4.5:1 on BOTH ink-900 and ink-850 (the harder case) — see CONTRAST_PAIRS
    300: "#9AA8BB",
    100: "#DDE4ED",
  },
  accent: {
    600: "#2C7089",
    500: "#3B8FAC",
    400: "#59AECA",
    300: "#8FCFE2",
    fg: "#04141B",
  },
  semantic: {
    ok: "#2F8F63",
    okFg: "#68D3A2",
    warn: "#B8862F",
    warnFg: "#E5BC68",
    danger: "#B8504C",
    dangerFg: "#F09590",
    info: "#4A6FA5",
    infoFg: "#93AFD8",
  },
  radius: { xs: "2px", sm: "4px", md: "6px", lg: "10px", full: "9999px" },
  shadowSm: "none",
};

export const light: ThemeTokens = {
  ink: {
    950: "#F4F7FA",
    900: "#FAFCFD",
    850: "#FFFFFF",
    800: "#EDF2F7",
    700: "#DBE2EA",
    500: "#67707E", // tuned to clear 4.5:1 on the FAFCFD canvas — see CONTRAST_PAIRS
    300: "#48566A",
    100: "#141C27",
  },
  accent: {
    600: "#134E64",
    500: "#1B6580",
    400: "#2A7E9C",
    300: "#E1EFF4", // becomes the *tint* in light — accent text is dark here, see CONTRAST_PAIRS
    fg: "#FFFFFF",
  },
  semantic: {
    ok: "#1F7A50",
    okFg: "#166341",
    warn: "#9A6E1C",
    warnFg: "#7A5614",
    danger: "#A83F3B",
    dangerFg: "#8A322F",
    info: "#3A5C8C",
    infoFg: "#2E4A73",
  },
  radius: { xs: "2px", sm: "4px", md: "6px", lg: "10px", full: "9999px" },
  shadowSm: "0 1px 2px rgb(16 24 36 / .06), 0 0 0 1px rgb(16 24 36 / .04)",
};

/**
 * Documented foreground/background pairs and the WCAG contrast ratio each must
 * clear, taken verbatim from plan §C's stated ratios. scripts/check-contrast.mjs
 * fails the build if a real computed ratio drops below `min` — this is what
 * fixes defect 4 (the ~20 text-slate-700/800-on-near-black failures) and keeps
 * it fixed on every future token edit.
 */
export interface ContrastPair {
  theme: "dark" | "light";
  label: string;
  fg: string;
  bg: string;
  min: number;
}

export const CONTRAST_PAIRS: ContrastPair[] = [
  // Dark — ink scale foregrounds on the canvas surface.
  { theme: "dark", label: "ink-500 muted fg on ink-900 canvas", fg: dark.ink[500], bg: dark.ink[900], min: 4.5 },
  { theme: "dark", label: "ink-300 secondary fg on ink-900 canvas", fg: dark.ink[300], bg: dark.ink[900], min: 7 },
  { theme: "dark", label: "ink-100 primary fg on ink-900 canvas", fg: dark.ink[100], bg: dark.ink[900], min: 14 },
  { theme: "dark", label: "ink-500 muted fg on ink-850 raised", fg: dark.ink[500], bg: dark.ink[850], min: 4.5 },
  { theme: "dark", label: "ink-100 primary fg on ink-850 raised", fg: dark.ink[100], bg: dark.ink[850], min: 13 },
  // Dark — accent.
  { theme: "dark", label: "accent-300 text on ink-900 canvas", fg: dark.accent[300], bg: dark.ink[900], min: 10 },
  // Corrected from an initial (unverified) design-brief claim of "13.9:1" — that
  // figure was narrative, not computed. 4.5:1 is the real, defensible WCAG AA bar
  // for normal-size text on a filled control; a mid-lightness accent fill cannot
  // hit 13:1 without either going near-black text (fine) or lightening the fill
  // past "restrained cyan-steel" into a pastel, which isn't the design intent.
  { theme: "dark", label: "accent-fg on accent-500 fill", fg: dark.accent.fg, bg: dark.accent[500], min: 4.5 },
  // Dark — semantic text tiers on ink-900/ink-850 (chip backgrounds are tinted at
  // low alpha over the surface, so the surface color is the practical worst case).
  { theme: "dark", label: "ok-fg on ink-900", fg: dark.semantic.okFg, bg: dark.ink[900], min: 6 },
  { theme: "dark", label: "warn-fg on ink-900", fg: dark.semantic.warnFg, bg: dark.ink[900], min: 6 },
  { theme: "dark", label: "danger-fg on ink-900", fg: dark.semantic.dangerFg, bg: dark.ink[900], min: 6 },
  { theme: "dark", label: "info-fg on ink-900", fg: dark.semantic.infoFg, bg: dark.ink[900], min: 6 },

  // Light — ink scale foregrounds on the canvas surface.
  { theme: "light", label: "ink-500 muted fg on ink-900 canvas", fg: light.ink[500], bg: light.ink[900], min: 4.5 },
  { theme: "light", label: "ink-300 secondary fg on ink-900 canvas", fg: light.ink[300], bg: light.ink[900], min: 7 },
  { theme: "light", label: "ink-100 primary fg on ink-900 canvas", fg: light.ink[100], bg: light.ink[900], min: 15 },
  { theme: "light", label: "ink-100 primary fg on ink-850 card (white)", fg: light.ink[100], bg: light.ink[850], min: 15 },
  // Light — accent gets darker, not lighter, per §C.2; must clear AA on white.
  { theme: "light", label: "accent-500 fill text (white) on accent-500", fg: light.accent.fg, bg: light.accent[500], min: 4.5 },
  { theme: "light", label: "accent-500 as text on ink-900 canvas", fg: light.accent[500], bg: light.ink[900], min: 4.5 },
  { theme: "light", label: "accent-500 as text on ink-850 card (white)", fg: light.accent[500], bg: light.ink[850], min: 4.5 },
  // Light — semantic text tiers on white/near-white.
  { theme: "light", label: "ok-fg on ink-850 card (white)", fg: light.semantic.okFg, bg: light.ink[850], min: 4.5 },
  { theme: "light", label: "warn-fg on ink-850 card (white)", fg: light.semantic.warnFg, bg: light.ink[850], min: 4.5 },
  { theme: "light", label: "danger-fg on ink-850 card (white)", fg: light.semantic.dangerFg, bg: light.ink[850], min: 4.5 },
  { theme: "light", label: "info-fg on ink-850 card (white)", fg: light.semantic.infoFg, bg: light.ink[850], min: 4.5 },
];
