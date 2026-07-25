import { useEffect, useState } from "react";

export type Breakpoint = "wide" | "medium" | "narrow";

/**
 * Three-tier responsive state (plan §D.4 collapses the plan's five documented
 * width bands into three behaviorally distinct shell modes — the two narrowest
 * bands share identical shell mechanics; what differs between them (export
 * button placement) is owned by the artifact canvas, not the shell):
 *
 *   wide   (>=1280px) — rail expanded, chat+canvas side by side, splitter active
 *   medium (1024-1279) — rail collapsed to an icon strip, kind/role selects
 *                         move into a Settings popover, splitter still active
 *   narrow (<1024)     — rail becomes an overlay drawer, chat/canvas become a
 *                         2-pane switcher (both stay mounted), splitter hidden
 */
export function useBreakpoint(): Breakpoint {
  const [bp, setBp] = useState<Breakpoint>(() => classify(typeof window === "undefined" ? 1920 : window.innerWidth));

  useEffect(() => {
    const wideQuery = window.matchMedia("(min-width: 1280px)");
    const mediumQuery = window.matchMedia("(min-width: 1024px)");
    const update = () => setBp(wideQuery.matches ? "wide" : mediumQuery.matches ? "medium" : "narrow");
    update();
    wideQuery.addEventListener("change", update);
    mediumQuery.addEventListener("change", update);
    return () => {
      wideQuery.removeEventListener("change", update);
      mediumQuery.removeEventListener("change", update);
    };
  }, []);

  return bp;
}

function classify(width: number): Breakpoint {
  if (width >= 1280) return "wide";
  if (width >= 1024) return "medium";
  return "narrow";
}
