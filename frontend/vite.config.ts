import { fileURLToPath, URL } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Same-origin addressing (see agent-utils.ts BACKEND_URL/RUNTIME_URL):
      // `vite dev` proxies exactly like nginx does in prod, so the app never
      // needs a build-time backend URL baked in.
      "/api/copilotkit": {
        target: "http://localhost:3001",
        changeOrigin: true,
      },
      "/api/artifacts": {
        target: "http://localhost:3001",
        changeOrigin: true,
      },
      "/api/backend": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/backend/, ""),
      },
    },
  },
});
