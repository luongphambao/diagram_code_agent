import { useState } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import GateFrame from "../GateFrame";
import Button from "../../ui/Button";
import Chip from "../../ui/Chip";
import type { GateCardProps } from "../types";

interface SelectedSlot {
  start: string;
  end: string;
  display_day: string;
  display_time: string;
}

/** Ported from components/MeetingSlotPicker.tsx (plan §F). `respond` carries
 * `{action:"approve", approved:true, selected_slot}` — gate_decisions.py's
 * `_decision_from_payload` reads `selected_slot` verbatim off the payload
 * (not an index) when present. */
export default function SlotPickerCard({ args, status, respond }: GateCardProps) {
  const [picked, setPicked] = useState<number | null>(null);
  const [decided, setDecided] = useState(false);
  const [cancelled, setCancelled] = useState(false);

  const slots = (Array.isArray(args.slots) ? args.slots : []) as SelectedSlot[];
  const durationMinutes = typeof args.duration_minutes === "number" ? args.duration_minutes : undefined;
  const timezone = typeof args.timezone === "string" ? args.timezone : "";
  const context = typeof args.context === "string" ? args.context : "";

  const confirm = () => {
    if (picked === null) return;
    setDecided(true);
    void respond?.({ action: "approve", approved: true, selected_slot: slots[picked] });
  };
  const cancel = () => {
    setCancelled(true);
    setDecided(true);
    void respond?.({ action: "reject", approved: false });
  };

  if (decided && status === ToolCallStatus.Executing) {
    return (
      <GateFrame label="Meeting Slot" tone="comms" status={status}>
        <p className="text-xs text-muted">
          {cancelled
            ? "Slot selection cancelled."
            : picked !== null
              ? `Slot confirmed: ${slots[picked].display_day} ${slots[picked].display_time}`
              : "Done."}
        </p>
      </GateFrame>
    );
  }

  return (
    <GateFrame
      label="Meeting Slot"
      tone="comms"
      status={status}
      badge={<Chip variant="accent">{durationMinutes ? `${durationMinutes} min` : "meeting"}</Chip>}
    >
      <p className="text-sm text-secondary">{typeof args.question === "string" ? args.question : "Pick a time that works:"}</p>
      {context && <p className="text-xs italic text-muted">{context}</p>}

      {slots.length === 0 ? (
        <div className="rounded-sm border border-line bg-well px-4 py-4 text-center">
          <p className="text-xs text-muted">No available slots found. Try adjusting the date range.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {slots.map((slot, i) => (
            <button
              key={i}
              onClick={() => setPicked(i)}
              className={`flex w-full items-center justify-between rounded-sm border px-3.5 py-2.5 text-left transition-colors ${
                picked === i ? "border-accent-hi bg-accent/10" : "border-line bg-well hover:border-accent-hi/40"
              }`}
            >
              <div>
                <p className={`text-xs font-semibold ${picked === i ? "text-accent-text" : "text-fg"}`}>{slot.display_day}</p>
                <p className={`mt-0.5 text-xs ${picked === i ? "text-accent-text" : "text-secondary"}`}>
                  {slot.display_time}
                  {timezone ? <span className="ml-1.5 text-muted">{timezone}</span> : null}
                </p>
              </div>
              <div
                className={`flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full border-2 ${
                  picked === i ? "border-accent-hi bg-accent-hi" : "border-line"
                }`}
              >
                {picked === i && <div className="h-1.5 w-1.5 rounded-full bg-on-accent" />}
              </div>
            </button>
          ))}
        </div>
      )}

      <div className="flex gap-2.5">
        <Button variant="primary" size="md" onClick={confirm} disabled={picked === null} className="flex-1">
          Confirm This Time
        </Button>
        <Button variant="secondary" size="md" onClick={cancel}>
          None Work
        </Button>
      </div>
      <p className="text-2xs text-muted">Select a slot above, then click Confirm.</p>
    </GateFrame>
  );
}
