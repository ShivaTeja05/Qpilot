/**
 * The Studio routes the proposal inbox reads and writes (api's `routers/studio.py`). Every
 * query key starts with `["w", sid]` so live events re-read it; every write is `actor="human"`
 * (the server sets it) and carries the head the view showed.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useSyncExternalStore } from "react";
import { ApiError, api, unwrap, type Schemas } from "@/api/client";
import { refreshWorkspace, reportWriteError } from "@/shell/writes";
import { toast } from "../Toaster";
import type { Payload } from "./edit";
import type { QuoteLookup } from "./parts";

export type InboxStage = "design" | "curves" | "prism" | "roundtrip";

/** The server is reading the session's file for the first time since it started (503 `warming`). */
export function isWarming(error: unknown): error is ApiError {
  return error instanceof ApiError && error.code === "warming";
}
export type ConfirmableStage = "design" | "curves" | "choices";
export type ProposalList = Schemas["ProposalList"];
export type ProposalDecided = Schemas["ProposalDecided"];

/** A stage's proposals, pending first (contradicted, cannot check, consistent), then decided. */
export function useStageProposals(sid: string | null | undefined, stage: InboxStage) {
  return useQuery({
    queryKey: ["w", sid, "proposals", stage],
    enabled: Boolean(sid),
    queryFn: () =>
      unwrap(api.GET("/api/sessions/{sid}/proposals", { params: { path: { sid: sid! }, query: { stage } } })),
  });
}

/** The session's quarantined texts as a lookup for the card's `quotes` and `sheetCells`. */
export function useQuotes(sid: string | null | undefined) {
  const query = useQuery({
    queryKey: ["w", sid, "quarantine"],
    enabled: Boolean(sid),
    queryFn: () => unwrap(api.GET("/api/sessions/{sid}/quarantine", { params: { path: { sid: sid! } } })),
    staleTime: 60_000,
  });
  const data = query.data;
  const byId = useMemo(() => new Map((data?.entries ?? []).map((e) => [e.text_id, e])), [data]);
  const lookup: QuoteLookup = useCallback((id: string) => (data ? (byId.get(id) ?? null) : undefined), [data, byId]);
  return { lookup, sheetCells: data?.sheet_cells, nFlagged: data?.n_flagged ?? 0, query };
}

function path(sid: string, pid: string) {
  return { params: { path: { sid, pid } } } as const;
}

/**
 * Accept / edit / reject for the card (`stage`: the inbox the head is read from). Each resolves once the inbox is re-read and the toast is
 * shown; a refusal rejects with the server's words (the card shows them). A `stale` answer
 * re-reads the views and says so.
 */
export function useProposalActions(sid: string, head: string | null | undefined, stage: InboxStage) {
  const qc = useQueryClient();
  // Every write names the head the view showed; without one (not read yet), read it first.
  const headNow = useCallback(async () => {
    if (head) return head;
    const list = await qc.fetchQuery({
      queryKey: ["w", sid, "proposals", stage],
      queryFn: () =>
        unwrap(api.GET("/api/sessions/{sid}/proposals", { params: { path: { sid }, query: { stage } } })),
    });
    return list.head;
  }, [qc, sid, head, stage]);
  const after = useCallback(
    async (call: Promise<ProposalDecided>) => {
      try {
        const done = await call;
        await refreshWorkspace(qc, sid);
        toast.success(done.message);
        return done;
      } catch (err) {
        if (err instanceof ApiError && (err.stale || err.needsKey)) reportWriteError(qc, err, sid);
        throw err;
      }
    },
    [qc, sid],
  );
  return {
    accept: async (pid: string, reason: string) => {
      const expected_head = await headNow();
      return after(unwrap(api.POST("/api/sessions/{sid}/proposals/{pid}/accept", { ...path(sid, pid), body: { reason, expected_head } })));
    },
    edit: async (pid: string, edits: Payload, reason: string) => {
      const expected_head = await headNow();
      return after(
        unwrap(api.POST("/api/sessions/{sid}/proposals/{pid}/edit", { ...path(sid, pid), body: { reason, edits, expected_head } })),
      );
    },
    reject: async (pid: string, reason: string) => {
      const expected_head = await headNow();
      return after(unwrap(api.POST("/api/sessions/{sid}/proposals/{pid}/reject", { ...path(sid, pid), body: { reason, expected_head } })));
    },
  };
}

/** The engine's check of an edited reading, before anyone accepts it (writes nothing). */
export function useCheckEdit(sid: string) {
  return useCallback(
    (pid: string, edits: Payload) =>
      unwrap(api.POST("/api/sessions/{sid}/proposals/{pid}/check", { ...path(sid, pid), body: { edits } })),
    [sid],
  );
}

// ---------------------------------------------------------------------------------------------
// "Does this matter?" jobs, kept per session across navigation (the job keeps running).

const mattersJobs = new Map<string, string>(); // `${sid}/${pid}` -> job id
const mattersListeners = new Set<() => void>();
let mattersVersion = 0;

function rememberMatters(sid: string, pid: string, job: string) {
  mattersJobs.set(`${sid}/${pid}`, job);
  mattersVersion += 1;
  mattersListeners.forEach((l) => l());
}

/** Start "Does this matter?" for a proposal and follow its job (the card reads the answer). */
export function useMattersJobs(sid: string) {
  useSyncExternalStore(
    (cb) => {
      mattersListeners.add(cb);
      return () => mattersListeners.delete(cb);
    },
    () => mattersVersion,
  );
  const ask = useCallback(
    async (pid: string) => {
      try {
        const started = await unwrap(api.POST("/api/sessions/{sid}/proposals/{pid}/matters", path(sid, pid)));
        rememberMatters(sid, pid, started.job.id);
      } catch (err) {
        toast.error("Could not ask", { description: err instanceof Error ? err.message : String(err) });
      }
    },
    [sid],
  );
  const jobOf = useCallback((pid: string) => mattersJobs.get(`${sid}/${pid}`) ?? null, [sid]);
  return { ask, jobOf };
}
