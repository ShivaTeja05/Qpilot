/**
 * The Audit section's data: the audit's status, its views, the what-if lab and verification.
 * Every query about the audit starts with `["w", workspace key, "audit", study id]`, so a
 * `study.changed` event for either key (a decision, a finished audit job) re-reads it.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import type {
  AuditHow,
  AuditOverview,
  AuditStatus,
  AuditStudyView,
  AuditVerify,
  AuditWhatif,
  Changes,
  IssueView,
  JobLike,
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
    response = await fetch(url, {
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

const base = (studyId: string) => `/api/studies/${encodeURIComponent(studyId)}/audit`;

/** Where the audit's queries live in the cache. */
export function auditKey(workspaceKey: string, studyId: string, ...rest: unknown[]): unknown[] {
  return ["w", workspaceKey, "audit", studyId, ...rest];
}

export interface AuditTarget {
  workspaceKey: string;
  studyId: string;
}

/** The study's audit: not run, running, ready, refused, not applicable or unavailable. */
export function useAuditStatus({ workspaceKey, studyId }: AuditTarget) {
  return useQuery({
    queryKey: auditKey(workspaceKey, studyId, "status"),
    queryFn: () => request<AuditStatus>("GET", base(studyId)),
    // While an audit runs, the job's events refresh this; poll slowly as a fallback.
    refetchInterval: (q) =>
      (q.state.data as AuditStatus | undefined)?.status === "running" ? 5000 : false,
  });
}

/** Start the audit (a job, about 50 s on the demo). */
export function useRunAudit({ workspaceKey, studyId }: AuditTarget) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => request<{ job: JobLike }>("POST", base(studyId)),
    onSuccess: () => qc.invalidateQueries({ queryKey: auditKey(workspaceKey, studyId, "status") }),
  });
}

/** Re-read every view of the audit (after a job finishes). */
export function useInvalidateAudit({ workspaceKey, studyId }: AuditTarget) {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: auditKey(workspaceKey, studyId) });
}

export function useAuditOverview(t: AuditTarget, enabled = true) {
  return useQuery({
    queryKey: auditKey(t.workspaceKey, t.studyId, "overview"),
    enabled,
    queryFn: () => request<AuditOverview>("GET", `${base(t.studyId)}/overview`),
  });
}

export function useAuditStudy(t: AuditTarget, enabled = true) {
  return useQuery({
    queryKey: auditKey(t.workspaceKey, t.studyId, "study"),
    enabled,
    queryFn: () => request<AuditStudyView>("GET", `${base(t.studyId)}/study`),
  });
}

export function useAuditHow(t: AuditTarget, enabled = true) {
  return useQuery({
    queryKey: auditKey(t.workspaceKey, t.studyId, "how"),
    enabled,
    queryFn: () => request<AuditHow>("GET", `${base(t.studyId)}/how`),
  });
}

/** The whole issue queue (the overview carries only its first few). */
export function useAuditIssues(t: AuditTarget, enabled = true) {
  return useQuery({
    queryKey: auditKey(t.workspaceKey, t.studyId, "issues"),
    enabled,
    queryFn: () =>
      request<IssueView[] | { issues: IssueView[] }>("GET", `${base(t.studyId)}/issues`),
    select: (data) => (Array.isArray(data) ? data : data.issues),
  });
}

export function useAuditVerify(t: AuditTarget, enabled = true) {
  return useQuery({
    queryKey: auditKey(t.workspaceKey, t.studyId, "verify"),
    enabled,
    queryFn: () => request<AuditVerify>("GET", `${base(t.studyId)}/verify`),
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
    queryKey: auditKey(t.workspaceKey, t.studyId, "whatif", changesKey(changes)),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    queryFn: ({ signal }) =>
      request<AuditWhatif>("POST", `${base(t.studyId)}/whatif`, { changes, genes }, signal),
  });
}
