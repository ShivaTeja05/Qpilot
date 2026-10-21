/**
 * Trace's words: what each flag and consequence means, in plain language, and how an effect
 * reads. Numbers come from the API; this only formats them (`@/lib/format`).
 */
import { count, fixed, fold, NNBSP } from "@/lib/format";
import type { CallView, Place, Sample, Well } from "./api";

export const CALL_WORD: Record<string, string> = { up: "up", down: "down", none: "no call" };

export const WELL_FLAG: Record<string, { word: string; detail: string }> = {
  reference_pull: {
    word: "Control gene off",
    detail: "Reads far from what the sample's other control genes predict.",
  },
  no_amplification: { word: "No curve", detail: "Did not count as amplified, so it has no value." },
  excluded: { word: "Excluded", detail: "A person excluded this well." },
  late_cq: {
    word: "Late for its plate",
    detail: "Its Cq is far later than the plate's other wells of this gene.",
  },
  efficiency_outlier: {
    word: "Odd efficiency",
    detail: "Its efficiency is unlike the plate's other wells of this gene.",
  },
  ntc_window: {
    word: "Near an NTC",
    detail: "Comes up less than five cycles before an amplifying no-template control on its plate.",
  },
  curve_note: { word: "LinRegPCR note", detail: "LinRegPCR wrote a note on this curve." },
};

export const SAMPLE_FLAG: Record<string, { word: string; detail: string }> = {
  reference_pull: {
    word: "Control-gene well off",
    detail:
      "One of its control-gene wells disagrees with its others, so every value of the sample moves.",
  },
  input_shift: {
    word: "Late on every gene",
    detail:
      "Every gene of the sample reads low together: consistent with the amount of RNA or cDNA put in.",
  },
  low_efficiency: {
    word: "Low efficiency",
    detail:
      "Its wells amplify less efficiently than their plates' others: consistent with an inhibitor.",
  },
  far_from_group: {
    word: "Far from its group",
    detail:
      "Its value is far from its group's; with one well per sample and gene that cannot be told apart from biology.",
  },
  ntc_window: {
    word: "Near an NTC",
    detail: "One of its wells comes up close to an amplifying no-template control.",
  },
  curve_note: { word: "Curve note", detail: "LinRegPCR noted something on its well of this gene." },
};

export const CONSEQUENCE: Record<
  Place["consequence"],
  { word: string; tone: "danger" | "warn" | "neutral" }
> = {
  changes_call: { word: "Changes the call", tone: "danger" },
  moves_number: { word: "Moves the number", tone: "warn" },
  changes_nothing: { word: "Changes nothing here", tone: "neutral" },
};

export const PLACE_KIND: Record<Place["kind"], string> = {
  reference_well: "Control-gene well",
  target_well: "Target well",
  sample: "Whole sample",
  plate_control: "No-template control",
};

/** "+5.3 %" / "−2.1 %": how much setting a sample aside moves the fold change. */
export function effectPercent(dLog2: number): string {
  const pct = 100 * (2 ** dLog2 - 1);
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "";
  return `${sign}${fixed(Math.abs(pct), Math.abs(pct) < 10 ? 1 : 0)}${NNBSP}%`;
}

/** Which way a sample pushes the fold change by being there (the opposite of setting it aside). */
export function push(sample: Pick<Sample, "d_log2fc">): "raises" | "lowers" | "none" {
  if (sample.d_log2fc < 0) return "raises";
  if (sample.d_log2fc > 0) return "lowers";
  return "none";
}

/** Two decimals, more when two would round a fold onto the rule's line (1.9996 is not 2.00). */
export function nearLine(x: number, lineLog2 = 1): string {
  const line = 2 ** lineLog2;
  let d = 2;
  while (d < 6 && x !== line && fixed(x, d) === fixed(line, d)) d += 1;
  return fixed(x, d);
}

/** "1.98-fold lower" / "3.32× higher": a fold change in words, as the trace's sentences say. */
export function changeWords(log2fc: number, lineLog2 = 1): string {
  if (!Number.isFinite(log2fc)) return "—";
  if (log2fc < 0) return `${nearLine(2 ** -log2fc, lineLog2)}-fold lower`;
  const fc = 2 ** log2fc;
  return `${fc >= 1 ? `${nearLine(fc, lineLog2)}×` : fold(fc)} higher`;
}

export function callLine(call: CallView): string {
  return `${CALL_WORD[call.conclusion] ?? call.conclusion}, ${changeWords(call.log2fc)}`;
}

/** "HMBS_20080318 · K22". */
export function address(well: Pick<Well, "plate" | "well">): string {
  return `${well.plate} · ${well.well}`;
}

export function wellRole(well: Pick<Well, "role">): string {
  return (
    (
      {
        target: "target",
        reference: "control gene",
        marker: "marker gene",
        candidate_reference: "candidate control gene",
        ntc: "no-template control",
        standard: "standard",
        other: "other",
      } as Record<string, string>
    )[well.role] ?? well.role
  );
}

/** The samples' sizes in the diagram: area ∝ |influence|, never below a visible dot. */
export function radiusScale(samples: readonly Pick<Sample, "d_log2fc">[], min = 5, max = 22) {
  const top = Math.max(1e-12, ...samples.map((s) => Math.abs(s.d_log2fc)));
  return (d: number) => min + (max - min) * Math.sqrt(Math.min(1, Math.abs(d) / top));
}

// ---- Where to look (qpilot/qpcr/trace.py, its words in qpilot/explain/trace_text.py) ------------

/** What a place is: a well of a reference or target gene, a control well, or the sample's tube. */
export const WHERE_ROLE: Record<string, string> = {
  reference_well: "Reference well",
  target_well: "Target well",
  control_well: "Control well",
  sample: "Whole sample",
};

/** The consequence of a place or an option; the word is the API's own. */
export const WHERE_TONE: Record<string, "danger" | "warn" | "neutral"> = {
  changes_call: "danger",
  beyond_ci: "warn",
  changes_nothing: "neutral",
};

/** The fingerprint checks (S1–S7) in words, for the checks that found nothing. */
const CHECK_WORD: Record<string, string> = {
  S1: "reference wells against each other",
  S2: "whole-sample lateness",
  S4: "whole-sample efficiency",
  S5: "curve notes",
  S6: "the well against its plate's no-template controls",
  S7: "samples left out",
};

/** What the data cannot show, in words (the engine's CANNOT_SHOW and its study-level limits). */
const CANNOT_WORD: Record<string, string> = {
  S8: "flagged samples sharing an extraction batch, RT batch, operator or date (no sample sheet with annotations)",
  S9: "a replicate well that is off (replicate wells are not compared yet)",
  single_target_well:
    "a single target well that is off: without replicates it cannot be told apart from biology",
  group_wide_fault: "a fault shared by every sample of one group: it looks like biology",
  sample_swap: "the wrong sample in the tube",
  rna_integrity: "RNA integrity",
  rt_replicates: "RT replicates",
  no_rt_controls: "no-RT controls",
  position_confounded:
    "a plate-position effect: every sample sits at the same well on every plate, so position and sample cannot be told apart",
};

/** A code the page has no words for, said as plainly as it can be. */
function unknownCode(code: string): string {
  return /^S\d+$/.test(code) ? `check ${code}` : code.replace(/_/g, " ");
}

/**
 * The checks that found nothing, in words: the no-template controls of each plate (`S6:<plate>`)
 * gathered into one line, then the other checks.
 */
export function checkedWords(codes: readonly string[]): string[] {
  const plates = codes.filter((c) => c.startsWith("S6:")).map((c) => c.slice(3));
  const out: string[] = [];
  if (plates.length === 1) out.push(`no-template controls on plate ${plates[0]}`);
  else if (plates.length > 1 && plates.length <= 6)
    out.push(`no-template controls on plates ${plates.join(", ")}`);
  else if (plates.length > 6) out.push(`no-template controls on ${count(plates.length)} plates`);
  for (const c of codes) if (!c.startsWith("S6:")) out.push(CHECK_WORD[c] ?? unknownCode(c));
  return out;
}

export function cannotWords(codes: readonly string[]): string[] {
  return codes.map((c) => CANNOT_WORD[c] ?? unknownCode(c));
}

/** "Sample 2016 · plate HMBS_20080318 · well K22" (a whole-sample place has no plate or well). */
export function placeWords(p: { sample: string; plate?: string | null; well?: string | null }) {
  return [
    `Sample ${p.sample}`,
    p.plate ? `plate ${p.plate}` : null,
    p.well ? `well ${p.well}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** A well typed as `PLATE:WELL` (or `PLATE/WELL`); the plate's name may hold anything else. */
export const WELL_INPUT = /^[^/:]+[:/][^/:]+$/;
