/** The Record section's words for chain entries, actors and record checks. */
import type { Tone } from "@/ui";
import type { Actor, ChainEntry, EntryStatus } from "./types";

export const ACTOR: Record<Actor, { word: string; filter: string; long: string }> = {
  human: { word: "Person", filter: "People", long: "decided by a person on this page or the CLI" },
  agent: { word: "Agent", filter: "Agents", long: "an AI agent over qPilot's MCP server" },
  system: { word: "qPilot", filter: "qPilot", long: "qPilot itself, by a fixed rule" },
};

export const STATUS: Record<EntryStatus, { word: string; tone: Tone; meaning: string }> = {
  applied: { word: "Applied", tone: "ok", meaning: "This choice is in force." },
  auto: {
    word: "Decided automatically",
    tone: "neutral",
    meaning: "No option changes any conclusion at the recommended settings, so qPilot took the recommended one.",
  },
  pending_human: {
    word: "Waiting for a person",
    tone: "warn",
    meaning: "An agent asked for this; it can change a conclusion, so a person approves or turns it down.",
  },
  rejected: { word: "Turned down", tone: "danger", meaning: "A person turned this request down." },
  stale: {
    word: "Not applied (stale)",
    tone: "neutral",
    meaning: "Something was decided first, so this attempt did not change the study.",
  },
};

/** An agent's request that a person has since approved or turned down (a later entry says which). */
export const ANSWERED = {
  word: "Request, answered",
  tone: "neutral" as Tone,
  meaning: "An agent asked for this; a person answered it in a later entry.",
};

/** The question an entry decided, in words (the server words every card; its id otherwise). */
export function cardTitle(entry: Pick<ChainEntry, "card_id" | "card_title">): string {
  return entry.card_title || entry.card_id;
}

/** The option an entry chose, in words (its id when the server sends no label). */
export function optionLabel(entry: Pick<ChainEntry, "option" | "option_label">): string {
  return entry.option_label || entry.option;
}
