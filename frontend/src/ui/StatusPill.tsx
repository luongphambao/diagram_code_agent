import type { ReactNode } from "react";

export type StatusVariant = "idle" | "running" | "awaiting" | "done" | "error";

/**
 * Five status variants, each a distinct dot SHAPE (not just color) so status
 * survives a colorblind read and a greyscale screenshot — plan §D.6. Circle
 * (idle/running/done), square (awaiting — a gate is open, deliberately
 * distinct from "running"), triangle (error).
 */
function Dot({ variant }: { variant: StatusVariant }) {
  const common = "inline-block h-1.5 w-1.5 flex-shrink-0";
  switch (variant) {
    case "idle":
      return <span className={`${common} rounded-full bg-muted`} aria-hidden="true" />;
    case "running":
      return (
        <span
          className={`${common} rounded-full bg-accent animate-pulse motion-reduce:animate-none`}
          aria-hidden="true"
        />
      );
    case "done":
      return <span className={`${common} rounded-full bg-ok`} aria-hidden="true" />;
    case "awaiting":
      return <span className={`${common} bg-warn`} aria-hidden="true" />; // square (no rounded-full)
    case "error":
      return (
        <span
          aria-hidden="true"
          className="inline-block h-0 w-0 flex-shrink-0 border-x-[4px] border-b-[7px] border-x-transparent border-b-danger"
        />
      );
  }
}

const LABEL_TEXT: Record<StatusVariant, string> = {
  idle: "text-muted",
  running: "text-accent-text",
  awaiting: "text-warn-text",
  done: "text-ok-text",
  error: "text-danger-text",
};

export default function StatusPill({
  variant,
  children,
  className = "",
}: {
  variant: StatusVariant;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-xs border border-line/60 bg-well/50 px-2 py-0.5 text-2xs font-medium uppercase tracking-wide ${LABEL_TEXT[variant]} ${className}`}
    >
      <Dot variant={variant} />
      {children}
    </span>
  );
}
