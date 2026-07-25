import { artifactStore, artifactUrl } from "./artifact-store.js";

/** The four multi-MB base64 fields worth offloading (plan §A.6). `drawio`
 * stays inline — it's text needed verbatim in `openInDrawio`'s URL
 * fragment, not a binary blob a browser fetches. */
const ARTIFACT_FIELDS: Record<string, { mime: string; filename: string }> = {
  png_base64: { mime: "image/png", filename: "diagram.png" },
  pdf_base64: { mime: "application/pdf", filename: "architecture_report.pdf" },
  pptx_base64: {
    mime: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    filename: "architecture_proposal.pptx",
  },
  wbs_xlsx_base64: {
    mime: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    filename: "wbs.xlsx",
  },
};

export interface ArtifactDescriptor {
  __artifact: string;
  mime: string;
  filename: string;
}

function substituteValue(threadId: string, field: string, value: unknown): unknown {
  const meta = ARTIFACT_FIELDS[field];
  if (!meta || typeof value !== "string" || !value) return value;
  const key = artifactStore.put(threadId, field, value, meta.mime, meta.filename);
  const descriptor: ArtifactDescriptor = { __artifact: artifactUrl(key), mime: meta.mime, filename: meta.filename };
  return descriptor;
}

interface JsonPatchOp {
  op: string;
  path: string;
  value?: unknown;
}

function isJsonPatchOp(v: unknown): v is JsonPatchOp {
  return !!v && typeof v === "object" && typeof (v as JsonPatchOp).path === "string";
}

/** Substitutes any STATE_DELTA op whose path targets one of the artifact
 * fields (`chat.py` emits these as flat `{op:"add", path:"/png_base64", ...}`
 * ops — see routers/chat.py:870-876). */
export function substituteStateDelta(threadId: string, delta: unknown): unknown {
  if (!Array.isArray(delta)) return delta;
  return delta.map((op) => {
    if (!isJsonPatchOp(op)) return op;
    const field = op.path.replace(/^\//, "");
    if (!(field in ARTIFACT_FIELDS)) return op;
    return { ...op, value: substituteValue(threadId, field, op.value) };
  });
}

/** Substitutes artifact fields inside a full STATE_SNAPSHOT (connect()'s
 * history replay, or a fresh RUN's snapshot). */
export function substituteSnapshot(threadId: string, snapshot: unknown): unknown {
  if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) return snapshot;
  const out: Record<string, unknown> = { ...(snapshot as Record<string, unknown>) };
  for (const field of Object.keys(ARTIFACT_FIELDS)) {
    if (field in out) out[field] = substituteValue(threadId, field, out[field]);
  }
  return out;
}
