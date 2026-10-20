import { resolve } from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The build goes straight into the Python package, which serves it (qpilot/web/static).
// `npm run dev` serves the page on :5173 and forwards /api to a running `qpilot app`
// (QPILOT_API, default http://127.0.0.1:7860). Origin is rewritten to the API's own origin so its
// same-origin check passes; the launch key comes from the API's cookie (open its printed link once).
const api = process.env.QPILOT_API ?? "http://127.0.0.1:7860";

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
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: api,
        changeOrigin: true,
        headers: { origin: api },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
