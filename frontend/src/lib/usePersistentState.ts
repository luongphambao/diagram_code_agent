import { useCallback, useEffect, useState } from "react";

/**
 * A single, namespaced localStorage-backed state hook (plan §D.3). Every UI
 * preference key lives under `da.ui.*`, and every read is validated — the
 * current app already does this ad hoc per-key (see `getStoredRole` /
 * `getStoredDiagramKind` in App.tsx); this generalises the pattern so future
 * preferences don't each reinvent the try/catch + validate dance.
 *
 * `key` should be the FULL storage key (not just a suffix) — the two existing
 * keys `diagram_agent_user_role` / `diagram_agent_diagram_kind` intentionally
 * do NOT get the `da.ui.` prefix, so nobody's already-stored preference resets
 * when this hook replaces their ad hoc handling.
 */
export function usePersistentState<T>(
  key: string,
  initial: T,
  validate?: (value: unknown) => value is T,
): [T, (value: T | ((prev: T) => T)) => void] {
  const [state, setState] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw === null) return initial;
      const parsed = JSON.parse(raw) as unknown;
      if (validate && !validate(parsed)) return initial;
      return parsed as T;
    } catch {
      return initial;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(state));
    } catch {
      /* ignore — quota exceeded or storage disabled; the preference just
       * won't persist across reloads, which is a harmless degradation. */
    }
  }, [key, state]);

  const set = useCallback((value: T | ((prev: T) => T)) => {
    setState((prev) => (typeof value === "function" ? (value as (p: T) => T)(prev) : value));
  }, []);

  return [state, set];
}

/** Convenience validator factory for a fixed set of string literal values. */
export function oneOf<T extends string>(...values: T[]) {
  return (v: unknown): v is T => typeof v === "string" && (values as string[]).includes(v);
}

/** Convenience validator for a number clamped into [min, max]; invalid values
 * (NaN, out of range) fall back to the hook's `initial` rather than being
 * silently clamped, since a clamp can mask a corrupted stored value. */
export function numberInRange(min: number, max: number) {
  return (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v >= min && v <= max;
}
