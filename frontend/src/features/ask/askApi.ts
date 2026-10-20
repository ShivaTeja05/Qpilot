/**
 * The two requests the drawer makes: start an answer (a job) and read what the model saw.
 * Same-origin, with this launch's key in its cookie, and errors in the server's own words.
 */
import { ApiError, type JobView } from "@/api/client";

/** The longest question the server takes (characters). */
export const MAX_QUESTION = 500;

interface ErrorShape {
  error?: { code?: string; message?: string; details?: Record<string, unknown> };
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { credentials: "same-origin", ...init });
  } catch {
    throw new ApiError(0, "offline", "qPilot is not answering. Is `qpilot app` still running?");
  }
  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    const e = (body as ErrorShape | undefined)?.error;
    throw new ApiError(
      response.status,
      e?.code ?? `http_${response.status}`,
      e?.message ?? "The server could not answer this request.",
      e?.details ?? {},
    );
  }
  return body as T;
}

/** Which engine answers: qPilot picks (`auto`), the study's own tools, or the robustness audit. */
export type AskSource = "auto" | "study" | "audit";

/** Ask a question about a study (a study id or a session id); the answer arrives on the job. */
export async function startAsk(
  key: string,
  question: string,
  source: AskSource = "auto",
): Promise<JobView> {
  const body = await call<{ job?: JobView }>(`/api/studies/${encodeURIComponent(key)}/ask`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question, source }),
  });
  if (!body.job?.id)
    throw new ApiError(
      500,
      "bad_response",
      "qPilot accepted the question but did not say where its answer will be.",
    );
  return body.job;
}

/** The last payload sent to a model in this qPilot process, blind-gated by the server. */
export interface ModelSeen {
  payload: unknown;
  hidden: boolean;
  reason: string | null;
  note: string | null;
}

const text = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);

export async function getModelSeen(key: string): Promise<ModelSeen> {
  const body = await call<Record<string, unknown>>(
    `/api/model/seen?study=${encodeURIComponent(key)}`,
  );
  return {
    payload: body.payload ?? null,
    hidden: body.hidden === true,
    reason: text(body.reason),
    note: text(body.note),
  };
}
