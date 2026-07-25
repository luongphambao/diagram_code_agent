import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToolCallStatus } from "@copilotkit/core";
import { GATE_TYPES, GATE_REGISTRY, type GateType } from "../registry";
import { parseGatePayload } from "../parseGatePayload";
import UnknownGateCard from "../UnknownGateCard";

/** Golden args per gate — real card shapes copied from backend/src/session/
 * gate_decisions.py::_card_for (techstack_approval/blueprint_approval lifted
 * verbatim from test/fixtures/flow-full-design.json, the contract oracle;
 * the rest hand-built to the same exact field names/shapes since that
 * fixture only covers the design-flow gates). */
const GOLDEN_ARGS: Record<GateType, Record<string, unknown>> = {
  techstack_approval: {
    type: "techstack_approval",
    tech_stack: {
      backend: { choice: "Node.js", rationale: "Team familiarity.", alternatives: [] },
    },
    question: "Review the recommended tech stack.",
    assumptions: {},
    scaling_roadmap: [],
    estimated_total_monthly_cost_usd: { min_usd: 1000, max_usd: 2000 },
    allowed_decisions: ["approve", "approve_with_assumptions", "accept_risk", "request_evidence", "request_alternative", "reject"],
  },
  blueprint_approval: {
    type: "blueprint_approval",
    blueprint: { pattern: "layered", nodes: [], clusters: [], edges: [] },
    question: "Review the architecture blueprint.",
    allowed_decisions: ["approve", "approve_with_assumptions", "accept_risk", "request_evidence", "request_alternative", "reject"],
  },
  result_review: { type: "result_review", summary: "diagram summary", question: "Is the diagram good?", iteration: 1 },
  pdf_report_approval: {
    type: "pdf_report_approval",
    question: "Generate the PDF report?",
    title: "T",
    subtitle: "S",
    brand: "",
    include_sections: ["cover"],
    missing_sections: [],
    allowed_decisions: ["approve", "request_evidence", "reject"],
  },
  ppt_proposal_approval: {
    type: "ppt_proposal_approval",
    question: "Generate the BnK PowerPoint proposal?",
    title: "T",
    subtitle: "S",
    brand: "",
    include_sections: ["cover"],
    missing_sections: [],
    allowed_decisions: ["approve", "request_evidence", "reject"],
  },
  email_approval: {
    type: "email_approval",
    question: "Send the report?",
    recipient_email: "client@example.com",
    subject: "Report",
    project_name: "Project X",
    recipient_name: "Team",
    attachments: ["report.pdf"],
  },
  meeting_approval: {
    type: "meeting_approval",
    question: "Schedule this meeting?",
    title: "Kickoff",
    start_datetime: "2026-08-01T09:00:00+07:00",
    end_datetime: "2026-08-01T10:00:00+07:00",
    display_start: "Sat, 01 Aug 2026 09:00",
    display_end: "10:00",
    duration_minutes: 60,
    attendee_email: "client@example.com",
    attendee_name: "Client",
    add_google_meet: true,
    timezone: "Asia/Ho_Chi_Minh",
  },
  slot_picker: {
    type: "slot_picker",
    question: "Pick a time.",
    slots: [{ start: "2026-08-01T09:00:00", end: "2026-08-01T10:00:00", display_day: "Sat 01 Aug", display_time: "09:00-10:00" }],
    duration_minutes: 60,
    timezone: "Asia/Ho_Chi_Minh",
    context: "",
  },
  wbs_skeleton_approval: {
    type: "wbs_skeleton_approval",
    question: "Review the WBS structure.",
    project_name: "Project X",
    project_code: "PX-01",
    phases: [{ code: "P1", name: "Phase 1", modules: [{ code: "M1", name: "Module 1" }] }],
    allowed_decisions: ["approve", "request_alternative", "reject"],
  },
  wbs_approval: {
    type: "wbs_approval",
    question: "Review the WBS plan.",
    total_mandays: 100,
    total_manmonths: 5,
    timeline_weeks: 20,
    timeline_months: 5,
    effort_by_role: { BE: 40, QC: 20 },
    effort_by_module: [{ code: "M1", name: "Module 1", total_md: 20 }],
    allowed_decisions: ["approve", "approve_with_assumptions", "accept_risk", "request_alternative", "reject"],
  },
  wbs_excel_approval: {
    type: "wbs_excel_approval",
    question: "Generate the WBS Excel file?",
    total_mandays: 100,
    timeline_months: 5,
  },
  business_case_approval: {
    type: "business_case_approval",
    question: "Review the business case.",
    benefit_basis: "Manual ops hours saved",
    implementation_cost_usd: 50000,
    implementation_cost_source: "auto",
    annual_operating_cost_usd: 12000,
    annual_operating_cost_source: "auto",
    annual_benefit_usd: 40000,
    analysis_horizon_years: 3,
    computed: { roi_pct: 26.7, payback_period_years: 1.8, total_cost_usd: 86000, total_benefit_usd: 109000, net_benefit_usd: 23000, cash_flow_by_year: [] },
    allowed_decisions: ["approve", "approve_with_assumptions", "accept_risk", "request_evidence", "reject"],
  },
  delivery_export_approval: {
    type: "delivery_export_approval",
    question: "Push the WBS work items to Jira?",
    system: "jira",
    dry_run: true,
  },
};

describe("gate registry exhaustiveness", () => {
  it("has exactly one entry per GATE_TYPES, each with a label/tone/Card", () => {
    expect(Object.keys(GATE_REGISTRY).sort()).toEqual([...GATE_TYPES].sort());
    for (const type of GATE_TYPES) {
      const def = GATE_REGISTRY[type];
      expect(def.label).toBeTruthy();
      expect(["decision", "export", "comms", "danger"]).toContain(def.tone);
      expect(def.Card).toBeTruthy();
    }
  });

  it("every registered type parses its own golden args as ok", () => {
    for (const type of GATE_TYPES) {
      const parsed = parseGatePayload(type, GOLDEN_ARGS[type]);
      expect(parsed.ok, `${type} should parse its golden args`).toBe(true);
    }
  });
});

describe("gate card golden payloads", () => {
  it("techstack_approval: approve sends {action:approve, approved:true}", async () => {
    const user = userEvent.setup();
    const respond = vi.fn().mockResolvedValue(undefined);
    const { Card } = GATE_REGISTRY.techstack_approval;
    render(<Card toolCallId="tc1" args={GOLDEN_ARGS.techstack_approval} status={ToolCallStatus.Executing} respond={respond} />);
    await user.click(screen.getByRole("button", { name: /approve stack/i }));
    expect(respond).toHaveBeenCalledWith(expect.objectContaining({ action: "approve", approved: true }));
  });

  it("blueprint_approval: approve sends {action:approve, approved:true}", async () => {
    const user = userEvent.setup();
    const respond = vi.fn().mockResolvedValue(undefined);
    const { Card } = GATE_REGISTRY.blueprint_approval;
    render(<Card toolCallId="tc1" args={GOLDEN_ARGS.blueprint_approval} status={ToolCallStatus.Executing} respond={respond} />);
    await user.click(screen.getByRole("button", { name: /looks good! generate diagram/i }));
    expect(respond).toHaveBeenCalledWith(expect.objectContaining({ action: "approve", approved: true }));
  });

  it("result_review: approve sends {satisfied:true} (not action/approved — backend special-cases finalize_diagram)", async () => {
    const user = userEvent.setup();
    const respond = vi.fn().mockResolvedValue(undefined);
    const { Card } = GATE_REGISTRY.result_review;
    render(<Card toolCallId="tc1" args={GOLDEN_ARGS.result_review} status={ToolCallStatus.Executing} respond={respond} />);
    await user.click(screen.getByRole("button", { name: /looks great/i }));
    expect(respond).toHaveBeenCalledWith({ satisfied: true });
  });

  it("email_approval: approve sends {action:approve, approved:true}", async () => {
    const user = userEvent.setup();
    const respond = vi.fn().mockResolvedValue(undefined);
    const { Card } = GATE_REGISTRY.email_approval;
    render(<Card toolCallId="tc1" args={GOLDEN_ARGS.email_approval} status={ToolCallStatus.Executing} respond={respond} />);
    await user.click(screen.getByRole("button", { name: /send email/i }));
    expect(respond).toHaveBeenCalledWith({ action: "approve", approved: true });
  });

  it("meeting_approval: cancel sends {action:reject, approved:false}", async () => {
    const user = userEvent.setup();
    const respond = vi.fn().mockResolvedValue(undefined);
    const { Card } = GATE_REGISTRY.meeting_approval;
    render(<Card toolCallId="tc1" args={GOLDEN_ARGS.meeting_approval} status={ToolCallStatus.Executing} respond={respond} />);
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));
    expect(respond).toHaveBeenCalledWith({ action: "reject", approved: false });
  });

  it("slot_picker: confirm sends {action:approve, approved:true, selected_slot} (not an index)", async () => {
    const user = userEvent.setup();
    const respond = vi.fn().mockResolvedValue(undefined);
    const { Card } = GATE_REGISTRY.slot_picker;
    render(<Card toolCallId="tc1" args={GOLDEN_ARGS.slot_picker} status={ToolCallStatus.Executing} respond={respond} />);
    await user.click(screen.getByText("Sat 01 Aug"));
    await user.click(screen.getByRole("button", { name: /confirm this time/i }));
    expect(respond).toHaveBeenCalledWith({
      action: "approve",
      approved: true,
      selected_slot: (GOLDEN_ARGS.slot_picker.slots as unknown[])[0],
    });
  });

  it("wbs_skeleton_approval: approve sends {action:approve, approved:true}", async () => {
    const user = userEvent.setup();
    const respond = vi.fn().mockResolvedValue(undefined);
    const { Card } = GATE_REGISTRY.wbs_skeleton_approval;
    render(<Card toolCallId="tc1" args={GOLDEN_ARGS.wbs_skeleton_approval} status={ToolCallStatus.Executing} respond={respond} />);
    await user.click(screen.getByRole("button", { name: /approve structure/i }));
    expect(respond).toHaveBeenCalledWith(expect.objectContaining({ action: "approve", approved: true }));
  });

  it("wbs_approval: approve sends {action:approve, approved:true}", async () => {
    const user = userEvent.setup();
    const respond = vi.fn().mockResolvedValue(undefined);
    const { Card } = GATE_REGISTRY.wbs_approval;
    render(<Card toolCallId="tc1" args={GOLDEN_ARGS.wbs_approval} status={ToolCallStatus.Executing} respond={respond} />);
    await user.click(screen.getByRole("button", { name: /approve plan/i }));
    expect(respond).toHaveBeenCalledWith(expect.objectContaining({ action: "approve", approved: true }));
  });

  it("wbs_excel_approval: approve sends {action:approve, approved:true}", async () => {
    const user = userEvent.setup();
    const respond = vi.fn().mockResolvedValue(undefined);
    const { Card } = GATE_REGISTRY.wbs_excel_approval;
    render(<Card toolCallId="tc1" args={GOLDEN_ARGS.wbs_excel_approval} status={ToolCallStatus.Executing} respond={respond} />);
    await user.click(screen.getByRole("button", { name: /generate \.xlsx/i }));
    expect(respond).toHaveBeenCalledWith({ action: "approve", approved: true });
  });

  it("business_case_approval: approve sends {action:approve, approved:true}", async () => {
    const user = userEvent.setup();
    const respond = vi.fn().mockResolvedValue(undefined);
    const { Card } = GATE_REGISTRY.business_case_approval;
    render(<Card toolCallId="tc1" args={GOLDEN_ARGS.business_case_approval} status={ToolCallStatus.Executing} respond={respond} />);
    await user.click(screen.getByRole("button", { name: /approve business case/i }));
    expect(respond).toHaveBeenCalledWith({ action: "approve", approved: true });
  });

  it("delivery_export_approval: approve sends {action:approve, approved:true}", async () => {
    const user = userEvent.setup();
    const respond = vi.fn().mockResolvedValue(undefined);
    const { Card } = GATE_REGISTRY.delivery_export_approval;
    render(<Card toolCallId="tc1" args={GOLDEN_ARGS.delivery_export_approval} status={ToolCallStatus.Executing} respond={respond} />);
    await user.click(screen.getByRole("button", { name: /build preview/i }));
    expect(respond).toHaveBeenCalledWith({ action: "approve", approved: true });
  });

  it("pdf_report_approval: approve sends {action:approve, approved:true}", async () => {
    const user = userEvent.setup();
    const respond = vi.fn().mockResolvedValue(undefined);
    const { Card } = GATE_REGISTRY.pdf_report_approval;
    render(<Card toolCallId="tc1" args={GOLDEN_ARGS.pdf_report_approval} status={ToolCallStatus.Executing} respond={respond} />);
    await user.click(screen.getByRole("button", { name: /generate pdf/i }));
    expect(respond).toHaveBeenCalledWith(expect.objectContaining({ action: "approve", approved: true }));
  });

  it("ppt_proposal_approval: approve sends {action:approve, approved:true}", async () => {
    const user = userEvent.setup();
    const respond = vi.fn().mockResolvedValue(undefined);
    const { Card } = GATE_REGISTRY.ppt_proposal_approval;
    render(<Card toolCallId="tc1" args={GOLDEN_ARGS.ppt_proposal_approval} status={ToolCallStatus.Executing} respond={respond} />);
    await user.click(screen.getByRole("button", { name: /generate ppt/i }));
    expect(respond).toHaveBeenCalledWith(expect.objectContaining({ action: "approve", approved: true }));
  });
});

describe("malformed payload fallback (parseGatePayload)", () => {
  const cases: Array<{ type: GateType; bad: unknown; reason: RegExp }> = [
    { type: "techstack_approval", bad: { type: "techstack_approval", question: "x" }, reason: /tech_stack/ },
    { type: "blueprint_approval", bad: { type: "blueprint_approval", question: "x" }, reason: /blueprint/ },
    { type: "slot_picker", bad: { type: "slot_picker", question: "x" }, reason: /slots/ },
    { type: "email_approval", bad: { type: "email_approval", question: "x" }, reason: /recipient_email/ },
    { type: "meeting_approval", bad: { type: "meeting_approval", question: "x" }, reason: /attendee_email/ },
  ];

  it.each(cases)("$type: missing required field -> ok:false", ({ type, bad, reason }) => {
    const parsed = parseGatePayload(type, bad);
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) expect(parsed.reason).toMatch(reason);
  });

  it("null/non-object args always fail", () => {
    expect(parseGatePayload("techstack_approval", null).ok).toBe(false);
    expect(parseGatePayload("email_approval", "not an object").ok).toBe(false);
    expect(parseGatePayload("wbs_approval", ["array", "not", "object"]).ok).toBe(false);
  });

  it("UnknownGateCard still resolves via respond on both Approve anyway and Cancel", async () => {
    const user = userEvent.setup();
    const approveRespond = vi.fn().mockResolvedValue(undefined);
    const { unmount } = render(
      <UnknownGateCard label="Tech Stack Recommendation" reason="tech_stack is missing." rawArgs={{ question: "x" }} status={ToolCallStatus.Executing} respond={approveRespond} />,
    );
    await user.click(within(screen.getByRole("group")).getByRole("button", { name: /approve anyway/i }));
    expect(approveRespond).toHaveBeenCalledWith({ action: "approve", approved: true });
    unmount();

    const cancelRespond = vi.fn().mockResolvedValue(undefined);
    render(<UnknownGateCard label="Tech Stack Recommendation" reason="tech_stack is missing." rawArgs={{ question: "x" }} status={ToolCallStatus.Executing} respond={cancelRespond} />);
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));
    expect(cancelRespond).toHaveBeenCalledWith(expect.objectContaining({ action: "reject", approved: false }));
  });
});
