/**
 * The Report section's requests: the study's report (Methods, MIQE 2.0, reviewer's report), the
 * report files written since qPilot started, and writing one (a job); the Run Review (headline
 * genes, the Evidence Ledger, the sign-offs) and a person's sign-off. Query keys start with
 * `["w", key]` so live events refresh them.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type JobView, type Schemas } from "@/api/client";
import { useWrite } from "@/shell/writes";

export type ReportView = Schemas["ReportView"];
export type ReportText = Schemas["ReportText"];
export type ReportFact = Schemas["ReportFact"];
export type MiqeItem = Schemas["MiqeItem"];
export type MiqeStatus = MiqeItem["status"];
export type ReviewFinding = Schemas["ReviewFinding"];
export type ReportGene = Schemas["ReportGene"];
export type ReportDecision = Schemas["ReportDecision"];
export type ReportExported = Schemas["ReportExported"];
export type ReportFormat = Schemas["ReportExportBody"]["format"];
export type Facts = ReportView["facts"];

export type RunReviewView = Schemas["RunReviewView"];
export type FactText = Schemas["FactText"];
export type EvidenceView = RunReviewView["evidence"];
export type EvidenceItem = Schemas["EvidenceItemView"];
export type EvidenceStatus = EvidenceItem["status"];
export type SignOff = Schemas["SignOffView"];
export type SignOffOutcome = SignOff["outcome"];
export type SignOffDone = Schemas["SignOffDone"];
export type NotBuilt = Schemas["NotBuiltView"];

/** The study's report (built once per state of the study; the first read takes a few seconds). */
export function useReport(workspaceKey: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", workspaceKey, "report", studyId],
    enabled: Boolean(studyId),
    queryFn: () =>
      unwrap(
        api.GET("/api/studies/{study_id}/report", { params: { path: { study_id: studyId! } } }),
      ),
  });
}

/** The report files written for the study since qPilot started, newest first. */
export function useReportExports(workspaceKey: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", workspaceKey, "report-exports", studyId],
    enabled: Boolean(studyId),
    queryFn: () =>
      unwrap(
        api.GET("/api/studies/{study_id}/report/exports", {
          params: { path: { study_id: studyId! } },
        }),
      ),
  });
}

/** Start writing a report file; the answer names the job (its card follows it). */
export function useExportReport(
  workspaceKey: string,
  studyId: string | null | undefined,
  onJob: (format: ReportFormat, id: string) => void,
) {
  return useWrite<{ format: ReportFormat; head: string | null | undefined }, { job: JobView }>({
    workspaceKey,
    mutationFn: async ({ format, head }) => {
      const answer = await unwrap(
        api.POST("/api/studies/{study_id}/report/export", {
          params: { path: { study_id: studyId! } },
          body: { format, expected_head: head ?? null },
        }),
      );
      onJob(format, answer.job.id);
      return answer;
    },
  });
}

/** Re-read the list of written files (a job finished). */
export function useRefreshExports(workspaceKey: string, studyId: string | null | undefined) {
  const qc = useQueryClient();
  return () =>
    void qc.invalidateQueries({ queryKey: ["w", workspaceKey, "report-exports", studyId] });
}

/** A job's result, if it has the shape of a written report file. */
export function asExported(result: unknown): ReportExported | null {
  const r = result as Partial<ReportExported> | null | undefined;
  return r && typeof r.format === "string" && typeof r.download?.url === "string"
    ? (r as ReportExported)
    : null;
}

const reviewKey = (workspaceKey: string, studyId: string | null | undefined) =>
  ["w", workspaceKey, "run-review", studyId] as const;

/** The Run Review: headline genes, the Evidence Ledger and every recorded sign-off. */
export function useRunReview(workspaceKey: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: reviewKey(workspaceKey, studyId),
    enabled: Boolean(studyId),
    queryFn: () =>
      unwrap(
        api.GET("/api/studies/{study_id}/review", { params: { path: { study_id: studyId! } } }),
      ),
  });
}

export interface SignOffVars {
  outcome: SignOffOutcome;
  comment: string;
  reviewer: string;
  /** The chain head the review was read at (`RunReviewView.head`). */
  head: string;
}

/**
 * A person signs off the run (the server records it as `human`). The answer carries the review
 * again, so the page shows it at once; a `stale` refusal (a decision since the review was read)
 * re-reads it (`useWrite`), and the mutation's error keeps the server's words for the form.
 */
export function useSignOff(
  workspaceKey: string,
  studyId: string | null | undefined,
  onDone?: (done: SignOffDone) => void,
) {
  const qc = useQueryClient();
  return useWrite<SignOffVars, SignOffDone>({
    workspaceKey,
    mutationFn: async ({ outcome, comment, reviewer, head }) => {
      const done = await unwrap(
        api.POST("/api/studies/{study_id}/review/sign-off", {
          params: { path: { study_id: studyId! } },
          body: { outcome, comment, reviewer, expected_head: head },
        }),
      );
      qc.setQueryData(reviewKey(workspaceKey, studyId), done.review);
      return done;
    },
    success: (done) => done.message,
    onSuccess: (done) => onDone?.(done),
  });
}
