/**
 * The typed API client. Types come from the Python contract (`npm run gen:api`); every request
 * is same-origin and carries this launch's key in its HttpOnly cookie.
 */
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type JobView = Schemas["JobView"];

export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });

/** A refusal or failure from the server, in its own plain words. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
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
}

interface ErrorShape {
  error?: { code?: string; message?: string; details?: Record<string, unknown> };
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
    response = await fetch(url, { method: "POST", body: form, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "offline", "qPilot is not answering. Is `qpilot app` still running?");
  }
  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) throw toError(response.status, body);
  return body as T;
}
