/**
 * The online demo's network layer, installed before anything else loads (see `entry.ts`).
 *
 * Every `/api/...` request the page makes is answered from a recording of the real server:
 * `GET` (and the compute-only POSTs in `key.ts`) by the file its key names under `/demo-api/`
 * (gzipped; every well's curve is packed by plate), anything else by a plain-words `read_only`
 * refusal. There is no event stream (nothing changes),
 * and links to `/api/...` downloads are served from the recordings too.
 *
 * Recording (`window.__QPILOT_DEMO_RECORD__`, set by scripts/static-demo/record.mjs): reads go to
 * the real server with their key in `x-qpilot-demo-key`, so the recorder files each answer under
 * exactly the key this page will ask for; writes are refused the same way, never sent.
 */
import { DEMO_API, demoKey, isRead } from "./key";
import { NOT_RECORDED, READ_ONLY } from "./words";

declare global {
  interface Window {
    __QPILOT_DEMO_RECORD__?: boolean;
    /** Requests the page asked for that have no recording (read by the demo's checks). */
    __QPILOT_DEMO_MISSES__?: string[];
  }
}

interface Entry {
  /** HTTP status of the recorded answer (its body is `<key>.gz`, gzipped). */
  s: number;
  /** Content type when it is not JSON. */
  t?: string;
}

interface Manifest {
  entries: Record<string, Entry>;
  /** Every well's raw curve, packed by plate: session → run → pack file (`curves/<file>.gz`). */
  curves?: Record<string, Record<string, string>>;
}

const recording = window.__QPILOT_DEMO_RECORD__ === true;
const realFetch = window.fetch.bind(window);
const misses: string[] = (window.__QPILOT_DEMO_MISSES__ = []);
let manifest: Promise<Manifest> | null = null;

function loadManifest(): Promise<Manifest> {
  manifest ??= realFetch(`${DEMO_API}/index.json`, { cache: "no-cache" }).then(
    (r) => (r.ok ? (r.json() as Promise<Manifest>) : { entries: {} }),
    () => ({ entries: {} }),
  );
  return manifest;
}

/**
 * A recorded body: gzipped on the site, unpacked here (unless a CDN already sent it with
 * `Content-Encoding: gzip` and the browser unpacked it: then it no longer starts with gzip's magic).
 */
async function gunzip(path: string): Promise<Blob | null> {
  const file = await realFetch(path);
  if (!file.ok) return null;
  const bytes = new Uint8Array(await file.arrayBuffer());
  const blob = new Blob([bytes]);
  if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) return blob;
  return new Response(blob.stream().pipeThrough(new DecompressionStream("gzip"))).blob();
}

const packs = new Map<string, Promise<Record<string, unknown> | null>>();

/**
 * One well's curve (`GET /api/sessions/{sid}/curve?well=<run>/<well>[&target=<gene>]`) from its
 * plate's pack: about 25,000 wells, one file per plate instead of one per well.
 */
async function packedCurve(m: Manifest, url: URL): Promise<Response | null> {
  const match = /^\/api\/sessions\/([^/]+)\/curve$/.exec(url.pathname);
  const well = url.searchParams.get("well") ?? "";
  const cut = well.lastIndexOf("/");
  if (!match || cut < 0 || [...url.searchParams.keys()].some((k) => k !== "well" && k !== "target"))
    return null;
  const file = m.curves?.[match[1]!]?.[well.slice(0, cut)];
  if (!file) return null;
  if (!packs.has(file)) {
    packs.set(
      file,
      gunzip(`${DEMO_API}/curves/${file}.gz`).then(async (b) =>
        b ? (JSON.parse(await b.text()) as Record<string, unknown>) : null,
      ),
    );
  }
  const item = (await packs.get(file))?.[well.slice(cut + 1)] as { target?: string } | undefined;
  const target = url.searchParams.get("target");
  if (!item || (target && item.target !== target)) return null;
  return new Response(JSON.stringify(item), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function refusal(status: number, code: string, message: string): Response {
  return new Response(JSON.stringify({ error: { code, message, details: {} } }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

interface Asked {
  method: string;
  url: URL;
  body: string | null;
  form: boolean;
}

async function read(input: RequestInfo | URL, init?: RequestInit): Promise<Asked> {
  const request = input instanceof Request ? input : null;
  const url = new URL(request ? request.url : String(input), location.href);
  const method = (init?.method ?? request?.method ?? "GET").toUpperCase();
  let body: string | null = null;
  let form = false;
  if (method !== "GET" && method !== "HEAD") {
    const raw = init?.body ?? null;
    if (raw instanceof FormData || raw instanceof Blob) form = true;
    else if (typeof raw === "string") body = raw;
    else if (raw != null) body = String(raw);
    else if (request) {
      const type = request.headers.get("content-type") ?? "";
      if (type.startsWith("multipart/")) form = true;
      else body = await request.clone().text();
    }
  }
  return { method, url, body, form };
}

async function demoFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const asked = await read(input, init);
  const { method, url } = asked;
  if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) {
    return realFetch(input, init);
  }
  if (asked.form || !isRead(method, url.pathname)) return refusal(403, "read_only", READ_ONLY);
  const key = await demoKey(method, url, asked.body);

  if (recording) {
    const headers = new Headers(
      init?.headers ?? (input instanceof Request ? input.headers : undefined),
    );
    headers.set("x-qpilot-demo-key", key);
    return realFetch(url.toString(), {
      method,
      headers,
      body: asked.body,
      credentials: "same-origin",
      signal: init?.signal ?? (input instanceof Request ? input.signal : undefined),
    });
  }

  const m = await loadManifest();
  const entry = m.entries[key];
  if (!entry) {
    const curve = method === "GET" ? await packedCurve(m, url) : null;
    if (curve) return curve;
    misses.push(`${method} ${url.pathname}${url.search}`);
    // A read nobody recorded (another what-if, a question of your own): say so, not "read-only".
    return refusal(404, "not_recorded", NOT_RECORDED);
  }
  const empty = entry.s === 204 || entry.s === 304;
  const body = empty ? null : await gunzip(`${DEMO_API}/${key}.gz`);
  if (!empty && !body) {
    misses.push(`${method} ${url.pathname}${url.search}`);
    return refusal(404, "not_recorded", NOT_RECORDED);
  }
  return new Response(body, {
    status: entry.s,
    headers: { "content-type": entry.t ?? "application/json" },
  });
}

window.fetch = demoFetch as typeof window.fetch;

// No event stream: nothing changes on a recording. (While recording, the real one runs, so the
// page re-reads what a finished job changed, and the recorder keeps those answers.)
if (!recording) {
  class QuietEventSource extends EventTarget {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSED = 2;
    readonly readyState = 0;
    readonly withCredentials: boolean;
    onopen: ((e: Event) => void) | null = null;
    onerror: ((e: Event) => void) | null = null;
    onmessage: ((e: MessageEvent) => void) | null = null;
    constructor(
      readonly url: string,
      init?: EventSourceInit,
    ) {
      super();
      this.withCredentials = Boolean(init?.withCredentials);
    }
    close(): void {}
  }
  window.EventSource = QuietEventSource as unknown as typeof EventSource;
}

// Downloads are links to /api/...: fetch them through the recordings and save the file.
document.addEventListener(
  "click",
  (event) => {
    const link = (event.target as Element | null)?.closest?.("a[href]");
    if (!(link instanceof HTMLAnchorElement)) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) return;
    event.preventDefault();
    const name = link.getAttribute("download") || url.pathname.split("/").pop() || "download";
    void (async () => {
      const response = await demoFetch(url.toString());
      if (!response.ok) {
        const { toast } = await import("sonner");
        const body = (await response.json().catch(() => null)) as {
          error?: { message?: string };
        } | null;
        toast.error("Not in the online demo", { description: body?.error?.message ?? READ_ONLY });
        return;
      }
      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const save = document.createElement("a");
      save.href = href;
      save.download = name;
      document.body.append(save);
      save.click();
      save.remove();
      setTimeout(() => URL.revokeObjectURL(href), 10_000);
    })();
  },
  true,
);
