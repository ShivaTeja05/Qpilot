/**
 * An answer, as the server's `ask` job returns it (`AskAnswer`, typed from the Python contract).
 * {@link toAskAnswer} refuses a result without an answer, so a server out of step with the page
 * shows "could not read the answer" instead of a broken panel.
 */
import type { Schemas } from "@/api/client";

export type AskAnswer = Schemas["AskAnswer"];
export type AskFact = Schemas["CitedFact"];

/** A finished ask job's result, or null when it holds no answer. */
export function toAskAnswer(result: unknown): AskAnswer | null {
  if (typeof result !== "object" || result === null) return null;
  const r = result as Partial<AskAnswer>;
  if (typeof r.answer !== "string" || !r.answer.trim() || !Array.isArray(r.facts)) return null;
  return r as AskAnswer;
}

/** The Decision Card an answer is about, as a focus target for Results (`card:<id>`). */
export function cardFocus(a: Pick<AskAnswer, "focus" | "card_id">): string | null {
  if (a.focus?.startsWith("card:")) return a.focus;
  return a.card_id ? `card:${a.card_id}` : null;
}
