/**
 * The Results section's data (qpilot/web/routers/results.py): the ResultsView, the flip matrix,
 * the Decision Cards with their view fields, and the writes on a card (decide, undo, turn down an
 * agent's request, explain with the model). Every query key starts with `["w", key]` so a live
 * event refreshes it; every write carries the head the view showed.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";

const path = (study_id: string) => ({ params: { path: { study_id } } });
const cardPath = (study_id: string, card_id: string) => ({ params: { path: { study_id, card_id } } });

const getResults = (id: string) => unwrap(api.GET("/api/studies/{study_id}/results", path(id)));
const getFlips = (id: string) => unwrap(api.GET("/api/studies/{study_id}/flips", path(id)));
const getCards = (id: string) => unwrap(api.GET("/api/studies/{study_id}/cards", path(id)));

// The types are the API's answers as the typed client returns them.
export type ResultsView = Awaited<ReturnType<typeof getResults>>;
export type GeneRow = ResultsView["genes"][number];
export type CardsView = Awaited<ReturnType<typeof getCards>>;
export type CardView = CardsView["cards"][number];
export type FlipsView = Awaited<ReturnType<typeof getFlips>>;
export type FactText = CardView["impact"];
/** What a write answers (the outcome, a sentence, the new head). */
export interface DecisionDone {
  outcome: { status: string };
  message: string;
  head: string;
}

export function useResults(key: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", key, "results", studyId],
    enabled: Boolean(studyId),
    queryFn: () => getResults(studyId!),
  });
}

export function useFlips(key: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", key, "flips", studyId],
    enabled: Boolean(studyId),
    queryFn: () => getFlips(studyId!),
  });
}

export function useCards(key: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", key, "cards", studyId],
    enabled: Boolean(studyId),
    queryFn: () => getCards(studyId!),
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
          api.POST("/api/studies/{study_id}/cards/{card_id}/undo", { ...at, body: { reason: w.reason, expected_head: w.head } }),
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
    mutationFn: (card: string) => unwrap(api.POST("/api/studies/{study_id}/cards/{card_id}/explain", cardPath(studyId, card))),
  });
}

/** The model's status: whether "Explain with the model" can be offered. */
export function useModelAnswers(): boolean {
  const q = useQuery({ queryKey: ["model"], queryFn: () => unwrap(api.GET("/api/model")), staleTime: 60_000 });
  return Boolean(q.data?.answers);
}
