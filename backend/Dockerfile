# Backend image: FastAPI AG-UI server + the diagram render toolchain.
# Build context MUST be the repo root (diagram_code_agent/) so both `backend/`
# and the sibling `resources/` (icon pack) are available — the code resolves
# resources via a path relative to the backend root, so the layout is preserved
# and the package is installed editable (`-e`).
FROM python:3.11-slim AS base

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

# draw.io desktop CLI — renders the NATIVE layout engine's .drawio → PNG so the
# visual critic can review native diagrams (the Graphviz path already emits PNG).
# Headless Electron needs xvfb + X/GTK libs; _render_drawio_png wraps it in
# `xvfb-run`. OPTIONAL: the download is non-fatal — if it fails (e.g. GitHub
# release blocked at build time), _render_drawio_png automatically falls back to
# a Playwright/Chromium-based renderer (viewer.diagrams.net, already installed
# below for PDF export) — only if BOTH are unavailable does the native path
# degrade to `.drawio` + validator lint with no PNG.
ARG DRAWIO_VERSION=30.2.6
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb wget libnotify4 libnss3 libxss1 libasound2 libgbm1 libgtk-3-0 xdg-utils \
    && ( wget -q -O /tmp/drawio.deb \
           "https://github.com/jgraph/drawio-desktop/releases/download/v${DRAWIO_VERSION}/drawio-amd64-${DRAWIO_VERSION}.deb" \
         && apt-get install -y --no-install-recommends /tmp/drawio.deb \
         || echo "WARN: draw.io desktop ${DRAWIO_VERSION} install failed — native diagrams export .drawio + validator lint only (no PNG preview)." ) \
    && rm -f /tmp/drawio.deb && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the backend package and the icon pack, then install editable so the
# backends.py path logic (parents[1] == backend/) keeps resolving.
COPY backend ./backend
COPY resources ./resources
COPY logo ./logo
RUN pip install -e ./backend
RUN python -m playwright install --with-deps chromium

# AG-UI SSE server.
EXPOSE 8001
ENV DIAGRAM_AGENT_PORT=8001
CMD ["diagram-agent-server"]
