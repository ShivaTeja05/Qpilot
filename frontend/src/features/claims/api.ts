/**
 * The Claims section's data (qpilot/web/routers/claims.py): check a text's claims against the
 * open study (`POST /claims`, read by rules), the same with the page's model proposing readings
 * the rules missed (`POST /claims/read`, a job), and example sentences the server wrote from the
 * study's own facts (`GET /claims/examples`). Query keys start with `["w", key]` so a live event
 * about the workspace refreshes them; a check is a mutation (the text is the body, never stored).
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, ApiError, unwrap, type Schemas } from "@/api/client";

export type ClaimsReport = Schemas["ClaimsReport"];
export type ClaimView = Schemas["ClaimView"];
export type ClaimText = Schemas["ClaimText"];
export type ClaimFact = Schemas["ClaimFact"];
export type ClaimCheck = Schemas["ClaimCheck"];
export type ClaimChoice = Schemas["ClaimChoice"];
export type ClaimSpan = Schemas["ClaimSpan"];
export type ClaimExamples = Schemas["ClaimExamples"];
export type ClaimsAssistResult = Schemas["ClaimsAssistResult"];
export type Verdict = ClaimView["verdict"];
export type CheckStatus = ClaimCheck["status"];

/** The most characters the server checks at once (`MAX_CLAIMS_TEXT`). */
export const MAX_TEXT = 5000;

const path = (study_id: string) => ({ params: { path: { study_id } } });

/** A checked text: the report and the exact text it was checked on (spans index into it). */
export interface Checked {
  text: string;
  report: ClaimsReport;
}

/** `POST /api/studies/{id}/claims`: every claim in the text, checked. */
export function useCheckClaims(studyId: string | null) {
  return useMutation({
    mutationFn: async (text: string): Promise<Checked> => {
      const report = await unwrap(
        api.POST("/api/studies/{study_id}/claims", { ...path(studyId!), body: { text } }),
      );
      return { text, report };
    },
  });
}

/** `POST /api/studies/{id}/claims/read`: the model proposes readings (a job; returns its id). */
export function useReadWithModel(studyId: string | null) {
  return useMutation({
    mutationFn: async (text: string) => {
      const started = await unwrap(
        api.POST("/api/studies/{study_id}/claims/read", { ...path(studyId!), body: { text } }),
      );
      return { text, jobId: started.job.id };
    },
  });
}

/** `GET /api/studies/{id}/claims/examples`: sentences written from the study's facts. */
export function useExamples(key: string, studyId: string | null) {
  return useQuery({
    queryKey: ["w", key, "claims-examples", studyId],
    enabled: Boolean(studyId),
    staleTime: 60_000,
    retry: (count: number, e: Error) =>
      e instanceof ApiError && e.code === "warming" ? count < 60 : count < 1,
    retryDelay: 2000,
    queryFn: () => unwrap(api.GET("/api/studies/{study_id}/claims/examples", path(studyId!))),
  });
}

/** The job's result as the contract types it (`JOB_RESULTS["claims.read"]`). */
export function assistResult(result: unknown): ClaimsAssistResult | null {
  if (!result || typeof result !== "object" || !("report" in result)) return null;
  return result as ClaimsAssistResult;
}
