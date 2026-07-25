/**
 * Validates a gate's raw tool-call args before handing them to its typed
 * card component (plan §F: "payload shape varies per gate type and is
 * validated at render time... which lets us show a useful fallback instead
 * of failing an opaque parse"). Deliberately narrow: the backend
 * (gate_decisions.py::_card_for) already normalises the payload shape
 * server-side, so this only guards against the cases a schema drift or a
 * genuinely broken tool call would produce — not full per-field validation
 * duplicating what each card already renders defensively.
 */
export type ParsedGatePayload =
  | { ok: true; data: Record<string, unknown> }
  | { ok: false; reason: string };

export function parseGatePayload(type: string, args: unknown): ParsedGatePayload {
  if (!args || typeof args !== "object" || Array.isArray(args)) {
    return { ok: false, reason: "Gate arguments were not an object." };
  }
  const data = args as Record<string, unknown>;

  switch (type) {
    case "techstack_approval":
      if (!data.tech_stack || typeof data.tech_stack !== "object" || Array.isArray(data.tech_stack)) {
        return { ok: false, reason: "tech_stack is missing or not an object." };
      }
      break;
    case "blueprint_approval":
      if (!data.blueprint || typeof data.blueprint !== "object" || Array.isArray(data.blueprint)) {
        return { ok: false, reason: "blueprint is missing or not an object." };
      }
      break;
    case "slot_picker":
      if (!Array.isArray(data.slots)) {
        return { ok: false, reason: "slots is missing or not an array." };
      }
      break;
    case "email_approval":
      if (typeof data.recipient_email !== "string") {
        return { ok: false, reason: "recipient_email is missing." };
      }
      break;
    case "meeting_approval":
      if (typeof data.attendee_email !== "string") {
        return { ok: false, reason: "attendee_email is missing." };
      }
      break;
    default:
      // Every other gate only needs a well-formed object; each card renders
      // its own optional fields defensively (matches the old components'
      // existing per-field guards, e.g. WbsApproval's normalizeRoleMap).
      break;
  }

  return { ok: true, data };
}
