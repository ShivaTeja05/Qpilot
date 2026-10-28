/** Melt calls in words: a short label and a tone per call (glyph + word, never colour alone). */
import type { MeltAssay, MeltCall, MeltStatus } from "./api";
import { fixed, plural } from "@/lib/format";

export type MeltTone = "ok" | "warn" | "danger" | "neutral";

/** A call's short label (the chip); the route's `status_text` is the long one. */
export const STATUS_WORD: Record<MeltStatus, string> = {
  one_product: "One product",
  extra_peak: "Extra peak",
  tm_off: "Not at the product's Tm",
  no_peak: "No melt peak",
  not_amplified: "Not amplified",
  no_product: "Nothing melted",
  product: "Product in a control",
  dimer: "Primer-dimer",
  other_product: "Another product",
  unclassified: "Unclassified peak",
  not_judged: "Not judged",
  unreadable: "Cannot be read",
  no_melt: "No melt curve",
};

/** The tone of a call under the shipped pack's severities (G-MELT). */
export const STATUS_TONE: Record<MeltStatus, MeltTone> = {
  one_product: "ok",
  no_product: "ok",
  dimer: "ok",
  extra_peak: "warn",
  product: "warn",
  other_product: "warn",
  tm_off: "danger",
  no_peak: "danger",
  not_amplified: "neutral",
  unclassified: "neutral",
  not_judged: "neutral",
  unreadable: "neutral",
  no_melt: "neutral",
};

/** Calls of no-template controls (an assay with only these has no product of its own). */
const CONTROL_CALLS = new Set(["no_product", "product", "dimer", "other_product", "unclassified"]);

/** `82.0 °C`. */
export function celsius(x: number | null | undefined, decimals = 1): string {
  return x == null || !Number.isFinite(x) ? "—" : `${fixed(x, decimals)} °C`;
}

/** A signed difference in degrees: `+1.6 °C`, `−0.4 °C`. */
export function delta(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return "—";
  const shown = fixed(Math.abs(x), 1);
  const sign = Number(shown) === 0 ? "" : x > 0 ? "+" : "−";
  return `${sign}${shown} °C`;
}

/** Where an assay's product melts, in one sentence (every number from the route). */
export function assaySentence(a: MeltAssay, tolerance: number): string {
  const controlsOnly = Object.keys(a.counts).every((k) => CONTROL_CALLS.has(k));
  if (a.expected_tm == null && controlsOnly) {
    return "Only no-template controls of this target here: a peak in them is measured against the plate's other products.";
  }
  if (a.expected_tm == null) {
    return "Too few study wells melted on this plate to say where the product melts, and the file declares no temperature: only extra peaks are judged.";
  }
  const where =
    a.expected_source === "file"
      ? `The file declares the product to melt at ${celsius(a.expected_tm)}`
      : `The product melts at ${celsius(a.expected_tm)}, the median of ${plural(a.n_reference, "study well")}`;
  const range =
    a.expected_source === "median" && a.min_tm != null && a.max_tm != null && a.n_reference > 1
      ? ` (${celsius(a.min_tm)} to ${celsius(a.max_tm)})`
      : "";
  return `${where}${range}; a well's product passes within ±${fixed(tolerance, 1)} °C of it.`;
}

/** How many wells of a plate G-MELT points at, in words. */
export function flaggedSentence(calls: readonly MeltCall[]): string {
  const n = calls.filter((c) => c.flagged).length;
  return n === 0
    ? "G-MELT points at no well on this plate."
    : `G-MELT points at ${plural(n, "well")} on this plate.`;
}
