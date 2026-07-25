import type { AgentState } from "../hooks/agent-utils";
import { downloadBase64File, downloadBlob, MIME_TYPES } from "../lib/downloadBase64";

export interface ExportDescriptor {
  id: "png" | "drawio" | "pdf" | "ppt" | "wbs";
  label: string;
  mime: string;
  ext: string;
  basename: string;
  kind: "base64" | "text";
  select: (state: AgentState) => string | undefined;
}

/**
 * Declarative export table (plan §G) replacing ArtifactTabs.tsx's four
 * hand-rolled base64-to-Blob functions and the double 5-level ternary for
 * which button is enabled/which handler it calls. Adding a new exportable
 * artifact is one array entry, not a new function plus two ternary branches.
 */
export const EXPORTS: ExportDescriptor[] = [
  { id: "png", label: "PNG", mime: MIME_TYPES.png, ext: "png", basename: "diagram", kind: "base64", select: (s) => s.png_base64 },
  { id: "drawio", label: ".drawio", mime: MIME_TYPES.drawio, ext: "drawio", basename: "diagram", kind: "text", select: (s) => s.drawio },
  { id: "pdf", label: "PDF", mime: MIME_TYPES.pdf, ext: "pdf", basename: "architecture_report", kind: "base64", select: (s) => s.pdf_base64 },
  { id: "ppt", label: "PPT", mime: MIME_TYPES.pptx, ext: "pptx", basename: "architecture_proposal", kind: "base64", select: (s) => s.pptx_base64 },
  { id: "wbs", label: "WBS", mime: MIME_TYPES.xlsx, ext: "xlsx", basename: "wbs", kind: "base64", select: (s) => s.wbs_xlsx_base64 },
];

function versionedName(base: string, ext: string, iteration?: number): string {
  return `${base}${iteration && iteration > 1 ? `_v${iteration}` : ""}.${ext}`;
}

export function downloadExport(descriptor: ExportDescriptor, state: AgentState): void {
  const value = descriptor.select(state);
  if (!value) return;
  const filename = versionedName(descriptor.basename, descriptor.ext, state.iteration);
  if (descriptor.kind === "text") {
    downloadBlob(new Blob([value], { type: descriptor.mime }), filename);
  } else {
    downloadBase64File(value, filename, descriptor.mime);
  }
}

/** `drawio` is text, not base64 — it needs to reach draw.io's URL-fragment
 * loader as raw XML (encodeURIComponent), so it stays outside the
 * descriptor's uniform download path (plan §G). */
export function openInDrawio(state: AgentState): void {
  if (!state.drawio) return;
  window.open(`https://app.diagrams.net/?src=about#U${encodeURIComponent(state.drawio)}`, "_blank");
}
