/**
 * The typed API client. Types come from the Python contract (`npm run gen:api`); every request
 * is same-origin and carries this launch's key in its HttpOnly cookie.
 *
 * Every request goes through {@link apiFetch}, which
 *
 * * names this tab (`x-qpilot-tab`): the events a write causes come back with it as `origin`, so
 *   this tab, which re-reads by itself after its own writes, does not re-read twice (live.ts);
 * * re-validates reads: a view read before is asked for with its `ETag`, and an unchanged view
 *   answers `304` with no body (the body kept here is handed back), so re-reading a workspace
 *   after a decision costs bytes only for the views the decision changed;
 * * asks for soft waits (`Prefer: respond-async`): a view the server is still preparing answers
 *   `202` instead of `409 loading` / `503 warming`, so the browser logs no failed load for a normal
 *   wait. The answer is handed on with its original status, so every caller sees the same
 *   `ApiError` (`code: "loading"` / `"warming"`) as before;
 * * notes the store sequence each answer was read at (`x-qpilot-store-seq`, see live.ts).
 */
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type JobView = Schemas["JobView"];

/** This tab's name for the server's events (random per page load). */
export const TAB_ID: string = (() => {
  try {
    return crypto.randomUUID().replace(/-/g, "").slice(0, 16);
  } catch {
    return Math.random().toString(36).slice(2, 18);
  }
})();

// ---- re-validated reads --------------------------------------------------------------------

interface Kept {
  etag: string;
  body: string;
  type: string;
}

/** Bodies kept to answer a 304 (most recently used last), bounded in count and size. */
const kept = new Map<string, Kept>();
let keptBytes = 0;
const KEEP_MAX = 96;
const KEEP_BYTES = 48 * 1024 * 1024;
const KEEP_ONE = 8 * 1024 * 1024;

function keep(url: string, item: Kept): void {
  forget(url);
  kept.set(url, item);
  keptBytes += item.body.length;
  for (const [old, value] of kept) {
    if (kept.size <= KEEP_MAX && keptBytes <= KEEP_BYTES) break;
    kept.delete(old);
    keptBytes -= value.body.length;
  }
}

function forget(url: string): void {
  const old = kept.get(url);
  if (old) {
    kept.delete(url);
    keptBytes -= old.body.length;
  }
}

/** Forget every kept body (tests). */
export function forgetKeptReads(): void {
  kept.clear();
  keptBytes = 0;
}

// ---- the store sequence answers were read at -----------------------------------------------

type SeqListener = (seq: number, startedAt: number) => void;
const seqListeners = new Set<SeqListener>();

/** Called with the store sequence of every answer (and when its request started). */
export function onReadSeq(listener: SeqListener): () => void {
  seqListeners.add(listener);
  return () => seqListeners.delete(listener);
}

// ---- soft waits ----------------------------------------------------------------------------

const SOFT: Record<string, number> = { loading: 409, warming: 503 };

interface ErrorShape {
  error?: { code?: string; message?: string; details?: Record<string, unknown> };
}

/** A `202` soft wait handed on as the answer it stands for (`409 loading`, `503 warming`). */
async function unsoften(response: Response): Promise<Response> {
  const text = await response.text();
  let code: string | undefined;
  try {
    code = (JSON.parse(text) as ErrorShape)?.error?.code;
  } catch {
    code = undefined;
  }
  const original = Number(response.headers.get("x-qpilot-status")) || (code && SOFT[code]);
  if (!code || !original) {
    return new Response(text, { status: response.status, headers: response.headers });
  }
  return new Response(text, { status: original, headers: response.headers });
}

/** Whether to re-validate with ETags (never in the online demo: it answers from recordings). */
const VALIDATE = !__QPILOT_STATIC_DEMO__;

/** `fetch` for qPilot's API: tab name, soft waits, re-validated reads (see the module doc). */
export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const isRequest = typeof Request !== "undefined" && input instanceof Request;
  const method = (isRequest ? (input as Request).method : (init.method ?? "GET")).toUpperCase();
  const raw = isRequest ? (input as Request).url : String(input);
  const base = typeof location === "undefined" ? "http://localhost/" : location.href;
  const url = new URL(raw, base);
  if (typeof location !== "undefined" && url.origin !== location.origin) {
    return globalThis.fetch(input, init);
  }
  const read = method === "GET" && VALIDATE;
  const known = read ? kept.get(url.href) : undefined;
  const extra: Record<string, string> = { "x-qpilot-tab": TAB_ID };
  if (known) extra["if-none-match"] = known.etag;
  const startedAt = performance.now();
  let response: Response;
  if (isRequest) {
    const request = input as Request;
    for (const [k, v] of Object.entries(extra)) request.headers.set(k, v);
    if (!request.headers.has("prefer")) request.headers.set("prefer", "respond-async");
    response = await globalThis.fetch(read ? new Request(request, { cache: "no-store" }) : request);
  } else {
    const headers = new Headers(init.headers);
    for (const [k, v] of Object.entries(extra)) headers.set(k, v);
    if (!headers.has("prefer")) headers.set("prefer", "respond-async");
    response = await globalThis.fetch(raw, {
      ...init,
      headers,
      ...(read ? { cache: "no-store" as RequestCache } : {}),
    });
  }
  const seq = Number(response.headers.get("x-qpilot-store-seq"));
  if (response.headers.has("x-qpilot-store-seq") && Number.isFinite(seq)) {
    seqListeners.forEach((l) => l(seq, startedAt));
  }
  if (response.status === 304 && known) {
    // Read the (empty) answer, so the browser counts the request as finished, not aborted.
    await response.arrayBuffer().catch(() => undefined);
    kept.delete(url.href); // most recently used last
    kept.set(url.href, known);
    return new Response(known.body, {
      status: 200,
      headers: { "content-type": known.type, etag: known.etag },
    });
  }
  if (response.status === 202) return unsoften(response);
  if (read) {
    const etag = response.headers.get("etag");
    const type = response.headers.get("content-type") ?? "";
    if (response.ok && etag && type.startsWith("application/json")) {
      const body = await response.clone().text();
      if (body.length <= KEEP_ONE) keep(url.href, { etag, body, type });
      else forget(url.href);
    } else {
      forget(url.href);
    }
  }
  return response;
}

export const api = createClient<paths>({
  baseUrl: "",
  credentials: "same-origin",
  fetch: (request: Request) => apiFetch(request),
});

/** A refusal or failure from the server, in its own plain words. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** True when the page was opened without this launch's key (or the server restarted). */
  get needsKey(): boolean {
    return this.status === 401 && this.code === "no_token";
  }

  /** True when someone (another tab, an agent) wrote since this view was read. */
  get stale(): boolean {
    return this.status === 409 && this.code === "stale";
  }

  /** True when the server is still preparing this view (a normal wait, not a failure). */
  get warming(): boolean {
    return this.code === "loading" || this.code === "warming";
  }
}

function toError(status: number, body: unknown): ApiError {
  const e = (body as ErrorShape | undefined)?.error;
  return new ApiError(
    status,
    e?.code ?? `http_${status}`,
    e?.message ?? "The server could not answer this request.",
    e?.details ?? {},
  );
}

/** Await an openapi-fetch call and return its data, or throw an {@link ApiError}. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response };
  try {
    result = await call;
  } catch {
    throw new ApiError(0, "offline", "qPilot is not answering. Is `qpilot app` still running?");
  }
  if (result.error !== undefined || !result.response.ok) {
    throw toError(result.response.status, result.error);
  }
  return result.data as T;
}

/** POST a multipart form (file uploads), returning the parsed JSON body. */
export async function postForm<T>(url: string, form: FormData): Promise<T> {
  let response: Response;
  try {
    response = await apiFetch(url, { method: "POST", body: form, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "offline", "qPilot is not answering. Is `qpilot app` still running?");
  }
  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) throw toError(response.status, body);
  return body as T;
}
