/** Loading placeholder — respects prefers-reduced-motion via the global rule
 * in index.css (the pulse animation is disabled there, not per-component). */
export default function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-sm bg-well ${className}`} aria-hidden="true" />;
}
