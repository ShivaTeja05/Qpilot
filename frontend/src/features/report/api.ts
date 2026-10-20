/**
 * The Report section's requests: the study's report (Methods, MIQE 2.0, reviewer's report), the
 * report files written since qPilot started, and writing one (a job). Query keys start with
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

/** The study's report (built once per state of the study; the first read takes a few seconds). */
export function useReport(workspaceKey: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", workspaceKey, "report", studyId],
    enabled: Boolean(studyId),
    queryFn: () =>
      unwrap(api.GET("/api/studies/{study_id}/report", { params: { path: { study_id: studyId! } } })),
  });
}

/** The report files written for the study since qPilot started, newest first. */
export function useReportExports(workspaceKey: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", workspaceKey, "report-exports", studyId],
    enabled: Boolean(studyId),
    queryFn: () =>
      unwrap(
        api.GET("/api/studies/{study_id}/report/exports", { params: { path: { study_id: studyId! } } }),
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
  return () => void qc.invalidateQueries({ queryKey: ["w", workspaceKey, "report-exports", studyId] });
}

/** A job's result, if it has the shape of a written report file. */
export function asExported(result: unknown): ReportExported | null {
  const r = result as Partial<ReportExported> | null | undefined;
  return r && typeof r.format === "string" && typeof r.download?.url === "string" ? (r as ReportExported) : null;
}
