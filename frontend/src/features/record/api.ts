/**
 * The Record section's requests: the decision chain, exporting the Analysis Record (a job) and
 * verifying a record zip. Query keys start with `["w", key]` so live events refresh them.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, postForm, unwrap, type JobView } from "@/api/client";
import { useWrite } from "@/shell/writes";
import { fromApi, type DecisionsApi, type VerifyResult } from "./types";

/** The study's decision chain. */
export function useDecisions(workspaceKey: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", workspaceKey, "decisions", studyId],
    enabled: Boolean(studyId),
    queryFn: async () => {
      const view: DecisionsApi = await unwrap(
        api.GET("/api/studies/{study_id}/decisions", { params: { path: { study_id: studyId! } } }),
      );
      return fromApi(view);
    },
  });
}

/** Start exporting the Analysis Record; the answer names the job to follow (its card says the rest). */
export function useExportRecord(
  workspaceKey: string,
  studyId: string | null | undefined,
  onJob: (id: string) => void,
) {
  return useWrite<string | null | undefined, { job: JobView }>({
    workspaceKey,
    mutationFn: async (expectedHead) => {
      const answer = await unwrap(
        api.POST("/api/studies/{study_id}/record", {
          params: { path: { study_id: studyId! } },
          body: { include_input: true, expected_head: expectedHead ?? null },
        }),
      );
      // Show the job's card at once; re-reading the workspace (useWrite) can take a while.
      onJob(answer.job.id);
      return answer;
    },
  });
}

/** The records exported for the study, newest first (with their downloads). */
export function useRecords(workspaceKey: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", workspaceKey, "records", studyId],
    enabled: Boolean(studyId),
    queryFn: () =>
      unwrap(
        api.GET("/api/studies/{study_id}/records", { params: { path: { study_id: studyId! } } }),
      ),
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
