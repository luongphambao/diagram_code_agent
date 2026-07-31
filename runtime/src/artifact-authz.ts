import { CONFIG } from "./config.js";

const AUTH_HEADER_NAMES = ["authorization", "x-auth-request-email", "x-auth-request-role"] as const;

export function threadIdFromArtifactKey(key: string): string | undefined {
  const parts = key.split(":");
  if (parts.length < 3) return undefined;
  parts.splice(-2, 2);
  const threadId = parts.join(":");
  return threadId || undefined;
}

export function forwardedArtifactAuthHeaders(
  headers: Record<string, string | string[] | undefined>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const name of AUTH_HEADER_NAMES) {
    const value = headers[name];
    if (typeof value === "string" && value) out[name] = value;
    else if (Array.isArray(value) && value.length > 0) out[name] = value[0];
  }
  return out;
}

export async function authorizeArtifactDownload(
  key: string,
  headers: Record<string, string | string[] | undefined>,
  fetchImpl: typeof fetch = fetch,
): Promise<{ ok: boolean; status: number }> {
  const threadId = threadIdFromArtifactKey(key);
  if (!threadId) return { ok: false, status: 404 };
  const url = `${CONFIG.backendUrl}/conversations/${encodeURIComponent(threadId)}/artifact-authz`;
  try {
    const response = await fetchImpl(url, {
      method: "GET",
      headers: forwardedArtifactAuthHeaders(headers),
    });
    return { ok: response.ok, status: response.ok ? 200 : response.status };
  } catch (error) {
    console.error(`[runtime] artifact authorization failed for ${threadId}:`, error);
    return { ok: false, status: 502 };
  }
}
