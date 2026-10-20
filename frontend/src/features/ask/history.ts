/**
 * The conversation, per study, in memory for this tab: it survives closing the drawer and moving
 * between sections, and is gone on reload (nothing is written to the browser or the store).
 */
import { useSyncExternalStore } from "react";
import type { AskView } from "./types";

/** Older turns are dropped beyond this many per study. */
export const MAX_TURNS = 50;

export type TurnState = "sending" | "running" | "done" | "failed";

export interface Turn {
  /** Local id (stable React key). */
  id: string;
  question: string;
  askedAt: number;
  /** The server's job, once the question was accepted. */
  jobId: string | null;
  state: TurnState;
  answer: AskView | null;
  /** The refusal or failure, as the server worded it. */
  error: unknown;
}

const EMPTY: Turn[] = [];
const byStudy = new Map<string, Turn[]>();
const listeners = new Set<() => void>();
let counter = 0;

function emit(): void {
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The study's turns, oldest first (re-renders when they change). */
export function useTurns(studyId: string | null | undefined): Turn[] {
  return useSyncExternalStore(subscribe, () => (studyId ? (byStudy.get(studyId) ?? EMPTY) : EMPTY));
}

export function getTurns(studyId: string): Turn[] {
  return byStudy.get(studyId) ?? EMPTY;
}

/** Add a question that is being sent; returns its turn. */
export function addTurn(studyId: string, question: string, now = Date.now()): Turn {
  counter += 1;
  const turn: Turn = {
    id: `t${now.toString(36)}-${counter}`,
    question,
    askedAt: now,
    jobId: null,
    state: "sending",
    answer: null,
    error: null,
  };
  byStudy.set(studyId, [...getTurns(studyId), turn].slice(-MAX_TURNS));
  emit();
  return turn;
}

export function updateTurn(studyId: string, id: string, patch: Partial<Omit<Turn, "id">>): void {
  const turns = getTurns(studyId);
  if (!turns.some((t) => t.id === id)) return;
  byStudy.set(
    studyId,
    turns.map((t) => (t.id === id ? { ...t, ...patch } : t)),
  );
  emit();
}

export function clearTurns(studyId: string): void {
  if (!byStudy.has(studyId)) return;
  byStudy.delete(studyId);
  emit();
}

/** The questions asked, most recent first, without repeats (for ↑ recall). */
export function recallList(turns: Turn[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const { question: q } of [...turns].reverse()) {
    if (!seen.has(q)) {
      seen.add(q);
      out.push(q);
    }
  }
  return out;
}

/** Forget every conversation (tests). */
export function resetAllTurns(): void {
  byStudy.clear();
  emit();
}
