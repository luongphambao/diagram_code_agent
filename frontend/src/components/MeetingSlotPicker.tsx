import { useState } from "react";
import type { PendingInterrupt } from "../hooks/useDiagramAgent";

interface SelectedSlot {
  start: string;
  end: string;
  display_day: string;
  display_time: string;
}

interface MeetingSlotPickerProps {
  interrupt: PendingInterrupt;
  onResolve: (approved: boolean, selectedSlot?: SelectedSlot) => void;
  disabled?: boolean;
}

export default function MeetingSlotPicker({
  interrupt,
  onResolve,
  disabled = false,
}: MeetingSlotPickerProps) {
  const [picked, setPicked] = useState<number | null>(null);
  const [decided, setDecided] = useState(false);
  const [cancelled, setCancelled] = useState(false);

  const { slots = [], duration_minutes, timezone, context } = interrupt.data;

  const confirm = () => {
    if (picked === null) return;
    const slot = slots[picked] as SelectedSlot;
    setDecided(true);
    onResolve(true, slot);
  };

  const cancel = () => {
    setCancelled(true);
    setDecided(true);
    onResolve(false);
  };

  if (decided) {
    return (
      <div className="flex w-full flex-col overflow-hidden rounded-2xl border border-violet-500/20 bg-violet-950/15 px-4 py-3">
        <p className="text-xs text-slate-500">
          {cancelled
            ? "Slot selection cancelled."
            : picked !== null
              ? `Slot confirmed: ${(slots[picked] as SelectedSlot).display_day} ${(slots[picked] as SelectedSlot).display_time}`
              : "Done."}
        </p>
      </div>
    );
  }

  return (
    <div className="flex w-full flex-col overflow-hidden rounded-2xl border border-violet-500/20 bg-violet-950/15">
      {/* Header */}
      <div className="flex items-center gap-2.5 border-b border-white/8 bg-white/4 px-4 py-3">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-violet-500/20">
          <svg
            className="h-3.5 w-3.5 text-violet-300"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <rect x="3" y="4" width="18" height="18" rx="2" />
            <line x1="16" y1="2" x2="16" y2="6" />
            <line x1="8" y1="2" x2="8" y2="6" />
            <line x1="3" y1="10" x2="21" y2="10" />
          </svg>
        </div>
        <p className="flex-1 text-sm font-semibold text-white">Pick a Meeting Time</p>
        <span className="rounded-full border border-violet-500/25 bg-violet-500/10 px-2 py-0.5 text-[11px] font-medium text-violet-300">
          {duration_minutes ? `${duration_minutes} min` : "meeting"}
        </span>
      </div>

      <div className="flex flex-col gap-3 px-4 py-4">
        <p className="text-xs leading-relaxed text-slate-400">{interrupt.data.question}</p>

        {context && <p className="text-[11px] italic text-slate-500">{context}</p>}

        {/* Slot list */}
        {slots.length === 0 ? (
          <div className="rounded-xl border border-white/8 bg-white/4 px-4 py-4 text-center">
            <p className="text-xs text-slate-500">
              No available slots found. Try adjusting the date range.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {(slots as SelectedSlot[]).map((slot, i) => (
              <button
                key={i}
                onClick={() => setPicked(i)}
                disabled={disabled}
                className={`flex w-full items-center justify-between rounded-xl border px-3.5 py-2.5 text-left transition-all disabled:opacity-50 ${
                  picked === i
                    ? "border-violet-500/60 bg-violet-500/15 ring-1 ring-violet-500/30"
                    : "border-white/8 bg-white/4 hover:border-violet-500/30 hover:bg-violet-500/8"
                }`}
              >
                <div>
                  <p
                    className={`text-xs font-semibold ${picked === i ? "text-violet-200" : "text-slate-200"}`}
                  >
                    {slot.display_day}
                  </p>
                  <p
                    className={`mt-0.5 text-[11px] ${picked === i ? "text-violet-300" : "text-slate-400"}`}
                  >
                    {slot.display_time}
                    {timezone ? <span className="ml-1.5 opacity-60">{timezone}</span> : null}
                  </p>
                </div>
                {/* Radio indicator */}
                <div
                  className={`flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full border-2 transition-colors ${
                    picked === i ? "border-violet-400 bg-violet-400" : "border-white/20"
                  }`}
                >
                  {picked === i && <div className="h-1.5 w-1.5 rounded-full bg-white" />}
                </div>
              </button>
            ))}
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2.5 pt-1">
          <button
            onClick={confirm}
            disabled={disabled || picked === null}
            className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-violet-700 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-violet-900/30 transition-all hover:bg-violet-600 active:scale-98 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <svg
              className="h-3.5 w-3.5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
            Confirm This Time
          </button>
          <button
            onClick={cancel}
            disabled={disabled}
            className="rounded-xl border border-white/10 bg-white/4 px-4 py-2.5 text-xs font-semibold text-slate-300 transition-all hover:bg-white/8 disabled:opacity-50"
          >
            None Work
          </button>
        </div>

        <p className="text-[11px] text-slate-700">Select a slot above, then click Confirm.</p>
      </div>
    </div>
  );
}
