/**
 * The Audit section's data: the audit's status, its views, the what-if lab and verification.
 * Every query about the audit starts with `["w", workspace key, "audit", study id]`, so a
 * `study.changed` event for either key (a decision, a finished audit job) re-reads it.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect } from "react";
import { ApiError, apiFetch, type JobView } from "@/api/client";
import { jobPollMs } from "@/api/jobs";
import type {
  AuditHow,
  AuditOverview,
  AuditStatus,
  AuditStudyView,
  AuditVerify,
  AuditWhatif,
  AttachedAudit,
  Changes,
  IssueView,
} from "./types";

interface ErrorShape {
  error?: { code?: string; message?: string; details?: Record<string, unknown> };
}

/**
 * A same-origin JSON request answered in the API's error shape. The audit routes are read
 * through this until their types are generated into `schema.d.ts`; the result is the route's
 * JSON as-is.
 */
async function request<T>(
  method: "GET" | "POST",
  url: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await apiFetch(url, {
      method,
      signal,
      credentials: "same-origin",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new ApiError(0, "offline", "qPilot is not answering. Is `qpilot app` still running?");
  }
  const data: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    const e = (data as ErrorShape | undefined)?.error;
    throw new ApiError(
      response.status,
      e?.code ?? `http_${response.status}`,
      e?.message ?? "The server could not answer this request.",
      e?.details ?? {},
    );
  }
  return data as T;
}

/** Where an audit's queries live in the cache (both keys, so either key's events re-read it). */
export function auditKey(t: AuditTarget, ...rest: unknown[]): unknown[] {
  return ["w", t.workspaceKey, "audit", t.studyId, t.base, ...rest];
}

export interface AuditTarget {
  workspaceKey: string;
  studyId: string;
  /** The audit's routes: the study's own (`/api/studies/{id}/audit`) or an attached folder's. */
  base: string;
}

/** The study's own audit. */
export function studyAudit(workspaceKey: string, studyId: string): AuditTarget {
  return { workspaceKey, studyId, base: `/api/studies/${encodeURIComponent(studyId)}/audit` };
}

/** A results folder attached when the server started (`qpilot app --audit DIR`). */
export function attachedAudit(workspaceKey: string, studyId: string, name: string): AuditTarget {
  return { workspaceKey, studyId, base: `/api/audits/${encodeURIComponent(name)}` };
}

/** The study's audit: not run, running, ready, refused, not applicable or unavailable. */
export function useAuditStatus(t: AuditTarget) {
  return useQuery({
    queryKey: auditKey(t, "status"),
    queryFn: () => request<AuditStatus>("GET", t.base),
    // While an audit runs, the job's events refresh this; poll slowly as a fallback.
    refetchInterval: (q) =>
      (q.state.data as AuditStatus | undefined)?.status === "running" ? jobPollMs() : false,
  });
}

/**
 * Start the audit (a job, about a minute on the demo). `again` replaces an existing audit (the
 * server keeps the earlier one beside it); without it, an existing audit is a 409.
 */
export function useRunAudit(t: AuditTarget) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (again: boolean = false) => request<{ job: JobView }>("POST", t.base, { again }),
    onSuccess: () => qc.invalidateQueries({ queryKey: auditKey(t, "status") }),
  });
}

/**
 * Put a job the status answer carries into the job cache, so its card shows at once (the event
 * stream and `useJob` keep it current from there).
 */
export function useSeedJob(job: JobView | null | undefined) {
  const qc = useQueryClient();
  useEffect(() => {
    if (job && !qc.getQueryData(["job", job.id])) qc.setQueryData(["job", job.id], job);
  }, [qc, job]);
}

/**
 * A view whose live data is not loaded yet answers 409 `loading` with the job that loads it
 * (the server never makes a request wait for the load): that job, or null for any other answer.
 */
export function loadingJob(error: unknown): JobView | null {
  if (!(error instanceof ApiError) || error.code !== "loading") return null;
  const job = error.details.job;
  return job && typeof job === "object" && "id" in job ? (job as JobView) : null;
}

/** An error worth showing: not the 409 that says the views are still loading. */
export function shownError(error: unknown): unknown {
  return error && !loadingJob(error) ? error : null;
}

/** Re-read every view of the audit (after a job finishes). */
export function useInvalidateAudit(t: AuditTarget) {
  const qc = useQueryClient();
  const { workspaceKey, studyId, base } = t;
  return useCallback(
    () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: auditKey({ workspaceKey, studyId, base }) }),
        // an attached folder's own answer carries its load state
        qc.invalidateQueries({ queryKey: ["audits"] }),
      ]),
    [qc, workspaceKey, studyId, base],
  );
}

export function useAuditOverview(t: AuditTarget, enabled = true) {
  return useQuery({
    queryKey: auditKey(t, "overview"),
    enabled,
    queryFn: () => request<AuditOverview>("GET", `${t.base}/overview`),
  });
}

export function useAuditStudy(t: AuditTarget, enabled = true) {
  return useQuery({
    queryKey: auditKey(t, "study"),
    enabled,
    queryFn: () => request<AuditStudyView>("GET", `${t.base}/study`),
  });
}

export function useAuditHow(t: AuditTarget, enabled = true) {
  return useQuery({
    queryKey: auditKey(t, "how"),
    enabled,
    queryFn: () => request<AuditHow>("GET", `${t.base}/how`),
  });
}

/** The whole issue queue (the overview carries only its first few). */
export function useAuditIssues(t: AuditTarget, enabled = true) {
  return useQuery({
    queryKey: auditKey(t, "issues"),
    enabled,
    queryFn: () => request<IssueView[] | { issues: IssueView[] }>("GET", `${t.base}/issues`),
    select: (data) => (Array.isArray(data) ? data : data.issues),
  });
}

/**
 * Check the audit's checksums and its binding to the study's record (the server writes the
 * record to a scratch folder and reads it back; nothing is kept). A POST that writes nothing.
 */
export function useAuditVerify(t: AuditTarget, enabled = true) {
  return useQuery({
    queryKey: auditKey(t, "verify"),
    enabled,
    queryFn: () => request<AuditVerify>("POST", `${t.base}/verify`, { bind_to_record: true }),
  });
}

/**
 * Results folders attached when the server started (`qpilot app --audit DIR`); none when the
 * server attaches none (or does not serve the list).
 */
export function useAttachedAudits() {
  return useQuery({
    queryKey: ["audits"],
    staleTime: Infinity,
    queryFn: async () => {
      try {
        return (await request<{ audits: AttachedAudit[] }>("GET", "/api/audits")).audits;
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return [];
        throw err;
      }
    },
  });
}

/**
 * One attached folder; opening it starts loading its live views (`views_ready`, `loading`).
 */
export function useAttachedAudit(name: string | undefined) {
  return useQuery({
    queryKey: ["audits", name],
    enabled: Boolean(name),
    queryFn: () => request<AttachedAudit>("GET", `/api/audits/${encodeURIComponent(name!)}`),
  });
}

/** Sorted `decision=option` pairs: one cache entry per set of choices, whatever the order. */
export function changesKey(changes: Changes): string {
  return Object.keys(changes)
    .sort()
    .map((d) => `${d}=${changes[d]}`)
    .join("&");
}

/**
 * The engine re-run live under a set of choices (every gene, planned → chosen). Keyed by the
 * choices, so going back to an earlier set is instant; the previous answer stays on screen while
 * the next one is computed.
 */
export function useWhatif(t: AuditTarget, changes: Changes, genes: string[], enabled = true) {
  return useQuery({
    queryKey: auditKey(t, "whatif", changesKey(changes)),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    queryFn: ({ signal }) =>
      request<AuditWhatif>("POST", `${t.base}/whatif`, { changes, genes }, signal),
  });
}
