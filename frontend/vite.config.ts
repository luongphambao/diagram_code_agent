import { fileURLToPath, URL } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { visualizer } from "rollup-plugin-visualizer";

// `ANALYZE=1 npm run build` emits dist/stats.html (plan R4/Stage 7's final
// bundle report) — off by default so a normal build doesn't pay the
// (small) extra analysis cost or leave a stats.html artifact in dist/.
const ANALYZE = process.env.ANALYZE === "1";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    ...(ANALYZE ? [visualizer({ filename: "dist/stats.html", gzipSize: true, brotliSize: true, template: "treemap" })] : []),
  ],
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
