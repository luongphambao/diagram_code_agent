/**
 * The bottom 26px "instrument readout" (plan §D.1) — the live `activity`
 * string, elapsed time, and run metrics that today are buried inside
 * DiagramCanvas props with no persistent home. Also carries the two aria-live
 * regions from §E.6: streaming *text* is deliberately not announced
 * (per-token aria-live is unusable) — only run status transitions and errors.
 */
export default function StatusStrip({
  isRunning,
  activity,
  error,
  modelCalls,
}: {
  isRunning: boolean;
  activity: string | null;
  error: string | null;
  modelCalls?: number;
}) {
  return (
    <div className="flex h-[26px] flex-shrink-0 items-center gap-3 border-t border-line px-4 text-2xs text-muted">
      <span
        className={`inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full ${
          isRunning ? "animate-pulse motion-reduce:animate-none bg-accent" : "bg-line"
        }`}
        aria-hidden="true"
      />
      <span className="min-w-0 flex-1 truncate">{activity ?? (isRunning ? "Working…" : "Idle")}</span>
      {modelCalls != null && (
        <span className="tnum flex-shrink-0" title="Model calls this run">
          {modelCalls} calls
        </span>
      )}

      {/* aria-live regions — visually hidden, announce transitions only. */}
      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {isRunning ? `Working: ${activity ?? "thinking"}` : "Ready"}
      </div>
      <div role="alert" aria-live="assertive" className="sr-only">
        {error ?? ""}
      </div>
    </div>
  );
}
