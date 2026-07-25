import type { ReactNode } from "react";

interface KVItem {
  label: string;
  value: ReactNode;
}

/** The "label + value" info block repeated across Email/Meeting/PDF/PPT/
 * business-case cards (plan §F.5), generalised into one primitive. Items
 * with an empty value are dropped rather than rendered blank. */
export default function KeyValueGrid({ items, className = "" }: { items: KVItem[]; className?: string }) {
  const visible = items.filter((i) => i.value !== undefined && i.value !== null && i.value !== "");
  if (!visible.length) return null;
  return (
    <dl className={`flex flex-col gap-2 rounded-sm border border-line bg-well px-3 py-2.5 ${className}`}>
      {visible.map((item, i) => (
        <div key={i}>
          <dt className="label-caps text-2xs font-semibold text-muted">{item.label}</dt>
          <dd className="mt-0.5 text-sm text-fg">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
