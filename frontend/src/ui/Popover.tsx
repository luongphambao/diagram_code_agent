import { useEffect, useRef, type ReactNode } from "react";

/**
 * A minimal anchored popover — used for the sub-1280px "Settings ▾" menu that
 * collapses the diagram-kind/role selects (plan §D.4/§D.5) and for the
 * artifact canvas's "Export ▾" overflow menu. Closes on outside click and
 * Escape; returns focus to the trigger on close.
 */
export default function Popover({
  open,
  onClose,
  anchorRef,
  children,
}: {
  open: boolean;
  onClose: () => void;
  anchorRef: React.RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  const popRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      const target = e.target as Node;
      if (popRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      onClose();
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
        anchorRef.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onClose, anchorRef]);

  if (!open) return null;

  return (
    <div
      ref={popRef}
      role="dialog"
      aria-modal="false"
      className="absolute right-0 top-full z-30 mt-1.5 min-w-48 rounded-md border border-line bg-raised p-2 shadow-sm"
    >
      {children}
    </div>
  );
}
