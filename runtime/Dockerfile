# Runtime image: the CopilotKit v2 Node service that proxies the browser's
# AG-UI chat traffic to the Python backend's /agui endpoint (see plan §A).
# Build context is the repo root (matches backend/Dockerfile and
# frontend/Dockerfile's convention) so this stays a plain sibling service.
FROM node:20-alpine AS build

WORKDIR /app
COPY runtime/package.json runtime/package-lock.json ./
RUN npm ci

COPY runtime/tsconfig.json ./
COPY runtime/src ./src
RUN npm run build && npm prune --omit=dev

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production

# Non-root runtime (backend/Dockerfile's convention is a fresh UID 1000, but
# node:20-alpine already ships a "node" user at UID/GID 1000 — creating
# another group at gid 1000 collides with it, so reuse the built-in one).
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist ./dist
COPY --from=build --chown=node:node /app/package.json ./
USER node

EXPOSE 3001

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD node -e "fetch('http://127.0.0.1:3001/healthz').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "dist/index.js"]
