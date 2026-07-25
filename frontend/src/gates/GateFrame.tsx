import { useEffect, useRef, type ReactNode } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import Card from "../ui/Card";
import Chip from "../ui/Chip";
import Stripe from "../ui/Stripe";
import type { ChipVariant } from "../ui/Chip";
import type { Severity } from "../ui/Stripe";

export type GateTone = "decision" | "export" | "comms" | "danger";

const TONE_META: Record<GateTone, { severity: Severity; chip: ChipVariant }> = {
  decision: { severity: "warn", chip: "warn" },
  export: { severity: "info", chip: "info" },
  comms: { severity: "accent", chip: "accent" },
  danger: { severity: "danger", chip: "danger" },
};

interface GateFrameProps {
  label: string;
  tone: GateTone;
  status: ToolCallStatus;
  /** Extra chip/text rendered next to the label in every state (e.g. a section count). */
  badge?: ReactNode;
  children: ReactNode;
}

/**
 * The shared shell every gate card renders through (plan §F.5): a 2px tone
 * stripe + header + body, replacing the near-identical header/border/stripe
 * markup duplicated across the 12 old approval components. Owns the
 * InProgress/Complete states generically (only "Executing" differs per
 * gate, via `children`) and the focus management on open — ported from
 * WildcardGateCard.tsx: focus the FRAME, not a primary button, since
 * focusing a primary invites an accidental Enter (plan §F, "Focus
 * management").
 */
export default function GateFrame({ label, tone, status, badge, children }: GateFrameProps) {
  const ref = useRef<HTMLDivElement>(null);
  const isExecuting = status === ToolCallStatus.Executing;
  const meta = TONE_META[tone];

  useEffect(() => {
    if (!isExecuting) return;
    ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    ref.current?.focus({ preventScroll: true });
  }, [isExecuting]);

  if (status === ToolCallStatus.InProgress) {
    return (
      <Card className="relative mt-2 max-w-xl overflow-hidden p-4 pl-5 animate-pulse motion-reduce:animate-none">
        <Stripe severity={meta.severity} />
        <p className="text-xs text-muted">Preparing {label.toLowerCase()}…</p>
      </Card>
    );
  }

  if (status === ToolCallStatus.Complete) {
    return (
      <Card className="relative mt-2 max-w-xl overflow-hidden p-4 pl-5">
        <Stripe severity="ok" />
        <div className="flex items-center gap-2">
          <Chip variant="ok">Resolved</Chip>
          <span className="text-sm font-medium text-fg">{label}</span>
          {badge}
        </div>
      </Card>
    );
  }

  return (
    <Card
      ref={ref}
      tabIndex={-1}
      role="group"
      aria-label={label}
      className="relative mt-2 max-w-xl overflow-hidden p-4 pl-5"
    >
      <Stripe severity={meta.severity} />
      <div className="mb-3 flex items-center gap-2">
        <Chip variant={meta.chip}>Approval needed</Chip>
        <span className="text-sm font-semibold text-fg">{label}</span>
        {badge}
      </div>
      <div className="flex flex-col gap-3">{children}</div>
    </Card>
  );
}
