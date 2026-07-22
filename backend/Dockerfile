# Backend image: FastAPI AG-UI server + the diagram render toolchain.
# Build context MUST be the repo root (diagram_code_agent/) so both `backend/`
# and the sibling `resources/` (icon pack) are available — the code resolves
# resources via a path relative to the backend root, so the layout is preserved
# and the package is installed editable (`-e`).
#
# Not a multi-stage build: the package is installed editable (`pip install -e
# ./backend`) so backends.py's path.parents[]-based resource resolution keeps
# working, which means the full source tree must be present in the final image
# regardless of a separate build stage — there is no compiled-artifact-only
# copy step that would make a second stage smaller. If this ever moves to a
# non-editable wheel install, revisit splitting build tooling into its own
# stage.
#
# Improvement plan §1.6: generated diagram code no longer runs in this
# container at all (see runtime/sandbox/ — SANDBOX_PROVIDER=modal by default,
# an isolated Modal Sandbox). This image only needs to run the trusted FastAPI
# app plus the Playwright/draw.io-CLI fallback for drawio->PNG rasterization.
FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps:
#  - graphviz       → the `dot` binary that renders diagrams
#  - fontconfig + fonts-liberation/dejavu → "Helvetica"-compatible fonts for labels
#  - libcairo/pango/gdk-pixbuf → cairosvg runtime
#  - libjpeg/zlib   → Pillow runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        graphviz \
        ghostscript \
        fontconfig fonts-liberation fonts-dejavu-core \
        libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
        libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the backend package and the icon pack, then install editable so the
# backends.py path logic (parents[1] == backend/) keeps resolving.
COPY backend ./backend
COPY resources ./resources
COPY logo ./logo
RUN pip install -e ./backend

# Pin the Playwright browser install to a fixed, non-HOME path. Without this,
# `playwright install` below (run here as root, $HOME=/root) puts chromium
# under /root/.cache/ms-playwright — invisible to the non-root `appuser`
# (§1.6 below, $HOME=/home/appuser) at runtime, silently breaking the
# drawio->PNG Playwright fallback in rendering_tools.py. ENV persists into the
# final runtime environment, so the same path resolves for `appuser` later.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN python -m playwright install --with-deps chromium

# --- Version metadata (improvement plan §1.5 /version endpoint) -------------
# Pass at build time, e.g.:
#   docker build --build-arg GIT_SHA=$(git rev-parse HEAD) \
#                --build-arg BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ) ...
# Left unset ("unknown") is honest and preferred over a guessed value.
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ENV GIT_SHA=${GIT_SHA} \
    BUILD_TIME=${BUILD_TIME}

# --- Non-root runtime (improvement plan §1.6) --------------------------------
# UID 1000 matches the common default host-user UID so the bind-mounted
# ./artifacts volume (see docker-compose.yml) is writable without extra setup
# on most Linux hosts; docker-compose's `user: "${UID:-1000}:${GID:-1000}"`
# lets an operator override this to match their own host UID/GID when it
# differs (`export UID GID` before `docker compose up`, or set them in a
# top-level .env). The named `agentspace` volume is chowned here so a fresh
# volume starts writable regardless.
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/backend/agent_space /app/artifacts \
    && chown -R appuser:appuser /app \
    && chmod -R a+rX /ms-playwright
USER appuser

# AG-UI SSE server.
EXPOSE 8001
ENV DIAGRAM_AGENT_PORT=8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8001/health/live', timeout=3)" || exit 1

CMD ["diagram-agent-server"]
