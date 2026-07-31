import { describe, expect, it, vi } from "vitest";
import {
  authorizeArtifactDownload,
  forwardedArtifactAuthHeaders,
  threadIdFromArtifactKey,
} from "../artifact-authz.js";

describe("artifact authorization", () => {
  it("extracts thread ids without assuming they contain no colons", () => {
    expect(threadIdFromArtifactKey("tenant:thread:png_base64:deadbeef")).toBe("tenant:thread");
    expect(threadIdFromArtifactKey("invalid")).toBeUndefined();
  });

  it("forwards only the backend identity headers", () => {
    expect(
      forwardedArtifactAuthHeaders({
        authorization: "Bearer token",
        "x-auth-request-email": "alice@bnk.vn",
        cookie: "secret=not-forwarded",
      }),
    ).toEqual({
      authorization: "Bearer token",
      "x-auth-request-email": "alice@bnk.vn",
    });
  });

  it("authorizes against the owning thread before serving bytes", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    const result = await authorizeArtifactDownload(
      "thread-1:png_base64:deadbeef",
      { "x-auth-request-email": "alice@bnk.vn" },
      fetchMock as typeof fetch,
    );

    expect(result).toEqual({ ok: true, status: 200 });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/conversations/thread-1/artifact-authz"),
      expect.objectContaining({ headers: { "x-auth-request-email": "alice@bnk.vn" } }),
    );
  });

  it("fails closed on ownership denial or backend failure", async () => {
    const denied = vi.fn(async () => new Response("not found", { status: 404 }));
    expect(
      await authorizeArtifactDownload("thread-1:pdf_base64:deadbeef", {}, denied as typeof fetch),
    ).toEqual({ ok: false, status: 404 });

    const unavailable = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    });
    expect(
      await authorizeArtifactDownload("thread-1:pdf_base64:deadbeef", {}, unavailable as typeof fetch),
    ).toEqual({ ok: false, status: 502 });
  });
});
