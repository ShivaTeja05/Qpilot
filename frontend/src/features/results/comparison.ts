/**
 * The comparison a person is looking at, in a study with several: one choice shared by Results,
 * Trace and a gene's page, so picking "Drug B vs Control" on Results opens Trace and the gene's
 * page on the same comparison. Kept per study for the life of the page (never stored; `null`
 * is the study's first comparison, as the API's default).
 */
import { useCallback, useSyncExternalStore } from "react";

const chosen = new Map<string, string>();
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Show comparison `id` of study `studyId` everywhere (null: back to the first). */
export function showComparison(studyId: string, id: string | null) {
  if (id) chosen.set(studyId, id);
  else chosen.delete(studyId);
  for (const listener of listeners) listener();
}

/** The comparison shown for a study (null: the first) and a setter. */
export function useShownComparison(
  studyId: string | null | undefined,
): [string | null, (id: string | null) => void] {
  const id = useSyncExternalStore(
    subscribe,
    () => (studyId ? (chosen.get(studyId) ?? null) : null),
    () => null,
  );
  const set = useCallback(
    (next: string | null) => (studyId ? showComparison(studyId, next) : undefined),
    [studyId],
  );
  return [id, set];
}
