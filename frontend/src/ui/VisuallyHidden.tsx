import type { ReactNode } from "react";

/** Screen-reader-only content — visually hidden but announced. Used for the
 * aria-live status/error regions (§E.6) and for giving icon-only controls an
 * accessible name without a visible label. */
export default function VisuallyHidden({ children }: { children: ReactNode }) {
  return <span className="sr-only">{children}</span>;
}
