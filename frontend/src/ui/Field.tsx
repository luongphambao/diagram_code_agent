import type { ReactNode } from "react";

/** A real <label> wrapping a control — replaces icon-prefixed <label> spans
 * in the old header (App.tsx) that had no visible text at all for the label
 * itself (title-attribute-only). */
export default function Field({
  label,
  htmlFor,
  children,
  className = "",
}: {
  label: string;
  htmlFor?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label htmlFor={htmlFor} className={`flex items-center gap-1.5 text-xs text-secondary ${className}`}>
      <span className="label-caps text-2xs text-muted">{label}</span>
      {children}
    </label>
  );
}
