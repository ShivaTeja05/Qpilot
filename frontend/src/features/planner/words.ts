/**
 * The planner's words and encodings: slider stops, group and gene tones, sample-type words.
 * Every number shown comes from the API; these are only the choices a person can make and how
 * categories are drawn.
 */
import { roleStyle } from "@/charts/plate";
import { fold } from "@/lib/format";

/** The change worth finding, as a magnitude (≥ 1); the direction is chosen apart. */
export const FOLD_STOPS = [1.25, 1.5, 1.75, 2, 2.5, 3, 4, 5, 6, 8, 10] as const;
export const POWER_STOPS = [0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.99] as const;
export const N_STOPS = [
  2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 80, 100, 120, 150, 200, 250, 300, 400, 500,
  600, 800, 1000,
] as const;

/** The index of the stop nearest `value` (on a log scale). */
export function nearestStop(stops: readonly number[], value: number): number {
  let best = 0;
  for (let i = 1; i < stops.length; i++)
    if (Math.abs(Math.log(stops[i]! / value)) < Math.abs(Math.log(stops[best]! / value))) best = i;
  return best;
}

/** "3.00× up" / "3.00× down (0.33×)". */
export function changeWords(magnitude: number, direction: "up" | "down"): string {
  return direction === "up"
    ? `${fold(magnitude)} higher`
    : `${fold(magnitude)} lower (${fold(1 / magnitude)})`;
}

/** Group tones: the Beeswarm's (accent, muted, info, warn), so a group looks the same everywhere. */
export const GROUP_TONES = ["var(--accent)", "var(--text-muted)", "var(--info)", "var(--warn)"];

/** Gene tones on a plate map (a legend names each; every well also carries its gene's number). */
export const TARGET_TONES = [
  "var(--accent)",
  "var(--info)",
  "var(--v-depends)",
  "var(--v-check)",
  "var(--v-fragile)",
  "var(--v-solid)",
  "var(--up)",
  "var(--down)",
  "var(--v-caveats)",
  "var(--text-muted)",
];

export const TYPE_WORDS: Record<string, string> = {
  unkn: "sample",
  std: "standard (dilution point)",
  ntc: "no-template control (NTC)",
  nrt: "no-RT control (NRT)",
  pos: "inter-run calibrator (IRC)",
};

/** A control well's look (the plate kit's sample-type style). */
export function controlStyle(type: string): { color: string; letter: string } {
  const s = roleStyle(type);
  return { color: s.color, letter: s.letter || "·" };
}

/** Letters for groups on the plate (A, B, …), named in the legend. */
export function groupLetter(index: number): string {
  return String.fromCharCode(65 + (index % 26));
}
