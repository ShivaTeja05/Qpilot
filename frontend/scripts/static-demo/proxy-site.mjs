#!/usr/bin/env node
/**
 * The Vercel front for a hosted qPilot server: the normal production page, with `/api/*` rewritten
 * to the backend, so the browser stays on one origin (CSP `'self'`, no CORS) and the server
 * (QPILOT_HOSTED=1) answers everything, the event stream included.
 *
 *   node scripts/static-demo/proxy-site.mjs --backend https://<host> [--page DIR] [--out DIR]
 *
 * --page: a built page (default: this checkout's qpilot/web/static, i.e. `npm run build`); it must
 * come from the same version as the backend. --out: the folder to deploy (default ../site-proxy).
 * Writes go through only once the backend lists this site's origin in QPILOT_ALLOWED_ORIGINS.
 */
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../../..");
const argv = process.argv.slice(2);
const option = (name, fallback) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};

const backend = new URL(option("--backend", ""));
if (backend.protocol !== "https:") throw new Error("--backend must be an https:// URL");
const page = resolve(option("--page", join(REPO, "qpilot/web/static")));
const out = resolve(option("--out", join(REPO, "site-proxy")));
if (!existsSync(join(page, "index.html"))) throw new Error(`no built page in ${page}`);

// The same security headers as the static demo (site/vercel.json), CSP 'self' only.
const security = JSON.parse(readFileSync(join(REPO, "site/vercel.json"), "utf8")).headers;
const config = {
  cleanUrls: false,
  trailingSlash: false,
  rewrites: [{ source: "/api/:path*", destination: `${backend.origin}/api/:path*` }],
  headers: security.filter((h) => h.source !== "/demo-api/(.*)"),
};

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
cpSync(page, out, { recursive: true });
writeFileSync(join(out, "vercel.json"), `${JSON.stringify(config, null, 2)}\n`);
console.log(`${out}: the page from ${page}, /api/* → ${backend.origin}/api/*`);
