import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config";

// Merges the app's Vite config (plugins, aliases) so component tests resolve
// imports identically to the real build — no drift between "works in tests"
// and "works in the app".
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      globals: false,
      setupFiles: ["./test/setup.ts"],
      css: true,
      coverage: {
        provider: "v8",
        reporter: ["text", "html"],
        include: ["src/**/*.{ts,tsx}"],
        exclude: ["src/**/*.d.ts", "src/main.tsx"],
      },
    },
  }),
);
