/**
 * What each mark means, for the charts: the page's one vocabulary (`@/lib/vocab`, docs/app.md §5)
 * under the names the charts and their adapters use. Conclusions are arrows, verdicts the audit's
 * glyphs, levels their own glyphs (and a bar count in tags): meaning is never colour alone.
 */
import {
  CONCLUSION,
  CONCLUSIONS,
  LEVEL,
  LEVELS,
  VERDICT,
  VERDICT_ORDER as ORDER,
  asConclusion,
  asLevel,
  isVerdict as vocabIsVerdict,
  type Conclusion,
  type Level,
  type Mark,
  type Shape,
  type Verdict,
} from "@/lib/vocab";

export type { Mark, Shape };
export type CallKey = Conclusion;
export type VerdictKey = Verdict;
export type LevelKey = Level;

/** Conclusions with the arrow and the short word the charts print. */
const callMark = (c: CallKey) => ({
  ...CONCLUSION[c],
  arrow: CONCLUSION[c].glyph,
  short: CONCLUSION[c].word,
});
export const CALLS: Record<CallKey, Mark & { arrow: string; short: string }> = {
  up: callMark("up"),
  down: callMark("down"),
  none: callMark("none"),
};

export const CALL_ORDER: CallKey[] = CONCLUSIONS;

/**
 * The call of an audit row: its `call_key` when the API sends one, else read from the audit's own
 * words ("called up (higher in …)", "called down", "no change called", "no call").
 */
export function callKey(row: { call_key?: string | null; call?: string | null } | string): CallKey {
  if (typeof row === "string") return asConclusion(row);
  const key = row.call_key;
  if (key === "up" || key === "down" || key === "none") return key;
  return asConclusion(row.call);
}

/** The audit's verdicts, most urgent first. */
export const VERDICT_ORDER: VerdictKey[] = ORDER;
export const VERDICTS = VERDICT;
export const isVerdict = (v: unknown): v is VerdictKey => vocabIsVerdict(v);

/** Confidence levels (ordinal, never a probability), highest first. */
export const LEVEL_ORDER: LevelKey[] = LEVELS;
export { LEVEL as LEVELS };
export const isLevel = (v: unknown): v is LevelKey => typeof v === "string" && asLevel(v) === v;

/** Option tiers in the audit. */
export const TIER_WORDS: Record<string, string> = {
  prespecified: "your planned analysis",
  defensible: "reasonable alternative",
  common_practice: "common shortcut",
};
