import { describe, expect, it } from "vitest";
import { substituteSnapshot, substituteStateDelta } from "../artifact-substitution.js";
import { artifactStore } from "../artifact-store.js";

function base64Of(text: string): string {
  return Buffer.from(text, "utf-8").toString("base64");
}

describe("substituteStateDelta", () => {
  it("replaces an artifact-field op's value with a descriptor, leaves other ops untouched", () => {
    const png = base64Of("fake png bytes");
    const delta = [
      { op: "add", path: "/current_step", value: "awaiting_techstack" },
      { op: "add", path: "/png_base64", value: png },
      { op: "add", path: "/drawio", value: "<mxfile/>" },
    ];
    const out = substituteStateDelta("thread-1", delta) as Array<Record<string, unknown>>;

    expect(out[0]).toEqual({ op: "add", path: "/current_step", value: "awaiting_techstack" });
    expect(out[2]).toEqual({ op: "add", path: "/drawio", value: "<mxfile/>" }); // drawio stays inline (text)

    const pngOp = out[1] as { value: { __artifact: string; mime: string; filename: string } };
    expect(pngOp.value.mime).toBe("image/png");
    expect(pngOp.value.filename).toBe("diagram.png");
    expect(pngOp.value.__artifact).toMatch(/^\/api\/artifacts\//);

    const key = decodeURIComponent(pngOp.value.__artifact.replace("/api/artifacts/", ""));
    expect(artifactStore.get(key)?.bytes.toString("utf-8")).toBe("fake png bytes");
  });

  it("passes through a non-array delta unchanged", () => {
    expect(substituteStateDelta("t", null)).toBeNull();
    expect(substituteStateDelta("t", { not: "an array" })).toEqual({ not: "an array" });
  });
});

describe("substituteSnapshot", () => {
  it("replaces all four artifact fields present in a snapshot, leaves everything else alone", () => {
    const snapshot = {
      current_step: "reviewing",
      png_base64: base64Of("png-bytes"),
      pdf_base64: base64Of("pdf-bytes"),
      pptx_base64: base64Of("pptx-bytes"),
      wbs_xlsx_base64: base64Of("xlsx-bytes"),
      drawio: "<mxfile/>",
      iteration: 2,
    };
    const out = substituteSnapshot("thread-2", snapshot) as Record<string, unknown>;

    expect(out.current_step).toBe("reviewing");
    expect(out.drawio).toBe("<mxfile/>");
    expect(out.iteration).toBe(2);
    for (const field of ["png_base64", "pdf_base64", "pptx_base64", "wbs_xlsx_base64"]) {
      const ref = out[field] as { __artifact: string };
      expect(ref.__artifact).toMatch(/^\/api\/artifacts\//);
    }
  });

  it("passes through non-object snapshots unchanged", () => {
    expect(substituteSnapshot("t", null)).toBeNull();
    expect(substituteSnapshot("t", "not an object")).toBe("not an object");
  });

  it("omits fields that aren't present rather than inventing empty descriptors", () => {
    const out = substituteSnapshot("thread-3", { current_step: "reviewing" }) as Record<string, unknown>;
    expect(out).toEqual({ current_step: "reviewing" });
  });
});
