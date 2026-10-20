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

/** Card titles by kind, as `qpilot/ai/explain.py` words them (used when the server sends none). */
const KIND_TITLE: Record<string, string> = {
  reference_set: "Which control genes to normalise to",
  group_cutoff: "Where to cut the comparison groups",
  undetermined: "What to do with wells that never amplified",
  amp_call: "Which curves count as amplified",
};
const CARD_KIND: Record<string, string> = {
  card_refset: "reference_set",
  card_cutoff: "group_cutoff",
  card_undetermined: "undetermined",
  card_amp_call: "amp_call",
};

/** The question an entry decided, in words. */
export function cardTitle(entry: Pick<ChainEntry, "card_id" | "card_title" | "card_kind">): string {
  if (entry.card_title) return entry.card_title;
  const kind = entry.card_kind ?? CARD_KIND[entry.card_id];
  return (kind && KIND_TITLE[kind]) || entry.card_id;
}

/** The option an entry chose, in words (its id when the server sends no label). */
export function optionLabel(entry: Pick<ChainEntry, "option" | "option_label">): string {
  return entry.option_label || entry.option;
}
