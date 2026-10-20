/**
 * The Record section's requests: the decision chain, exporting the Analysis Record (a job) and
 * verifying a record zip. Query keys start with `["w", key]` so live events refresh them.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { ApiError, postForm, type JobView } from "@/api/client";
import { useWrite } from "@/shell/writes";
import type { DecisionsView, RecordList, VerifyResult } from "./types";

const OFFLINE = "qPilot is not answering. Is `qpilot app` still running?";

interface ErrorShape {
  error?: { code?: string; message?: string; details?: Record<string, unknown> };
}

/** A same-origin JSON request, failing with the server's own words as an {@link ApiError}. */
export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      credentials: "same-origin",
      ...init,
      headers: { accept: "application/json", ...(init?.body ? { "content-type": "application/json" } : {}), ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "offline", OFFLINE);
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

const studyPath = (studyId: string) => `/api/studies/${encodeURIComponent(studyId)}`;

/** The study's decision chain. */
export function useDecisions(workspaceKey: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", workspaceKey, "decisions", studyId],
    enabled: Boolean(studyId),
    queryFn: () => requestJson<DecisionsView>(`${studyPath(studyId!)}/decisions`),
  });
}

/** Start exporting the Analysis Record; the answer names the job to follow (its card says the rest). */
export function useExportRecord(workspaceKey: string, studyId: string | null | undefined, onJob: (id: string) => void) {
  return useWrite<string | null | undefined, { job: JobView }>({
    workspaceKey,
    mutationFn: (expectedHead) =>
      requestJson<{ job: JobView }>(`${studyPath(studyId!)}/record`, {
        method: "POST",
        body: JSON.stringify({ expected_head: expectedHead ?? null }),
      }),
    onSuccess: (answer) => onJob(answer.job.id),
  });
}

/** The records this launch exported for the study, newest first (with their downloads). */
export function useRecords(workspaceKey: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", workspaceKey, "records", studyId],
    enabled: Boolean(studyId),
    queryFn: () => requestJson<RecordList>(`${studyPath(studyId!)}/records`),
  });
}

/** Verify a record zip: checksums, both chains and the audit binding (answered directly). */
export function useVerifyRecord() {
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("record", file, file.name);
      return postForm<VerifyResult>("/api/records/verify", form);
    },
  });
}
