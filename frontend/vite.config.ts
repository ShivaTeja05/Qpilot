import { resolve } from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The build goes straight into the Python package, which serves it (qpilot/web/static).
// `npm run dev` serves the page on :5173 and forwards /api to a running `qpilot app`
// (QPILOT_API, default http://127.0.0.1:7860). Origin is rewritten to the API's own origin so its
// same-origin check passes, and the launch key is added from QPILOT_APP_TOKEN (dev servers only:
// `scripts/serve-dev.sh` fixes it), so the dev page needs no cookie.
const api = process.env.QPILOT_API ?? "http://127.0.0.1:7860";
const devKey = process.env.QPILOT_APP_TOKEN;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": resolve(__dirname, "src") } },
  build: {
    outDir: "../qpilot/web/static",
    emptyOutDir: true,
    assetsDir: "assets",
    // Never inline assets as data: URIs; the CSP allows fonts from this server only.
    assetsInlineLimit: 0,
    sourcemap: false,
    chunkSizeWarningLimit: 600,
  },
  server: {
    host: "127.0.0.1",
    port: Number(process.env.VITE_PORT ?? 5173),
    strictPort: true,
    proxy: {
      "/api": {
        target: api,
        changeOrigin: true,
        headers: { origin: api, ...(devKey ? { "x-qpilot-token": devKey } : {}) },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test-setup.ts"],
    testTimeout: 20_000,
  },
});
