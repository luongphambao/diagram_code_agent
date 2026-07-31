import { createServer } from "node:http";
import { CopilotRuntime } from "@copilotkit/runtime/v2";
import { createCopilotNodeListener } from "@copilotkit/runtime/v2/node";
import type { AbstractAgent } from "@ag-ui/client";
import { DiagramHttpAgent } from "./diagram-agent.js";
import { PassthroughRunner } from "./passthrough-runner.js";
import { CONFIG } from "./config.js";
import { artifactStore } from "./artifact-store.js";
import { authorizeArtifactDownload } from "./artifact-authz.js";

/** Forward whatever identity headers backend/src/security/auth.py's
 *  `require_identity` understands (header mode: X-Auth-Request-Email /
 *  X-Auth-Request-Role; bearer mode: Authorization) so the runtime hop is
 *  transparent to whichever auth mode is deployed. Belt-and-braces:
 *  CopilotRuntime's own `forwardHeaders` denylist already lets custom `x-*`
 *  and `authorization` through by default — this sets them directly on the
 *  per-request agent instance regardless of that policy.
 *
 *  `AgentFactoryContext.request` is verified as a standard Web Fetch `Request`
 *  (CopilotKit/packages/runtime/src/v2/runtime/core/runtime.ts:88-91) — the
 *  Node bridge (createCopilotNodeHandler) converts the raw IncomingMessage
 *  before this factory ever sees it, so `.headers.get(...)`, not
 *  `.headers[...]`. */
function pickAuthHeaders(request: Request): Record<string, string> {
  const out: Record<string, string> = {};
  for (const key of ["authorization", "x-auth-request-email", "x-auth-request-role"]) {
    const value = request.headers.get(key);
    if (value) out[key] = value;
  }
  return out;
}

const runtime = new CopilotRuntime({
  // Per-request factory: agents are cloned per-request regardless, but a
  // factory lets us thread the caller's auth identity onto the outbound
  // Python call via per-instance headers.
  agents: ({ request }) => {
    const agent = new DiagramHttpAgent({
      url: `${CONFIG.backendUrl}/agui`,
      headers: pickAuthHeaders(request),
    });
    // @copilotkit/runtime@1.63.2 declares `agents` as
    // Record<string, AbstractAgent> against its own bundled @ag-ui/client
    // type identity; our direct @ag-ui/client dependency (same published
    // version, 0.0.57) does not structurally unify due to private fields on
    // AbstractAgent. Upstream examples in CopilotKit's own repo work around
    // this with `typescript.ignoreBuildErrors` project-wide; we scope it to
    // this single cast instead so the rest of the service stays typechecked.
    // agent-shape.test.ts asserts the real API surface still matches, so a
    // future @ag-ui/client bump that actually breaks compatibility fails a
    // test instead of silently passing through this cast.
    return { default: agent as unknown as AbstractAgent };
  },
  runner: new PassthroughRunner(),
});

const listener = createCopilotNodeListener({
  runtime,
  basePath: "/api/copilotkit",
  cors: CONFIG.allowedOrigins.length > 0 ? { origin: CONFIG.allowedOrigins } : true,
});

const ARTIFACTS_PREFIX = "/api/artifacts/";

const server = createServer(async (req, res) => {
  if (req.url === "/healthz") {
    res.writeHead(200, { "Content-Type": "text/plain" }).end("ok");
    return;
  }

  // Serves the offloaded artifacts (plan §A.6) substituted into STATE_DELTA/
  // STATE_SNAPSHOT by PassthroughRunner. The lookup key is content-hashed
  // (artifact-store.ts), so a cache hit is safe to mark immutable.
  if (req.method === "GET" && req.url?.startsWith(ARTIFACTS_PREFIX)) {
    const key = decodeURIComponent(req.url.slice(ARTIFACTS_PREFIX.length).split("?")[0]);
    const authz = await authorizeArtifactDownload(key, req.headers);
    if (!authz.ok) {
      const status = authz.status === 401 ? 401 : authz.status === 502 ? 502 : 404;
      res.writeHead(status, { "Content-Type": "text/plain", "Cache-Control": "no-store" })
        .end(status === 502 ? "artifact authorization unavailable" : "artifact not found");
      return;
    }
    const entry = artifactStore.get(key);
    if (!entry) {
      res.writeHead(404, { "Content-Type": "text/plain" }).end("artifact not found or expired");
      return;
    }
    res.writeHead(200, {
      "Content-Type": entry.mime,
      "Content-Length": entry.bytes.length,
      "Cache-Control": "private, max-age=1800, immutable",
    });
    res.end(entry.bytes);
    return;
  }

  listener(req, res);
});

server.listen(CONFIG.port, () => {
  console.log(`diagram-agent-runtime listening on :${CONFIG.port} -> ${CONFIG.backendUrl}`);
});
