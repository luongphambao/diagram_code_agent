/** Shared helpers for turning a base64 payload into a downloadable/openable Blob. */

function base64ToObjectUrl(base64: string, mime: string): string {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  return URL.createObjectURL(new Blob([bytes], { type: mime }));
}

/**
 * Revoking synchronously right after `a.click()` races the download in
 * Firefox (the click's navigation hasn't started reading the blob yet),
 * which can yield a zero-byte file — a latent bug across all four of
 * ArtifactTabs.tsx's original hand-rolled download functions (plan §G).
 * `queueMicrotask` defers the revoke to the next microtask, after the
 * synchronous click has been dispatched.
 */
export function downloadBase64File(base64: string, filename: string, mime: string): void {
  const url = base64ToObjectUrl(base64, mime);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  queueMicrotask(() => URL.revokeObjectURL(url));
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  queueMicrotask(() => URL.revokeObjectURL(url));
}

export function openBase64InNewTab(base64: string, mime: string): void {
  const url = base64ToObjectUrl(base64, mime);
  window.open(url, "_blank", "noopener,noreferrer");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export const MIME_TYPES = {
  png: "image/png",
  pdf: "application/pdf",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  drawio: "application/xml",
} as const;
