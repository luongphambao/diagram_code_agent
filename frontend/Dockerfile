# Frontend image: build the Vite/React SPA, serve the static bundle with nginx.
# The backend URL is baked at BUILD time (Vite inlines import.meta.env.*), so it
# is passed as a build arg — it must be the URL the BROWSER uses to reach the
# backend (e.g. http://localhost:8001 when running via docker compose locally).
FROM node:20-alpine AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
ARG VITE_BACKEND_URL=http://localhost:8001
ENV VITE_BACKEND_URL=$VITE_BACKEND_URL
RUN npm run build

FROM nginx:alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
