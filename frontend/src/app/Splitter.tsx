import { useCallback, useRef } from "react";

/**
 * Replaces App.tsx's hand-rolled resize handle. Adds two things the old one
 * lacked: pointer capture (so a fast drag that exits the window doesn't
 * strand the col-resize cursor) and a real `role="separator"` with keyboard
 * resize (ArrowLeft/Right), so the chat/canvas split is operable without a
 * mouse.
 */
export default function Splitter({
  width,
  min,
  max,
  onChange,
}: {
  width: number;
  min: number;
  max: number;
  onChange: (next: number) => void;
}) {
  const dragging = useRef(false);
  const startX = useRef(0);
  const startW = useRef(width);

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      dragging.current = true;
      startX.current = e.clientX;
      startW.current = width;
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    },
    [width],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!dragging.current) return;
      const delta = e.clientX - startX.current;
      onChange(Math.min(max, Math.max(min, startW.current + delta)));
    },
    [max, min, onChange],
  );

  const endDrag = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = false;
    (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  }, []);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const step = e.shiftKey ? 40 : 12;
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        onChange(Math.max(min, width - step));
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        onChange(Math.min(max, width + step));
      } else if (e.key === "Home") {
        e.preventDefault();
        onChange(min);
      } else if (e.key === "End") {
        e.preventDefault();
        onChange(max);
      }
    },
    [max, min, onChange, width],
  );

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize chat panel"
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={width}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={onKeyDown}
      className="group relative w-1 flex-shrink-0 cursor-col-resize bg-line/50 transition-colors hover:bg-accent/40 focus-visible:bg-accent/40"
    >
      <div className="pointer-events-none absolute inset-y-0 left-1/2 flex -translate-x-1/2 flex-col items-center justify-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
        <span className="h-1 w-1 rounded-full bg-accent-hi" />
        <span className="h-1 w-1 rounded-full bg-accent-hi" />
        <span className="h-1 w-1 rounded-full bg-accent-hi" />
      </div>
    </div>
  );
}
