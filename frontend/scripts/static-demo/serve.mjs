/**
 * Serve the assembled online demo (site/) the way Vercel will: static files, `cleanUrls` off,
 * the headers of site/vercel.json on every answer, 404 for anything else. Used by record.mjs to
 * check the site before it is deployed; also runnable on its own:
 *
 *   node scripts/static-demo/serve.mjs [SITE_DIR] [PORT]
 */
import { createReadStream, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".png": "image/png",
  ".txt": "text/plain; charset=utf-8",
  ".bin": "application/octet-stream",
};

/** The headers vercel.json gives every path (its `"source": "/(.*)"` rule). */
export function siteHeaders(site) {
  const config = JSON.parse(readFileSync(join(site, "vercel.json"), "utf8"));
  const out = {};
  for (const rule of config.headers ?? []) {
    if (rule.source !== "/(.*)") continue;
    for (const { key, value } of rule.headers) out[key.toLowerCase()] = value;
  }
  return out;
}

/** Start the server (port 0: any free port); resolves with `{ url, close() }`. */
export function serveSite(site, port) {
  const root = resolve(site);
  const headers = siteHeaders(root);
  const server = createServer((req, res) => {
    const path = decodeURIComponent(new URL(req.url ?? "/", "http://x").pathname);
    let file = normalize(join(root, path === "/" ? "index.html" : path));
    if (!file.startsWith(root) || /(^|\/)(vercel\.json|README\.md)$/.test(file)) file = "";
    let size = -1;
    try {
      const st = file ? statSync(file) : null;
      if (st?.isFile()) size = st.size;
    } catch {
      size = -1;
    }
    if (req.method !== "GET" && req.method !== "HEAD") {
      res.writeHead(405, { ...headers, "content-type": "text/plain" }).end("method not allowed");
      return;
    }
    if (size < 0) {
      res.writeHead(404, { ...headers, "content-type": "text/plain" }).end("not found");
      return;
    }
    res.writeHead(200, {
      ...headers,
      "content-type": TYPES[extname(file)] ?? "application/octet-stream",
      "content-length": size,
    });
    if (req.method === "HEAD") res.end();
    else createReadStream(file).pipe(res);
  });
  return new Promise((ok, fail) => {
    server.once("error", fail);
    server.listen(port, "127.0.0.1", () => {
      const { port: bound } = server.address();
      ok({ url: `http://127.0.0.1:${bound}`, close: () => new Promise((r) => server.close(r)) });
    });
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const site = process.argv[2] ?? resolve(fileURLToPath(import.meta.url), "../../../../site");
  const port = Number(process.argv[3] ?? 7961);
  const { url } = await serveSite(site, port);
  console.log(`Serving ${site} at ${url} (Ctrl-C to stop)`);
}
