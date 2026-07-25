import { useEffect, useRef, useState, type ReactNode } from "react";

interface LightboxProps {
  open: boolean;
  onClose: () => void;
  imageSrc: string;
  alt: string;
  actions?: ReactNode;
}

/**
 * Native `<dialog>` + `showModal()` (plan §G) — focus trap and an inert
 * background come from the platform for free, plus `+`/`-`/`0` zoom and
 * arrow-key pan and return-focus to the trigger. Deliberately NOT
 * CopilotKit's own Lightbox export (scoped to chat attachments; would drag
 * `[data-copilotkit]` styling into the canvas).
 */
export default function Lightbox({ open, onClose, imageSrc, alt, actions }: LightboxProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      returnFocusRef.current = document.activeElement as HTMLElement;
      setZoom(1);
      setPan({ x: 0, y: 0 });
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const handleClose = () => {
      onClose();
      returnFocusRef.current?.focus();
    };
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, [onClose]);

  function onKeyDown(e: React.KeyboardEvent<HTMLDialogElement>) {
    const step = 40;
    if (e.key === "+" || e.key === "=") setZoom((z) => Math.min(z + 0.25, 4));
    else if (e.key === "-") setZoom((z) => Math.max(z - 0.25, 0.25));
    else if (e.key === "0") {
      setZoom(1);
      setPan({ x: 0, y: 0 });
    } else if (e.key === "ArrowLeft") setPan((p) => ({ ...p, x: p.x + step }));
    else if (e.key === "ArrowRight") setPan((p) => ({ ...p, x: p.x - step }));
    else if (e.key === "ArrowUp") setPan((p) => ({ ...p, y: p.y + step }));
    else if (e.key === "ArrowDown") setPan((p) => ({ ...p, y: p.y - step }));
  }

  return (
    <dialog
      ref={dialogRef}
      aria-label="Diagram fullscreen preview"
      onKeyDown={onKeyDown}
      onClick={(e) => {
        if (e.target === dialogRef.current) dialogRef.current?.close();
      }}
      className="m-auto max-h-none max-w-none border-none bg-transparent p-0 backdrop:bg-black/90 backdrop:backdrop-blur-sm"
    >
      <div className="relative flex h-screen w-screen items-center justify-center overflow-hidden">
        <button
          type="button"
          aria-label="Close preview"
          onClick={() => dialogRef.current?.close()}
          className="absolute right-5 top-5 flex h-9 w-9 items-center justify-center rounded-full border border-line bg-well text-fg transition-colors hover:bg-app"
        >
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        {actions && <div className="absolute right-5 top-16 flex flex-col gap-2">{actions}</div>}

        <div className="absolute bottom-5 left-5 flex items-center gap-1 rounded-sm border border-line bg-well px-1 py-1">
          <button
            type="button"
            aria-label="Zoom out"
            onClick={() => setZoom((z) => Math.max(z - 0.25, 0.25))}
            className="flex h-7 w-7 items-center justify-center rounded-xs text-fg hover:bg-app"
          >
            −
          </button>
          <button
            type="button"
            aria-label="Reset zoom"
            onClick={() => {
              setZoom(1);
              setPan({ x: 0, y: 0 });
            }}
            className="tnum w-14 text-center text-xs text-secondary hover:text-fg"
          >
            {Math.round(zoom * 100)}%
          </button>
          <button
            type="button"
            aria-label="Zoom in"
            onClick={() => setZoom((z) => Math.min(z + 0.25, 4))}
            className="flex h-7 w-7 items-center justify-center rounded-xs text-fg hover:bg-app"
          >
            +
          </button>
        </div>

        <img
          src={imageSrc}
          alt={alt}
          style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}
          className="max-h-[90vh] max-w-[90vw] rounded-md object-contain shadow-2xl transition-transform"
        />
      </div>
    </dialog>
  );
}
