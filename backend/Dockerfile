# Backend image: FastAPI AG-UI server + the diagram render toolchain.
# Build context MUST be the repo root (diagram_code_agent/) so both `backend/`
# and the sibling `resources/` (icon pack) are available — the code resolves
# resources via a path relative to the backend root, so the layout is preserved
# and the package is installed editable (uv sync's default; see below).
#
# Not a multi-stage build: the package is installed editable (`uv sync
# --frozen`, no `--no-editable`) so backends.py's path.parents[]-based
# resource resolution keeps working, which means the full source tree must be
# present in the final image regardless of a separate build stage — there is
# no compiled-artifact-only copy step that would make a second stage smaller.
# If this ever moves to a non-editable wheel install, revisit splitting build
# tooling into its own stage.
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
#  - libreoffice-calc + poppler-utils → wbs_excel_render.py's wbs_filled.xlsx -> PDF ->
#    PNG pipeline (proposal-deck WBS/Effort/Delivery-Plan sheet screenshots, docx WS3).
#    Best-effort at the call site (see wbs_excel_render.soffice_available): if these are
#    ever missing, the deck falls back to its native python-pptx tables — never blocking.
#  - libreoffice-writer → brd_toc.py's out.brd.docx -> PDF bookmark-outline round trip,
#    used to refresh the BRD's cached TOC page numbers for non-Word viewers. Same
#    best-effort contract (see brd_toc.soffice_available): missing it just means the TOC
#    field stays marked dirty for Word to recompute on open instead of being pre-refreshed.
RUN apt-get update && apt-get install -y --no-install-recommends \
        graphviz \
        ghostscript \
        fontconfig fonts-liberation fonts-dejavu-core \
        libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
        libjpeg62-turbo zlib1g \
        libreoffice-calc libreoffice-writer poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install uv itself — COPYing the binary from Astral's official minimal image
# is the standard pattern and does NOT introduce a second "build" stage that
# could accidentally leave the editable-install source tree out of the final
# image; the backend source below is still copied whole into this one stage.
# Pinned to the same version this repo's dev environment resolved uv.lock
# with (`uv --version`) — any 0.7.x reads this lockfile format identically,
# but pinning the exact version keeps the build byte-for-byte reproducible.
COPY --from=ghcr.io/astral-sh/uv:0.7.11 /uv /usr/local/bin/uv

WORKDIR /app

# Copy the backend package and the icon pack, then install from the committed
# lockfile (uv.lock) — matches local dev (`uv sync --frozen`, AGENTS.md) and
# CI (.github/workflows/ci.yml) exactly, instead of the previous `pip install
# -e ./backend`, which resolved every dependency fresh against PyPI at build
# time with no lock: two builds of the same commit at different times could
# silently end up on different dependency versions. `--no-dev` skips
# pytest/ruff/pyright (dev-only, backend/pyproject.toml's [dependency-groups],
# not needed at runtime). `--no-editable` is deliberately NOT passed — see the
# top-of-file comment: backends.py resolves resources via
# `Path(__file__).resolve().parents[]`, which requires the package to stay
# importable from its source location, not copied into site-packages.
#
# Provider extras: langchain-anthropic (backend/pyproject.toml's optional
# `anthropic` extra) is only needed if config.yaml points a role at a
# claude-*/anthropic model — the repo's committed backend/config.yaml uses an
# OpenAI-compatible provider for every role, so it's left out by default
# rather than silently missing at runtime with no build-time signal. Pass
# `--build-arg INSTALL_ANTHROPIC=1` to include it.
COPY backend ./backend
COPY resources ./resources
COPY logo ./logo
ARG INSTALL_ANTHROPIC=0
RUN cd backend && \
    if [ "$INSTALL_ANTHROPIC" = "1" ]; then \
        uv sync --frozen --no-dev --extra anthropic; \
    else \
        uv sync --frozen --no-dev; \
    fi
ENV PATH="/app/backend/.venv/bin:${PATH}"

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
