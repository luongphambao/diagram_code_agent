import { describe, expect, it } from "vitest";
import { artifactStore, artifactUrl } from "../artifact-store.js";

function base64Of(text: string): string {
  return Buffer.from(text, "utf-8").toString("base64");
}

describe("ArtifactStore", () => {
  it("stores an artifact and retrieves the exact bytes back", () => {
    const b64 = base64Of("hello artifact");
    const key = artifactStore.put("t1", "png_base64", b64, "image/png", "diagram.png");
    const entry = artifactStore.get(key);
    expect(entry).toBeDefined();
    expect(entry?.bytes.toString("utf-8")).toBe("hello artifact");
    expect(entry?.mime).toBe("image/png");
    expect(entry?.filename).toBe("diagram.png");
  });

  it("dedupes identical bytes for the same thread+field into one key", () => {
    const b64 = base64Of("same content");
    const before = artifactStore.count();
    const key1 = artifactStore.put("t2", "pdf_base64", b64, "application/pdf", "report.pdf");
    const key2 = artifactStore.put("t2", "pdf_base64", b64, "application/pdf", "report.pdf");
    expect(key1).toBe(key2);
    expect(artifactStore.count()).toBe(before + 1);
  });

  it("different threads or fields never collide even with identical bytes", () => {
    const b64 = base64Of("shared bytes");
    const keyA = artifactStore.put("thread-a", "png_base64", b64, "image/png", "a.png");
    const keyB = artifactStore.put("thread-b", "png_base64", b64, "image/png", "b.png");
    const keyC = artifactStore.put("thread-a", "pdf_base64", b64, "application/pdf", "c.pdf");
    expect(new Set([keyA, keyB, keyC]).size).toBe(3);
  });

  it("returns undefined for an unknown key", () => {
    expect(artifactStore.get("nonexistent:key:here")).toBeUndefined();
  });

  it("artifactUrl produces a URL-encoded /api/artifacts/ path", () => {
    expect(artifactUrl("t:field:abc123")).toBe("/api/artifacts/t%3Afield%3Aabc123");
  });
});
