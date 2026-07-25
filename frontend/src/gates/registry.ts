import type { ComponentType } from "react";
import type { GateTone } from "./GateFrame";
import type { GateCardProps } from "./types";
import TechStackCard from "./cards/TechStackCard";
import BlueprintCard from "./cards/BlueprintCard";
import ResultReviewCard from "./cards/ResultReviewCard";
import PdfReportCard from "./cards/PdfReportCard";
import PptProposalCard from "./cards/PptProposalCard";
import EmailCard from "./cards/EmailCard";
import MeetingCard from "./cards/MeetingCard";
import SlotPickerCard from "./cards/SlotPickerCard";
import WbsSkeletonCard from "./cards/WbsSkeletonCard";
import WbsCard from "./cards/WbsCard";
import WbsExcelCard from "./cards/WbsExcelCard";
import BusinessCaseCard from "./cards/BusinessCaseCard";
import DeliveryExportCard from "./cards/DeliveryExportCard";

/**
 * The 13 real backend gate names (backend/src/session/gate_decisions.py::
 * _card_for's `card["type"]` values — the exact string chat.py:879 sends as
 * `toolCallName`, which IS the whole binding: `name` in each
 * useHumanInTheLoop registration below must equal one of these). Plan §F
 * corrections baked in: `brief_approval` dropped (BriefApproval.tsx was
 * never mounted — no `_card_for` branch produces it), `business_case_approval`
 * added (backend gate with no prior frontend component).
 */
export const GATE_TYPES = [
  "techstack_approval",
  "blueprint_approval",
  "result_review",
  "pdf_report_approval",
  "ppt_proposal_approval",
  "email_approval",
  "meeting_approval",
  "slot_picker",
  "wbs_skeleton_approval",
  "wbs_approval",
  "wbs_excel_approval",
  "business_case_approval",
  "delivery_export_approval",
] as const;

export type GateType = (typeof GATE_TYPES)[number];

export interface GateDefinition {
  label: string;
  tone: GateTone;
  Card: ComponentType<GateCardProps>;
}

// `satisfies` (not `: Record<...>`) so a missing/extra key is a compile
// error against GATE_TYPES — the exhaustiveness check plan §F asks for,
// verified again at runtime by registry.test.tsx.
export const GATE_REGISTRY = {
  techstack_approval: { label: "Tech Stack Recommendation", tone: "decision", Card: TechStackCard },
  blueprint_approval: { label: "Architecture Blueprint", tone: "decision", Card: BlueprintCard },
  result_review: { label: "Diagram Review", tone: "decision", Card: ResultReviewCard },
  pdf_report_approval: { label: "PDF Report", tone: "export", Card: PdfReportCard },
  ppt_proposal_approval: { label: "PPT Proposal", tone: "export", Card: PptProposalCard },
  email_approval: { label: "Email", tone: "comms", Card: EmailCard },
  meeting_approval: { label: "Meeting", tone: "comms", Card: MeetingCard },
  slot_picker: { label: "Meeting Slot", tone: "comms", Card: SlotPickerCard },
  wbs_skeleton_approval: { label: "WBS Skeleton", tone: "decision", Card: WbsSkeletonCard },
  wbs_approval: { label: "WBS Plan", tone: "decision", Card: WbsCard },
  wbs_excel_approval: { label: "WBS Excel Export", tone: "export", Card: WbsExcelCard },
  business_case_approval: { label: "Business Case", tone: "decision", Card: BusinessCaseCard },
  delivery_export_approval: { label: "Delivery Export", tone: "export", Card: DeliveryExportCard },
} satisfies Record<GateType, GateDefinition>;
