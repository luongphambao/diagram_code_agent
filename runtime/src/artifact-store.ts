import { createHash } from "node:crypto";

export interface StoredArtifact {
  bytes: Buffer;
  mime: string;
  filename: string;
  storedAt: number;
}

const MAX_BYTES = 512 * 1024 * 1024;
const TTL_MS = 30 * 60 * 1000;

/**
 * Bounded LRU for the multi-MB base64 artifacts (png/pdf/pptx/xlsx) that
 * `handle-run.ts`'s `agent.setState(input.state)` would otherwise post back
 * to the runtime on EVERY turn (plan §A.6) — 5-15MB per run once all four
 * exist. Keyed `${threadId}:${field}:${sha1(bytes).slice(0,12)}` so a
 * re-approved/regenerated artifact with identical bytes reuses the same
 * entry instead of growing the store, and different artifacts never
 * collide. `drawio` is deliberately NOT offloaded here — it's text, and
 * `openInDrawio` needs it inline in a URL fragment, not behind a fetch.
 *
 * Single-instance, in-memory (plan R3): a multi-replica deployment would
 * need sticky sessions by `threadId` or a shared store (Redis) — fine for
 * this single-replica internal tool; documented in runtime/README.md.
 */
class ArtifactStore {
  private readonly map = new Map<string, StoredArtifact>(); // Map iteration order = insertion order, used as the LRU ordering.
  private totalBytes = 0;

  private evictExpired(): void {
    const now = Date.now();
    for (const [key, entry] of this.map) {
      if (now - entry.storedAt > TTL_MS) {
        this.totalBytes -= entry.bytes.length;
        this.map.delete(key);
      }
    }
  }

  private evictLru(): void {
    while (this.totalBytes > MAX_BYTES && this.map.size > 0) {
      const oldestKey = this.map.keys().next().value;
      if (oldestKey === undefined) break;
      const entry = this.map.get(oldestKey);
      if (entry) this.totalBytes -= entry.bytes.length;
      this.map.delete(oldestKey);
    }
  }

  /** Stores (or dedupes) one artifact and returns its lookup key. */
  put(threadId: string, field: string, base64: string, mime: string, filename: string): string {
    this.evictExpired();
    const bytes = Buffer.from(base64, "base64");
    const hash = createHash("sha1").update(bytes).digest("hex").slice(0, 12);
    const key = `${threadId}:${field}:${hash}`;

    const existing = this.map.get(key);
    if (existing) {
      // Touch for recency (re-insert moves it to the end of iteration order).
      this.map.delete(key);
      this.map.set(key, { ...existing, storedAt: Date.now() });
      return key;
    }

    this.map.set(key, { bytes, mime, filename, storedAt: Date.now() });
    this.totalBytes += bytes.length;
    this.evictLru();
    return key;
  }

  get(key: string): StoredArtifact | undefined {
    const entry = this.map.get(key);
    if (!entry) return undefined;
    if (Date.now() - entry.storedAt > TTL_MS) {
      this.totalBytes -= entry.bytes.length;
      this.map.delete(key);
      return undefined;
    }
    this.map.delete(key);
    this.map.set(key, entry);
    return entry;
  }

  /** Total bytes currently retained — for the Stage 6 bounded-memory check. */
  byteSize(): number {
    return this.totalBytes;
  }

  count(): number {
    return this.map.size;
  }
}

export const artifactStore = new ArtifactStore();

export function artifactUrl(key: string): string {
  return `/api/artifacts/${encodeURIComponent(key)}`;
}
