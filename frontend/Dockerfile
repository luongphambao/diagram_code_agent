# Frontend image: build the Vite/React SPA, serve the static bundle with nginx.
# Same-origin by default now (plan §A.11) — nginx.conf proxies /api/backend/
# and /api/copilotkit/ to their respective services, so nothing needs to be
# baked in at build time. VITE_BACKEND_URL stays available as an override
# (e.g. pointing at a backend on a different host outside docker compose);
# leave it empty ("") for the normal same-origin path.

# node:24 (not 20): scripts/build-tokens.mjs imports styles/tokens.ts directly
# via Node's native TypeScript-stripping support (stable in Node 24, absent
# in Node 20 -> ERR_UNKNOWN_FILE_EXTENSION on the bare `node script.mjs`
# invocation `npm run build` uses). Matches the Node version already used in
# local dev, so this was never exercised until an actual Docker build.
FROM node:24-alpine AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
ARG VITE_BACKEND_URL=""
ENV VITE_BACKEND_URL=$VITE_BACKEND_URL
RUN npm run build

FROM nginx:alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
