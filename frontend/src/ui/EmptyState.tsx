import type { ReactNode } from "react";

/** Replaces the ad hoc empty-state block in DiagramCanvas/ChatSidebar
 * (icon + title + hint, previously `text-slate-500`/`text-slate-700` — a
 * WCAG AA failure at those sizes on a near-black ground). */
export default function EmptyState({
  icon,
  title,
  hint,
}: {
  icon?: ReactNode;
  title: string;
  hint?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-10 text-center">
      {icon && (
        <div className="flex h-10 w-10 items-center justify-center rounded-md bg-well text-secondary">
          {icon}
        </div>
      )}
      <div>
        <p className="text-sm font-medium text-secondary">{title}</p>
        {hint && <p className="mt-1.5 text-xs leading-relaxed text-muted">{hint}</p>}
      </div>
    </div>
  );
}
