/** Single source of truth for env parsing — see plan §A.4/A.10. */

function parseOrigins(raw: string | undefined): string[] {
  if (!raw) return [];
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export const CONFIG = {
  /** Server-to-server URL inside the compose network — NOT the browser URL.
   *  Defaults to localhost for bare `npm run dev` outside Docker. */
  backendUrl: (process.env.BACKEND_URL ?? "http://localhost:8001").replace(/\/+$/, ""),
  port: Number(process.env.PORT ?? 3001),
  allowedOrigins: parseOrigins(process.env.ALLOWED_ORIGINS),
  /**
   * Byte-identity assertion (plan §B.3): compares the last `role==="user"`
   * message before and after sanitizeMessages() and throws on mismatch.
   * On by default everywhere except when explicitly disabled — this guards
   * the backend's fragile follow-up-phrase heuristics (chat.py:314-494)
   * against any future CopilotKit upgrade that starts mutating messages.
   */
  assertMessageIntegrity: process.env.ASSERT_MESSAGE_INTEGRITY !== "0",
} as const;
