/** Pure utilities and shared types for the diagram agent hooks. */

export const BACKEND_URL =
  (import.meta.env.VITE_BACKEND_URL as string | undefined) ??
  "http://localhost:8001";

// ---- Shared domain types ---- //

export interface LogEntry {
  t: number;
  type: "llm" | "tool_start" | "tool_end";
  model?: string;
  turn?: number;
  tool?: string;
  label?: string;
  input?: string;
  output?: string;
  elapsed_s?: number;
  error?: string;
  subagent?: string;
  ok?: boolean;
}

export interface TechAlternative {
  name: string;
  why_rejected?: string;
  criteria?: Record<string, number>;
}

export interface CostRange {
  min_usd: number;
  max_usd: number;
}

export interface TechRisk {
  risk: string;
  mitigation?: string;
}

export interface UserScaleAssumptions {
  mau?: number;
  dau?: number;
  peak_concurrent?: number;
  peak_rps?: number;
  growth_rate_yoy_pct?: number;
}

export interface DataAssumptions {
  initial_gb?: number;
  growth_gb_per_month?: number;
  read_write_ratio?: string;
}

export interface TeamAssumptions {
  size?: number;
  skill_level?: string;
  devops_maturity?: string;
}

export interface SolutionAssumptions {
  budget_tier?: string;
  monthly_budget_range_usd?: CostRange;
  users?: UserScaleAssumptions;
  data?: DataAssumptions;
  team?: TeamAssumptions;
  project_phase?: string;
  availability_target?: string;
  latency_target_p99_ms?: number;
  compliance?: string[];
  primary_region?: string;
  confirm_with_customer?: string[];
}

export interface ScalingPhase {
  phase: string;
  trigger?: string;
  changes?: string[];
  est_monthly_cost_usd?: CostRange;
}

export interface TechStackLayer {
  choice: string;
  rationale: string;
  cost_tier?: string;
  decision_criteria?: Record<string, number>;
  alternatives: Array<string | TechAlternative>;
  estimated_monthly_cost_usd?: CostRange;
  capacity_sizing?: string;
  performance_target?: string;
  risks?: TechRisk[];
}

export interface DiagramBrief {
  objective: string;
  application_type?: string;
  scale_level?: string;
  security_level?: string;
  provider_preference?: string;
  analysis_signals?: string[];
  stakeholders?: string[];
  functional_requirements?: string[];
  non_functional_requirements?: string[];
  layout_constraints?: string[];
  assumptions?: string[];
}

export interface ArchitectureAnalysis {
  application_type: string;
  scale_level: string;
  security_level: string;
  provider_preference?: string;
  detected_capabilities: string[];
  constraints: string[];
  suggested_patterns: Array<{
    pattern: string;
    fit: "high" | "medium" | "low";
    score: number;
    reasons: string[];
  }>;
  concerns: string[];
}

export interface Blueprint {
  audience?: string;
  detail_level?: string;
  layout_intent?: string;
  presentation_style?: "slide" | "diagram";
  slide_title?: string;
  slide_kicker?: string;
  brand?: string;
  diagram_title?: string;
  pattern: string;
  pattern_rationale?: string;
  key_decisions?: Array<string | {
    decision?: string;
    rationale?: string;
    tradeoffs?: string[] | string;
  }>;
  nodes: Array<{ id: string; label: string; tech?: string; cluster?: string; type?: string }>;
  clusters: Array<{ id: string; label: string; tier?: string }>;
  edges: Array<{ from: string; to: string; label?: string; protocol?: string }>;
  pillar_coverage?: Record<string, { addressed_by?: string[]; gaps?: string[] }>;
  nfr_mapping?: Array<{ nfr: string; mechanism?: string; node_ids?: string[] }>;
}

export interface Delegation {
  id: string;
  subagent: string;
  description: string;
  status: "running" | "completed" | "error";
  result?: string | null;
  current_tool?: string;
  current_label?: string;
  current_detail?: string;
}

export interface WbsSummary {
  total_mandays: number;
  total_manmonths: number;
  effort_by_role: Record<string, number>;
  weeks: number;
  months: number;
  effort_by_module: Array<{ code: string; name: string; total_md: number }>;
}

/**
 * Format a man-day value that MIGHT arrive as a string. Backend defaults these to 0,
 * but a stringified number from the model would make a bare `.toFixed(1)` throw
 * ("Cannot read properties of undefined") and crash the whole message list / WBS tab.
 * Coerce → number, fall back to "0.0" for anything non-numeric.
 */
export function fmtMd(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  return (Number.isFinite(n) ? n : 0).toFixed(1);
}

// Governance read-outs surfaced in the canvas "Quality" tab (display-only).
export interface QualitySnapshot {
  solution_revision?: number;
  quality_score?: number;
  quality_grade?: string;
  score_breakdown?: Record<string, number>;
  total_findings?: number;
  findings_open?: number;
  findings_waived?: number;
  findings_resolved?: number;
  findings_by_dimension?: Record<string, number>;
  findings_by_severity?: Record<string, number>;
  total_decisions?: number;
  total_evidence?: number;
  evidence_coverage_pct?: number;
  total_assumptions?: number;
  assumptions_confirmed?: number;
  assumption_confirmation_pct?: number;
  total_risks?: number;
  risk_mitigation_pct?: number;
  total_tokens?: number;
  model_calls?: number;
}

export interface DriftEntry { id: string; name: string; kind: string }

export interface DriftReport {
  summary?: {
    designed?: number;
    observed?: number;
    matched?: number;
    in_design_not_in_reality?: number;
    in_reality_not_in_design?: number;
  };
  in_design_not_in_reality?: DriftEntry[];
  in_reality_not_in_design?: DriftEntry[];
  matched?: DriftEntry[];
  remediation?: string[];
}

export interface ComplianceControl {
  id: string;
  name: string;
  kind: string;
  standard_ref: string;
  status: string;
  grounded: boolean;
  implemented: boolean;
}

export interface ComplianceState {
  pack: string;
  controls: ComplianceControl[];
}

export interface LastMeeting {
  title: string;
  start_datetime: string;
  end_datetime: string;
  timezone: string;
  attendee_email: string;
  attendee_name: string;
  event_link: string;
  meet_link: string;
}

export interface AgentState {
  current_step?: string;
  iteration?: number;
  png_base64?: string;
  pdf_base64?: string;
  pptx_base64?: string;
  wbs_xlsx_base64?: string;
  wbs_summary?: WbsSummary;
  drawio?: string;
  code?: string;
  summary?: string;
  error?: string;
  logs?: LogEntry[];
  architecture_analysis?: ArchitectureAnalysis;
  diagram_brief?: DiagramBrief;
  tech_stack?: Record<string, TechStackLayer>;
  blueprint?: Blueprint;
  delegations?: Delegation[];
  activeSubagent?: string;
  quality?: QualitySnapshot;
  drift?: DriftReport;
  compliance?: ComplianceState;
  last_meeting?: LastMeeting;
}

export type InterruptType =
  | "brief_approval"
  | "techstack_approval"
  | "blueprint_approval"
  | "result_review"
  | "pdf_report_approval"
  | "ppt_proposal_approval"
  | "email_approval"
  | "slot_picker"
  | "meeting_approval"
  | "wbs_skeleton_approval"
  | "wbs_approval"
  | "wbs_excel_approval"
  | "delivery_export_approval";

export interface PendingInterrupt {
  toolCallId: string;
  data: {
    type: InterruptType;
    question: string;
    brief?: DiagramBrief;
    tech_stack?: Record<string, TechStackLayer>;
    assumptions?: SolutionAssumptions;
    scaling_roadmap?: ScalingPhase[];
    estimated_total_monthly_cost_usd?: CostRange;
    blueprint?: Blueprint;
    summary?: string;
    iteration?: number;
    title?: string;
    subtitle?: string;
    brand?: string;
    include_sections?: string[];
    missing_sections?: string[];
    recipient_email?: string;
    subject?: string;
    project_name?: string;
    recipient_name?: string;
    slots?: Array<{
      start: string;
      end: string;
      display_day: string;
      display_time: string;
    }>;
    context?: string;
    start_datetime?: string;
    end_datetime?: string;
    display_start?: string;
    display_end?: string;
    duration_minutes?: number;
    attendee_email?: string;
    attendee_name?: string;
    description?: string;
    add_google_meet?: boolean;
    timezone?: string;
    phases?: Array<{code: string; name: string; modules?: Array<{code: string; name: string}>}>;
    project_code?: string;
    total_mandays?: number;
    total_manmonths?: number;
    timeline_weeks?: number;
    timeline_months?: number;
    effort_by_role?: Record<string, number>;
    effort_by_module?: Array<{code: string; name: string; total_md: number}>;
    // Delivery export gate (export_to_delivery).
    system?: string;
    dry_run?: boolean;
    // HITL v2: the trade-off actions this gate offers (drives DecisionActions).
    allowed_decisions?: DecisionAction[];
  };
}

// Role the user acts in at a gate (mirrors backend tools.ROLE_GATE_PERMISSIONS, §8.6).
// Sent on every /agui request as `userRole`; the backend enforces gate role policy.
export type UserRole = "viewer" | "pm" | "lead" | "admin";

// HITL v2 decision actions (mirror backend tools.GATE_DECISIONS).
export type DecisionAction =
  | "approve"
  | "reject"
  | "approve_with_assumptions"
  | "accept_risk"
  | "request_evidence"
  | "request_alternative";

// Payload posted back to the gate for a HITL v2 action.
export interface DecisionPayload {
  action: DecisionAction;
  approved?: boolean;
  comment?: string;
  assumption_ids?: string[];
  statement?: string;
  owner?: string;
  mitigation?: string;
  claim?: string;
  source_expectation?: string;
  option_comparison?: string;
  constraint_change?: string;
}

export interface UploadedFile {
  file_id: string;
  filename: string;
  kind: string;
  char_count: number;
  preview?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

export interface WireMessage {
  id: string;
  role: string;
  content: string;
  toolCallId?: string;
}

// A HITL gate that has been resolved — kept in the chat timeline instead of
// vanishing once `pendingInterrupt` is cleared (§ frontend chat/HITL persistence).
export interface ResolvedGate {
  id: string; // toolCallId
  data: PendingInterrupt["data"];
  decision: Record<string, unknown>;
  resolvedAt: number;
  // Number of chat messages that existed when this gate resolved — anchors it
  // to the right spot in the merged chat/gate timeline (see MessageList).
  afterMessageIndex: number;
}

// The backend doesn't persist the original gate-card payload (only the decision
// wire-message), so the resolved-gate timeline is persisted client-side, per thread.
const GATE_HISTORY_PREFIX = "diagram_agent_gate_history_";

export function loadGateHistory(threadId: string): ResolvedGate[] {
  try {
    const raw = localStorage.getItem(GATE_HISTORY_PREFIX + threadId);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveGateHistory(threadId: string, history: ResolvedGate[]): void {
  try {
    if (history.length === 0) {
      localStorage.removeItem(GATE_HISTORY_PREFIX + threadId);
    } else {
      localStorage.setItem(GATE_HISTORY_PREFIX + threadId, JSON.stringify(history));
    }
  } catch { /* storage unavailable/full — history stays in-memory for the session */ }
}

export function clearGateHistory(threadId: string): void {
  try { localStorage.removeItem(GATE_HISTORY_PREFIX + threadId); } catch { /* ignore */ }
}
