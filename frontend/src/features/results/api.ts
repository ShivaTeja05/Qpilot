/**
 * The Results section's data (qpilot/web/routers/results.py): the ResultsView, the flip matrix,
 * the Decision Cards with their view fields, and the writes on a card (decide, undo, turn down an
 * agent's request, explain with the model), and the Evidence Ledger (`routers/evidence.py`: what
 * the study cannot tell you). Every query key starts with `["w", key]` so a live
 * event refreshes it; every write carries the head the view showed.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, unwrap } from "@/api/client";

const path = (study_id: string) => ({ params: { path: { study_id } } });
const cardPath = (study_id: string, card_id: string) => ({
  params: { path: { study_id, card_id } },
});

const getResults = (id: string) => unwrap(api.GET("/api/studies/{study_id}/results", path(id)));
const getFlips = (id: string) => unwrap(api.GET("/api/studies/{study_id}/flips", path(id)));
const getCards = (id: string) => unwrap(api.GET("/api/studies/{study_id}/cards", path(id)));
const getEvidence = (id: string) => unwrap(api.GET("/api/studies/{study_id}/evidence", path(id)));

// The types are the API's answers as the typed client returns them.
export type ResultsView = Awaited<ReturnType<typeof getResults>>;
export type GeneRow = ResultsView["genes"][number];
export type CardsView = Awaited<ReturnType<typeof getCards>>;
export type CardView = CardsView["cards"][number];
export type FlipsView = Awaited<ReturnType<typeof getFlips>>;
export type FactText = CardView["impact"];
/** A card opened from Trace: the place it is about (null on every other card). */
export type CardPlace = NonNullable<CardView["place"]>;
export type EvidenceView = Awaited<ReturnType<typeof getEvidence>>;
export type EvidenceItem = NonNullable<EvidenceView["items"]>[number];
/** What a write answers (the outcome, a sentence, the new head). */
export interface DecisionDone {
  outcome: { status: string };
  message: string;
  head: string;
}

/**
 * While the server reads a study's file for the first time it answers 503 `warming`; keep asking
 * (the live event that follows refetches too) instead of showing an error.
 */
const warmingRetry = {
  retry: (count: number, e: Error) =>
    e instanceof ApiError && e.code === "warming"
      ? count < 90
      : !(e instanceof ApiError && e.status >= 400 && e.status < 500) && count < 2,
  retryDelay: (count: number, e: Error) =>
    e instanceof ApiError && e.code === "warming" ? 2000 : Math.min(1000 * 2 ** count, 8000),
};

/** True while a query waits for the server to finish reading the study. */
export function isWarming(q: { failureReason: Error | null; isFetching: boolean }): boolean {
  return q.failureReason instanceof ApiError && q.failureReason.code === "warming";
}

export function useResults(key: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", key, "results", studyId],
    enabled: Boolean(studyId),
    ...warmingRetry,
    queryFn: () => getResults(studyId!),
  });
}

export function useFlips(key: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", key, "flips", studyId],
    enabled: Boolean(studyId),
    ...warmingRetry,
    queryFn: () => getFlips(studyId!),
  });
}

export function useCards(key: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", key, "cards", studyId],
    enabled: Boolean(studyId),
    ...warmingRetry,
    queryFn: () => getCards(studyId!),
  });
}

/** The Evidence Ledger: what the study can and cannot tell you (read-only). */
export function useEvidence(key: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", key, "evidence", studyId],
    enabled: Boolean(studyId),
    ...warmingRetry,
    queryFn: () => getEvidence(studyId!),
  });
}

export type CardWrite =
  | { kind: "decide"; card: string; option: string; reason: string; head: string }
  | { kind: "undo"; card: string; reason: string; head: string }
  | { kind: "reject"; card: string; reason: string; head: string; option?: string | null };

/** Decide / undo / turn down, always as a person (the server sets the actor). */
export function useCardWrite(key: string, studyId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (w: CardWrite) => {
      const at = cardPath(studyId, w.card);
      if (w.kind === "decide")
        return unwrap(
          api.POST("/api/studies/{study_id}/cards/{card_id}/decide", {
            ...at,
            body: { option: w.option, reason: w.reason, expected_head: w.head },
          }),
        );
      if (w.kind === "undo")
        return unwrap(
          api.POST("/api/studies/{study_id}/cards/{card_id}/undo", {
            ...at,
            body: { reason: w.reason, expected_head: w.head },
          }),
        );
      return unwrap(
        api.POST("/api/studies/{study_id}/cards/{card_id}/reject-request", {
          ...at,
          body: { reason: w.reason, option: w.option ?? null, expected_head: w.head },
        }),
      );
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["w", key] }),
  });
}

/** Explain a card with the model: a job whose result is the checked explanation. */
export function useExplain(studyId: string) {
  return useMutation({
    mutationFn: (card: string) =>
      unwrap(api.POST("/api/studies/{study_id}/cards/{card_id}/explain", cardPath(studyId, card))),
  });
}

/** The model's status: whether "Explain with the model" can be offered. */
export function useModelAnswers(): boolean {
  const q = useQuery({
    queryKey: ["model"],
    queryFn: () => unwrap(api.GET("/api/model")),
    staleTime: 60_000,
  });
  return Boolean(q.data?.answers);
}

// ---- the Import Trust card (qpilot/web/routers/trust.py) -----------------------------------

const getTrust = (id: string) => unwrap(api.GET("/api/studies/{study_id}/import-trust", path(id)));

export type TrustView = Awaited<ReturnType<typeof getTrust>>;
export type TrustOption = TrustView["options"][number];
export type TrustRequest = TrustView["requests"][number];
export type TrustDecided = Awaited<ReturnType<typeof postTrust>>;

const postTrust = (id: string, option: string, reason: string, inbox: string | null) =>
  unwrap(
    api.POST("/api/studies/{study_id}/import-trust/decide", {
      ...path(id),
      body: { option, reason, expected_inbox: inbox },
    }),
  );

/** Whether the study's imported curves can be trusted as they are (Import Trust card). */
export function useImportTrust(key: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", key, "import-trust", studyId],
    enabled: Boolean(studyId),
    ...warmingRetry,
    queryFn: () => getTrust(studyId!),
  });
}

export type TrustWrite =
  | { kind: "decide"; option: string; reason: string }
  | { kind: "turn_down"; proposal: string; reason: string };

/**
 * A person's choice on the Import Trust card, or turning an agent's request down (a Studio
 * session only; the server sets the actor). Cq only, or leaving it, starts the analysis of the
 * changed design (`job`); every query of the workspace is read again when it settles.
 */
export function useTrustWrite(key: string, studyId: string, view: TrustView | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (w: TrustWrite): Promise<{ message: string }> => {
      const inbox = view?.inbox_head ?? null;
      if (w.kind === "decide") return postTrust(studyId, w.option, w.reason, inbox);
      if (!inbox) throw new Error("Read the card again before turning the request down.");
      const done = await unwrap(
        api.POST("/api/sessions/{sid}/proposals/{pid}/reject", {
          params: { path: { sid: key, pid: w.proposal } },
          body: { reason: w.reason, expected_head: inbox },
        }),
      );
      return { message: done.message };
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["w", key] }),
  });
}
