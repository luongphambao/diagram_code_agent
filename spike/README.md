# LangGraph Platform Cloud spike

Throwaway repo, not the real app. Exists to answer three questions that
LangChain does **not document explicitly** before we sink weeks into the real
migration (see `plans/*cicd*.md` Phase 0 in the main branch):

| Question | Why it's not a safe assumption |
|---|---|
| Does SSE survive a custom `http.app` route on Cloud (not buffered/killed by the proxy)? | Undocumented. One unresolved forum report of a custom route 404ing after deploy. SSE is the entire mechanism `/agui` depends on. |
| Does multipart upload reach a custom route intact? | Undocumented. Community consensus favors "upload by reference" instead. |
| Do `graphviz` + Playwright Chromium run inside 2 vCPU / 2 GB RAM without hitting a build timeout? | `dockerfile_lines` is allowed, but there are multiple open GitHub issues about Cloud build/deploy timeouts with heavy images. |

Verified locally already (`langgraph dev`, 2026-08-18): graph loads, custom
app loads, all three routes work, 60/60 SSE ticks arrive incrementally (not
buffered). One real bug found and fixed in the process: `subprocess.run`
inside an async route trips LangGraph's blocking-call detector — fixed with
`asyncio.to_thread`. **The same pattern exists in the real app's
`runtime/sandbox/render_exec.py` and should get the same fix regardless of
what this spike's Cloud results say.**

What's *not* verified yet: all of the above running on an actual Cloud
container (2 vCPU / 2 GB RAM, real proxy layer, real build pipeline) — that
needs a LangSmith account and can't be done from this environment.

## How to deploy this

1. Needs a LangSmith account, **Plus plan or higher**, and (one-time, per
   workspace) a GitHub org owner authorizing the `hosted-langserve` app.
2. Push this branch (`spike/langgraph-platform-cloud`) to GitHub.
3. LangSmith UI → new deployment → connect this repo → branch
   `spike/langgraph-platform-cloud` → path to config: `spike/langgraph.json`.
4. Deploy (Serverless tier is fine for this — it's a throwaway).

## What to check once it's live

Replace `$URL` with the deployment URL and `$KEY` with your LangSmith API key.

```bash
# 1. Liveness
curl -sf "$URL/spike/health" -H "x-api-key: $KEY"

# 2. SSE — does it stream incrementally or arrive all at once at the end?
#    Time it: should take ~60s and print one line per second, not 60 lines
#    at once. If curl exits early or nothing prints until the very end,
#    Cloud's proxy is buffering the custom route -> Topology B (mount /agui
#    directly in the deployment) does not work as designed.
time curl -sN "$URL/spike/sse" -H "x-api-key: $KEY"

# 3. Upload — does the sha256 match what you sent?
echo "hello spike" > /tmp/t.txt
sha256sum /tmp/t.txt
curl -sf -F "file=@/tmp/t.txt" "$URL/spike/upload" -H "x-api-key: $KEY"

# 4. Render — does graphviz+Playwright complete without OOM or timeout?
time curl -sf "$URL/spike/render" -H "x-api-key: $KEY"
```

## Decision table (fill in after deploying)

| Result | Verdict |
|---|---|
| SSE streams incrementally, upload's sha256 matches, render returns `"ok": true` for both | Proceed with the plan as written (Topology B: mount `/agui` via `http.app`). |
| SSE arrives all at once / times out | Switch to Topology A: frontend talks to Platform directly via `@ag-ui/langgraph`, needs a Node runtime to hold the API key (or custom auth). This changes the frontend, not just the backend — decide before starting Phase 2. |
| Upload fails or truncates | Switch `/upload` to upload-by-reference (presigned URL to S3/GCS) instead of pushing bytes through the deployment. |
| `render.playwright.ok == false` (OOM/timeout) or the build itself times out | Move rendering to LangSmith Sandbox from the start (bring Phase 6 forward), don't bake Chromium into the deployment image. |
| `render.graphviz.ok == false` for a different reason than the blocking-call bug (already fixed here) | Investigate — `dockerfile_lines`' apt install may need adjusting for the `wolfi` base image. |

Tear down the deployment once you have an answer — this branch is not meant
to stay live.
