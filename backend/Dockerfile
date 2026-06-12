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
        fontconfig fonts-liberation fonts-dejavu-core \
        libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
        libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the backend package and the icon pack, then install editable so the
# diagram_mcp.backends path logic (parents[2] == backend/) keeps resolving.
COPY backend ./backend
COPY resources ./resources
COPY logo ./logo
RUN pip install -e ./backend
RUN python -m playwright install --with-deps chromium

# AG-UI SSE server.
EXPOSE 8001
ENV DIAGRAM_AGENT_PORT=8001
CMD ["diagram-agent-server"]
