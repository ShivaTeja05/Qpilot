import { resolve } from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

// The build goes straight into the Python package, which serves it (qpilot/web/static).
// `npm run dev` serves the page on :5173 and forwards /api to a running `qpilot app`
// (QPILOT_API, default http://127.0.0.1:7860). Origin is rewritten to the API's own origin so its
// same-origin check passes, and the launch key is added from QPILOT_APP_TOKEN (dev servers only:
// `scripts/serve-dev.sh` fixes it), so the dev page needs no cookie.
const api = process.env.QPILOT_API ?? "http://127.0.0.1:7860";
const devKey = process.env.QPILOT_APP_TOKEN;

// `VITE_STATIC_DEMO=1` (npm run build:demo) builds the read-only online demo instead: the same
// page, answered from recordings of the real server (src/demo, scripts/static-demo), into
// dist-demo/. The flag only adds code paths: without it the build is byte-identical.
const staticDemo = process.env.VITE_STATIC_DEMO === "1";

/** The demo's entry installs the recordings' network layer before the page loads. */
const demoEntry: Plugin = {
  name: "qpilot-static-demo-entry",
  transformIndexHtml: {
    order: "pre",
    handler: (html) => {
      if (!html.includes('src="/src/main.tsx"')) throw new Error("index.html entry not found");
      return html
        .replace('src="/src/main.tsx"', 'src="/src/demo/entry.ts"')
        .replace("<title>qPilot</title>", "<title>qPilot — read-only online demo</title>");
    },
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss(), ...(staticDemo ? [demoEntry] : [])],
  resolve: { alias: { "@": resolve(__dirname, "src") } },
  define: { __QPILOT_STATIC_DEMO__: JSON.stringify(staticDemo) },
  build: {
    outDir: staticDemo ? "dist-demo" : "../qpilot/web/static",
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
