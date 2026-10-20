/**
 * Trace's words: what each flag and consequence means, in plain language, and how an effect
 * reads. Numbers come from the API; this only formats them (`@/lib/format`).
 */
import { fixed, fold, NNBSP } from "@/lib/format";
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
