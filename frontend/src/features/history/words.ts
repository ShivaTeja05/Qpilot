/** The History section's words: actors, stages, entry statuses and each point in a sentence. */
import { dateTime } from "@/lib/format";
import type { Tone } from "@/ui";
import type { Point } from "./model";

export const ACTOR_WORD: Record<string, string> = {
  human: "A person",
  agent: "An agent",
  system: "qPilot (automatic)",
};

/** Who acted, inside a sentence ("decided by a person"). */
export const ACTOR_LOWER: Record<string, string> = {
  human: "a person",
  agent: "an agent",
  system: "qPilot (automatic)",
};

/** A span of two times, the second left out when both read the same. */
export function timeSpan(first: string, last: string): string {
  const a = dateTime(first);
  const b = dateTime(last);
  return a === b ? a : `${a} – ${b}`;
}

export const STAGE_WORD: Record<string, string> = {
  design: "Design",
  curves: "Curves",
  choices: "Choices",
  prism: "Prism",
  other: "Studio",
};

export const STATUS_WORD: Record<string, { word: string; tone: Tone }> = {
  applied: { word: "Applied", tone: "ok" },
  auto: { word: "Decided automatically", tone: "neutral" },
  pending_human: { word: "Waiting for a person", tone: "warn" },
  rejected: { word: "Turned down", tone: "danger" },
  stale: { word: "Not applied (stale)", tone: "neutral" },
};

export const ACTION_WORD: Record<string, string> = {
  propose: "proposed",
  accept: "accepted",
  edit: "edited and accepted",
  reject: "turned down",
  supersede: "replaced",
};

export const CAUSE_WORD: Record<string, string> = {
  design: "the design",
  choices: "the choices",
  both: "both",
  unknown: "cannot tell",
};

/** A point of the timeline in one sentence (its accessible name and the map's caption). */
export function pointTitle(point: Point): string {
  if (point.kind === "earlier") {
    const after = point.study.after ? ` (made after: ${point.study.after})` : "";
    return `The earlier analysis of this file${after}, as it stood at its last decision`;
  }
  const s = point.step;
  if (s.kind === "start") return "Step 0: the study as analysed, every choice as planned";
  const who = ACTOR_WORD[s.actor ?? ""] ?? "Someone";
  const what = `${s.card_title ?? s.card_id}: ${s.option_label ?? s.option}`;
  const verb =
    s.status === "pending_human"
      ? "asked for"
      : s.status === "rejected"
        ? "turned down a request for"
        : s.undo
          ? "undid back to"
          : "chose";
  const when = s.at ? `, ${dateTime(s.at)}` : "";
  const carried = s.carried ? " (carried over from the earlier analysis of these data)" : "";
  return `Step ${s.seq}: ${who} ${verb} ${what}${carried}${when}`;
}
