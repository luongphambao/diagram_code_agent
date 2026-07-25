import { useState } from "react";
import { ToolCallStatus } from "@copilotkit/core";
import GateFrame from "../GateFrame";
import KeyValueGrid from "../KeyValueGrid";
import Chip from "../../ui/Chip";
import Button from "../../ui/Button";
import type { GateCardProps } from "../types";

/** Ported from components/MeetingApproval.tsx (plan §F). */
export default function MeetingCard({ args, status, respond }: GateCardProps) {
  const [decided, setDecided] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  const title = typeof args.title === "string" ? args.title : "";
  const displayStart = typeof args.display_start === "string" ? args.display_start : "";
  const displayEnd = typeof args.display_end === "string" ? args.display_end : "";
  const durationMinutes = typeof args.duration_minutes === "number" ? args.duration_minutes : 0;
  const attendeeEmail = typeof args.attendee_email === "string" ? args.attendee_email : "";
  const attendeeName = typeof args.attendee_name === "string" ? args.attendee_name : "";
  const description = typeof args.description === "string" ? args.description : "";
  const addGoogleMeet = args.add_google_meet !== false;
  const timezone = typeof args.timezone === "string" ? args.timezone : "";

  function decide(approved: boolean) {
    setDecided(true);
    setDecision(approved ? "approved" : "rejected");
    void respond?.({ action: approved ? "approve" : "reject", approved });
  }

  if (decided && status === ToolCallStatus.Executing) {
    return (
      <GateFrame label="Meeting" tone="comms" status={status}>
        <p className="text-xs text-muted">{decision === "approved" ? "Creating calendar event…" : "Meeting scheduling cancelled."}</p>
      </GateFrame>
    );
  }

  return (
    <GateFrame label="Meeting" tone="comms" status={status} badge={<Chip variant="accent">Google Calendar</Chip>}>
      <p className="text-sm text-secondary">{typeof args.question === "string" ? args.question : "Schedule this meeting?"}</p>
      <KeyValueGrid
        items={[
          { label: "Meeting", value: title },
          {
            label: "Date & Time",
            value: displayStart ? (
              <>
                {displayStart}
                {displayEnd ? ` – ${displayEnd}` : ""}
                {durationMinutes ? <span className="mt-0.5 block text-xs text-muted">{durationMinutes} min · {timezone}</span> : null}
              </>
            ) : (
              ""
            ),
          },
          {
            label: "Attendee",
            value: attendeeEmail ? (
              <>
                {attendeeName && attendeeName !== "Client" ? `${attendeeName} ` : ""}
                <span className="text-muted">&lt;{attendeeEmail}&gt;</span>
              </>
            ) : (
              ""
            ),
          },
          { label: "Agenda", value: description },
        ]}
      />
      {addGoogleMeet && (
        <div className="flex items-center gap-2 rounded-sm border border-ok/25 bg-ok/8 px-3 py-2">
          <p className="text-2xs text-ok-text">Google Meet link will be generated and included in the invite</p>
        </div>
      )}
      <p className="text-2xs text-muted">A calendar invite will be sent to all attendees from your connected Google Calendar account.</p>
      <div className="flex gap-2.5">
        <Button variant="primary" size="md" onClick={() => decide(true)} className="flex-1">
          Confirm Meeting
        </Button>
        <Button variant="secondary" size="md" onClick={() => decide(false)}>
          Cancel
        </Button>
      </div>
    </GateFrame>
  );
}
