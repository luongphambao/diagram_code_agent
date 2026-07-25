import { ToolCallStatus } from "@copilotkit/core";
import GateFrame from "./GateFrame";
import Button from "../ui/Button";

interface UnknownGateCardProps {
  label: string;
  reason: string;
  rawArgs: unknown;
  status: ToolCallStatus;
  respond: ((result: unknown) => Promise<void>) | undefined;
}

/**
 * Malformed-payload fallback (plan §F, ported from CopilotKit's own
 * interrupts-langgraph example). The essential property: THE FALLBACK
 * STILL RESOLVES, so a schema drift on the Python side can't wedge the
 * agent forever — "Approve anyway" and "Cancel" both call `respond`,
 * exactly like a normal gate would.
 */
export default function UnknownGateCard({ label, reason, rawArgs, status, respond }: UnknownGateCardProps) {
  function decide(payload: Record<string, unknown>) {
    void respond?.(payload);
  }

  return (
    <GateFrame label={label} tone="danger" status={status}>
      <p className="text-sm text-secondary">
        This gate's data could not be read: <span className="text-danger-text">{reason}</span>
      </p>
      <details className="text-xs">
        <summary className="cursor-pointer text-muted hover:text-secondary">Raw payload</summary>
        <pre className="mt-2 max-h-64 overflow-auto rounded-sm bg-well p-2 font-mono text-code text-secondary">
          {JSON.stringify(rawArgs, null, 2)}
        </pre>
      </details>
      <div className="flex gap-2">
        <Button variant="primary" size="sm" onClick={() => decide({ action: "approve", approved: true })}>
          Approve anyway
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() =>
            decide({ action: "reject", approved: false, feedback: "Malformed gate payload — please regenerate." })
          }
        >
          Cancel
        </Button>
      </div>
    </GateFrame>
  );
}
