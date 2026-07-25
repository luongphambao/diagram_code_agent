import { useRef } from "react";
import Chip from "./Chip";

export interface TabBarItem {
  id: string;
  label: string;
  count?: number;
  countVariant?: "neutral" | "accent" | "danger";
}

/**
 * Full ARIA APG tabs pattern (plan §G.2) — role=tablist/tab/tabpanel,
 * aria-selected, roving tabindex, arrow-key/Home/End navigation. Replaces
 * ArtifactTabs.tsx's plain <button> row with no role/aria-selected. The count
 * is a Chip (not baked into the label string), so screen readers get
 * "Activity, 12 items" via aria-label rather than "(12)" read as prose.
 */
export default function TabBar({
  items,
  active,
  onSelect,
  panelId,
  label,
}: {
  items: TabBarItem[];
  active: string;
  onSelect: (id: string) => void;
  /** id prefix used to build `tab-${id}` / `panel-${id}` pairs. */
  panelId: string;
  label: string;
}) {
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  function focusAndSelect(id: string) {
    onSelect(id);
    tabRefs.current[id]?.focus();
  }

  function onKeyDown(e: React.KeyboardEvent, index: number) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    let next = index;
    if (e.key === "ArrowLeft") next = (index - 1 + items.length) % items.length;
    else if (e.key === "ArrowRight") next = (index + 1) % items.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = items.length - 1;
    focusAndSelect(items[next].id);
  }

  return (
    <div
      role="tablist"
      aria-label={label}
      aria-orientation="horizontal"
      className="flex items-center gap-1 overflow-x-auto"
    >
      {items.map((item, i) => {
        const selected = item.id === active;
        return (
          <button
            key={item.id}
            ref={(el) => {
              tabRefs.current[item.id] = el;
            }}
            role="tab"
            id={`${panelId}-tab-${item.id}`}
            aria-selected={selected}
            aria-controls={`${panelId}-panel-${item.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onSelect(item.id)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={`flex flex-shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium transition-colors ${
              selected
                ? "border-accent text-fg"
                : "border-transparent text-secondary hover:bg-well hover:text-fg"
            }`}
          >
            {item.label}
            {item.count != null && (
              <Chip
                variant={item.countVariant === "danger" ? "danger" : selected ? "accent" : "neutral"}
                numeric
                aria-label={`${item.count} items`}
              >
                {item.count}
              </Chip>
            )}
          </button>
        );
      })}
    </div>
  );
}
