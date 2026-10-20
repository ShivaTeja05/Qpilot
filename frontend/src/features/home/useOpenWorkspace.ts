/**
 * After an open job finishes: read the new session's frame (it primes the shell's frame query)
 * and go to its next step, the section the server names.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";
import { useLocation } from "wouter";
import { api, unwrap, type JobView } from "@/api/client";
import { useJob } from "@/api/jobs";
import { SECTION, sectionPath } from "@/shell/sections";
import { asSection } from "./workspace";

/** The key an open job's result names (`{"key": "<session id>"}`), if it has one. */
export function openedKey(result: unknown): string | null {
  const key = (result as { key?: unknown } | null | undefined)?.key;
  return typeof key === "string" && key ? key : null;
}

/**
 * Calls `onDone(job)` once when the job `id` finishes (the event stream and `useJob` keep it
 * current); `onFailed` once if it fails. Returns the job's live state.
 */
export function useJobOutcome(
  id: string | null,
  onDone: (job: JobView) => void,
  onFailed?: (job: JobView) => void,
): JobView | undefined {
  const job = useJob(id).data;
  const fired = useRef<string | null>(null);
  const handlers = useRef({ onDone, onFailed });
  useEffect(() => {
    handlers.current = { onDone, onFailed };
  });
  useEffect(() => {
    if (!job || !id || fired.current === id) return;
    // The result arrives with the re-read after the "done" event; wait for it.
    if (job.status === "done" && job.result != null) {
      fired.current = id;
      handlers.current.onDone(job);
    } else if (job.status === "failed") {
      fired.current = id;
      handlers.current.onFailed?.(job);
    }
  }, [job, id]);
  return job;
}

/** Returns `goTo(sessionId)`: fetch the session's frame, then navigate to its next step. */
export function useGoToSession() {
  const qc = useQueryClient();
  const [, navigate] = useLocation();
  return useCallback(
    async (sid: string) => {
      const view = await qc.fetchQuery({
        queryKey: ["w", sid, "frame"],
        queryFn: () => unwrap(api.GET("/api/sessions/{sid}", { params: { path: { sid } } })),
      });
      void qc.invalidateQueries({ queryKey: ["workspaces"] });
      const section = asSection(view.next_step.section, "design");
      navigate(sectionPath(view, SECTION[section].scope === "global" ? "design" : section));
    },
    [qc, navigate],
  );
}
