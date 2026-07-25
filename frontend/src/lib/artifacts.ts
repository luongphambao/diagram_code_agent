/** Mirrors runtime/src/artifact-substitution.ts's descriptor shape (plan
 * §A.6, Stage 6). Once the runtime offloads a big base64 field, the browser
 * never sees the bytes at all — just this small pointer. */
export interface ArtifactRef {
  __artifact: string;
  mime: string;
  filename: string;
}

export type Base64OrArtifact = string | ArtifactRef;

export function isArtifactRef(value: unknown): value is ArtifactRef {
  return !!value && typeof value === "object" && "__artifact" in (value as object);
}

/**
 * Resolves either shape to something usable directly as an `<img>`/`<iframe>`
 * `src` — a base64 string becomes an inline `data:` URL (the pre-offload
 * shape, still valid if the runtime ever falls back to it), an artifact
 * descriptor is already a real same-origin URL, so no `atob` main-thread
 * work is needed at all (plan §A.6: "removing the atob jank").
 */
export function resolveSrc(value: Base64OrArtifact | undefined, mime: string): string | undefined {
  if (!value) return undefined;
  if (isArtifactRef(value)) return value.__artifact;
  return `data:${mime};base64,${value}`;
}
