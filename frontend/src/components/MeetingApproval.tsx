import { useState } from "react";
import type { PendingInterrupt } from "../hooks/useDiagramAgent";

interface MeetingApprovalProps {
  interrupt: PendingInterrupt;
  onResolve: (approved: boolean) => void;
  disabled?: boolean;
}

export default function MeetingApproval({
  interrupt,
  onResolve,
  disabled = false,
}: MeetingApprovalProps) {
  const [decided, setDecided] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  const {
    title,
    display_start,
    display_end,
    duration_minutes,
    attendee_email,
    attendee_name,
    description,
    add_google_meet,
    timezone,
  } = interrupt.data;

  const approve = () => {
    setDecided(true);
    setDecision("approved");
    onResolve(true);
  };

  const reject = () => {
    setDecided(true);
    setDecision("rejected");
    onResolve(false);
  };

  return (
    <div className="flex w-full flex-col overflow-hidden rounded-2xl border border-emerald-500/20 bg-emerald-950/15">
      {/* Header */}
      <div className="flex items-center gap-2.5 border-b border-white/8 bg-white/4 px-4 py-3">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500/20">
          <svg
            className="h-3.5 w-3.5 text-emerald-300"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
            <line x1="16" y1="2" x2="16" y2="6" />
            <line x1="8" y1="2" x2="8" y2="6" />
            <line x1="3" y1="10" x2="21" y2="10" />
          </svg>
        </div>
        <p className="flex-1 text-sm font-semibold text-white">Schedule Client Meeting</p>
        <span className="rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-300">
          Google Calendar
        </span>
      </div>

      {decided ? (
        <div className="px-4 py-3">
          <p className="text-xs text-slate-500">
            {decision === "approved" ? "Creating calendar event…" : "Meeting scheduling cancelled."}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3 px-4 py-4">
          <p className="text-xs leading-relaxed text-slate-400">{interrupt.data.question}</p>

          {/* Meeting details card */}
          <div className="rounded-xl border border-white/8 bg-white/4 px-3 py-3 space-y-2.5">
            {/* Title */}
            {title && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-emerald-300/70">
                  Meeting
                </p>
                <p className="mt-0.5 text-sm font-medium text-slate-100">{title}</p>
              </div>
            )}

            {/* Date & time */}
            {display_start && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-emerald-300/70">
                  Date & Time
                </p>
                <p className="mt-0.5 text-sm text-slate-100">
                  {display_start}
                  {display_end ? ` – ${display_end}` : ""}
                </p>
                {duration_minutes ? (
                  <p className="text-[11px] text-slate-500">
                    {duration_minutes} min · {timezone}
                  </p>
                ) : null}
              </div>
            )}

            {/* Attendee */}
            {attendee_email && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-emerald-300/70">
                  Attendee
                </p>
                <p className="mt-0.5 text-xs text-slate-300">
                  {attendee_name && attendee_name !== "Client" ? `${attendee_name} ` : ""}
                  <span className="text-slate-400">&lt;{attendee_email}&gt;</span>
                </p>
              </div>
            )}

            {/* Description */}
            {description && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-emerald-300/70">
                  Agenda
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-slate-400">{description}</p>
              </div>
            )}
          </div>

          {/* Google Meet badge */}
          {add_google_meet && (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-500/15 bg-emerald-500/8 px-3 py-2">
              <svg
                className="h-3.5 w-3.5 flex-shrink-0 text-emerald-400"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <polygon points="23 7 16 12 23 17 23 7" />
                <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
              </svg>
              <p className="text-[11px] text-emerald-300">
                Google Meet link will be generated and included in the invite
              </p>
            </div>
          )}

          <p className="text-[11px] text-slate-500">
            A calendar invite will be sent to all attendees from your connected Google Calendar
            account.
          </p>

          {/* Action buttons */}
          <div className="flex gap-2.5">
            <button
              onClick={approve}
              disabled={disabled}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-emerald-700 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-emerald-900/30 transition-all hover:bg-emerald-600 active:scale-98 disabled:opacity-50"
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
              Confirm Meeting
            </button>
            <button
              onClick={reject}
              disabled={disabled}
              className="rounded-xl border border-white/10 bg-white/4 px-4 py-2.5 text-xs font-semibold text-slate-300 transition-all hover:bg-white/8 disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
