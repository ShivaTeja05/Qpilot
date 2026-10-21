/**
 * The online demo's addressing: every API request maps to one recorded file. The key is a hash
 * of the method, the path, the sorted query and (for a POST) the body as canonical JSON, so the
 * recorder and the page always agree on it. Nothing here imports the app: `install.ts` patches
 * `fetch` before the typed client is created, and must not load the client first.
 */

/** Where the recordings are served from, next to the page. */
export const DEMO_API = "/demo-api";

/** POSTs that only compute (nothing is written): the demo answers the recorded ones. */
const READ_POSTS: RegExp[] = [
  // The audit's what-if, one gene's samples under other choices, the checksum check.
  /^\/api\/studies\/[^/]+\/audit\/(whatif|samples|verify)$/,
  /^\/api\/audits\/[^/]+\/(whatif|samples|verify)$/,
  // The Claim Auditor's rules, Plan next and its plates, Trace's "set these samples aside".
  /^\/api\/studies\/[^/]+\/claims$/,
  /^\/api\/studies\/[^/]+\/planner(\/layout)?$/,
  /^\/api\/studies\/[^/]+\/trace\/[^/]+\/without$/,
  // Ask (a job; every number in the answer is a cited fact) and the report's files.
  /^\/api\/studies\/[^/]+\/ask$/,
  /^\/api\/studies\/[^/]+\/report\/export$/,
];

/** True for a request that changes nothing on the server (a GET, or a compute-only POST). */
export function isRead(method: string, path: string): boolean {
  const m = method.toUpperCase();
  if (m === "GET" || m === "HEAD") return true;
  return m === "POST" && READ_POSTS.some((re) => re.test(path));
}

/** JSON with every object's keys sorted, so equal bodies give equal keys. */
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonicalJson(v)}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

/** A request body as the key sees it: canonical JSON when it parses, else the text itself. */
export function canonicalBody(text: string | null | undefined): string {
  if (!text) return "";
  try {
    return canonicalJson(JSON.parse(text));
  } catch {
    return text;
  }
}

/** What the key is made of: `GET /api/x?a=1&b=2` (+ a newline and the canonical body). */
export function keySource(method: string, url: URL, body?: string | null): string {
  const query = [...url.searchParams.entries()]
    .sort(([a, av], [b, bv]) => (a < b ? -1 : a > b ? 1 : av < bv ? -1 : av > bv ? 1 : 0))
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join("&");
  const m = method.toUpperCase();
  const head = `${m} ${url.pathname}${query ? `?${query}` : ""}`;
  return m === "GET" || m === "HEAD" ? head : `${head}\n${canonicalBody(body)}`;
}

/** The recording's file name (without extension): the first 32 hex digits of a SHA-256. */
export async function demoKey(method: string, url: URL, body?: string | null): Promise<string> {
  const bytes = new TextEncoder().encode(keySource(method, url, body));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest).slice(0, 16), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}
