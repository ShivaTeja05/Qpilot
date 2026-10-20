/**
 * What a plate map can colour its wells by, and how. Every encoding is a token (never raw hex)
 * and has a second channel (a letter, a shape, a number in the hover card), so colour never
 * carries meaning alone (docs/app.md §5).
 */
import { MISSING, count, fixed } from "@/lib/format";
import { ROLE_SHORT, ROLE_WORDS } from "@/lib/vocab";

/**
 * One well on the plate. Blind by construction: there is no group field, so the plate map can
 * never show which group a sample is in.
 */
export interface PlateWell {
  /** The well's label as the file names it: `A1` … `P24` (`AA1` from row 27). */
  well: string;
  sample?: string | null;
  target?: string | null;
  /** RDML sample type (`unkn`, `std`, `ntc`, `nrt`, `nac`, `pos`, `opt`, `ntp`); others shown as text. */
  role?: string | null;
  /** The amplification call in use (null: no call, e.g. no curve). */
  amplified?: boolean | null;
  cq?: number | null;
  /** The well's own amplification efficiency (LinRegPCR: fold per cycle, 2 = doubling). */
  efficiency?: number | null;
  /** Fit quality of LinRegPCR's window of linearity. */
  r2?: number | null;
  /** The Curve Judge reads this curve differently from the call in use (outlined). */
  disagree?: boolean;
  /** A person set this well's call (a corner mark). */
  personCall?: boolean;
  /** Text in this well's names reads like instructions: marked, never obeyed. */
  flagged?: boolean;
  /** Extra lines for the hover card (plain text). */
  notes?: readonly string[];
  /** Shown faded (filtered out, e.g. by a gene filter); not selectable. */
  dimmed?: boolean;
}

export type PlateLayer = "role" | "call" | "cq" | "efficiency" | "r2";

export const PLATE_LAYER_LABEL: Record<PlateLayer, string> = {
  role: "Sample type",
  call: "Amplification call",
  cq: "Cq",
  efficiency: "Efficiency",
  r2: "R²",
};

/** Layer options for a SegmentedControl / Select. */
export function layerOptions(layers: readonly PlateLayer[]): { value: PlateLayer; label: string }[] {
  return layers.map((value) => ({ value, label: PLATE_LAYER_LABEL[value] }));
}

// ---------------------------------------------------------------------------------------------
// Sample types

export interface RoleStyle {
  /** A CSS colour from the tokens. */
  color: string;
  /** One letter drawn in the well (none for study samples, the bulk of a plate). */
  letter: string;
  label: string;
}

const ROLE_STYLE: Record<string, Omit<RoleStyle, "label">> = {
  unkn: { color: "color-mix(in oklab, var(--text-faint) 55%, var(--surface))", letter: "" },
  std: { color: "var(--info)", letter: "S" },
  ntc: { color: "var(--warn)", letter: "N" },
  nrt: { color: "var(--v-check)", letter: "R" },
  nac: { color: "var(--v-fragile)", letter: "A" },
  pos: { color: "var(--ok)", letter: "P" },
  opt: { color: "var(--v-nocall)", letter: "O" },
  ntp: { color: "var(--v-depends)", letter: "T" },
};

export const ROLE_ORDER = ["unkn", "std", "ntc", "nrt", "nac", "pos", "opt", "ntp"] as const;

export function roleStyle(role: string | null | undefined): RoleStyle {
  const r = role ?? "";
  const known = ROLE_STYLE[r];
  if (known) return { ...known, label: ROLE_SHORT[r] ?? r };
  return { color: "var(--line-strong)", letter: "?", label: r ? `“${r}”` : "No type" };
}

export function roleWords(role: string | null | undefined): string {
  if (!role) return "no sample type declared";
  return ROLE_WORDS[role] ?? `sample type “${role}”`;
}

// ---------------------------------------------------------------------------------------------
// Calls

export type CallKey = "amplified" | "not_amplified" | "no_call";

export function callKey(amplified: boolean | null | undefined): CallKey {
  return amplified === true ? "amplified" : amplified === false ? "not_amplified" : "no_call";
}

export const CALL_STYLE: Record<CallKey, { label: string; color: string; words: string }> = {
  amplified: { label: "Amplified", color: "var(--accent)", words: "amplified" },
  not_amplified: { label: "Not amplified", color: "var(--danger)", words: "not amplified (no usable curve)" },
  no_call: { label: "No call", color: "var(--text-faint)", words: "no call" },
};

export const DISAGREE_COLOR = "var(--v-depends)";

// ---------------------------------------------------------------------------------------------
// Numbers

export type NumericLayer = "cq" | "efficiency" | "r2";

export const NUMERIC: Record<NumericLayer, { decimals: number; words: string; get: (w: PlateWell) => number | null | undefined }> = {
  cq: { decimals: 1, words: "Cq (cycle where the curve crosses LinRegPCR's threshold)", get: (w) => w.cq },
  efficiency: {
    decimals: 2,
    words: "the well's own efficiency (fold per cycle; 2.00 is a perfect doubling)",
    get: (w) => w.efficiency,
  },
  r2: { decimals: 4, words: "R² of LinRegPCR's window of linearity", get: (w) => w.r2 },
};

export function isNumericLayer(layer: PlateLayer): layer is NumericLayer {
  return layer === "cq" || layer === "efficiency" || layer === "r2";
}

export function numberText(layer: NumericLayer, value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? MISSING : fixed(value, NUMERIC[layer].decimals);
}

export interface Domain {
  lo: number;
  hi: number;
  /** True when values below `lo` / above `hi` exist and are drawn at the end of the scale. */
  clippedLo: boolean;
  clippedHi: boolean;
  /** Wells with a value. */
  n: number;
}

function quantile(sorted: readonly number[], q: number): number {
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  const a = sorted[lo]!;
  const b = sorted[hi]!;
  return a + (b - a) * (pos - lo);
}

/**
 * The colour scale's ends: the 2nd and 98th percentiles of the values when 50 or more wells have
 * one (so one bad well does not wash out the rest), else the full range. Null when no well has a
 * value.
 */
export function numericDomain(values: readonly (number | null | undefined)[]): Domain | null {
  const v = values.filter((x): x is number => typeof x === "number" && Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  const min = v[0]!;
  const max = v[v.length - 1]!;
  let lo = min;
  let hi = max;
  if (v.length >= 50) {
    lo = quantile(v, 0.02);
    hi = quantile(v, 0.98);
  }
  if (hi <= lo) {
    lo = min;
    hi = max;
  }
  return { lo, hi, clippedLo: min < lo, clippedHi: max > hi, n: v.length };
}

/** Where a value sits on the scale, 0–1 (clamped). */
export function position(domain: Domain, value: number): number {
  if (domain.hi <= domain.lo) return 0.5;
  return Math.min(1, Math.max(0, (value - domain.lo) / (domain.hi - domain.lo)));
}

/** The fill for a share of the scale: the accent mixed into the sunken surface (theme-aware). */
export function rampColor(t: number): string {
  const pct = Math.round(12 + 83 * Math.min(1, Math.max(0, t)));
  return `color-mix(in oklab, var(--accent) ${pct}%, var(--surface-sunken))`;
}

/** Ink that reads on a ramp fill (dark ink on light fills, light ink on deep ones). */
export function rampInk(t: number): string {
  return t > 0.6 ? "var(--accent-fg)" : "var(--text)";
}

// ---------------------------------------------------------------------------------------------
// Words

/** One line for screen readers and the table: what this well is under the layer. */
export function wellSummary(w: PlateWell, layer: PlateLayer): string {
  const parts = [w.well];
  if (w.sample) parts.push(`sample ${w.sample}`);
  if (w.target) parts.push(w.target);
  if (layer === "role") parts.push(roleStyle(w.role).label);
  else if (layer === "call") parts.push(CALL_STYLE[callKey(w.amplified)].words);
  else parts.push(`${PLATE_LAYER_LABEL[layer]} ${numberText(layer, NUMERIC[layer].get(w))}`);
  if (w.disagree) parts.push("the Curve Judge disagrees");
  if (w.personCall) parts.push("call set by a person");
  if (w.flagged) parts.push("names read like instructions (never obeyed)");
  if (w.dimmed) parts.push("filtered out");
  return parts.join(", ");
}

/** A sentence about the whole plate under a layer (the map's accessible summary). */
export function plateSummary(wells: readonly PlateWell[], layer: PlateLayer): string {
  const shown = wells.filter((w) => !w.dimmed);
  const head = `${count(shown.length)} wells`;
  if (layer === "role") {
    const by = new Map<string, number>();
    for (const w of shown) by.set(roleStyle(w.role).label, (by.get(roleStyle(w.role).label) ?? 0) + 1);
    return `${head} by sample type: ${[...by].map(([k, n]) => `${count(n)} ${k}`).join(", ")}.`;
  }
  if (layer === "call") {
    const n = { amplified: 0, not_amplified: 0, no_call: 0 } as Record<CallKey, number>;
    for (const w of shown) n[callKey(w.amplified)] += 1;
    const disagree = shown.filter((w) => w.disagree).length;
    const parts = [`${count(n.amplified)} amplified`, `${count(n.not_amplified)} not amplified`];
    if (n.no_call) parts.push(`${count(n.no_call)} with no call`);
    return `${head}: ${parts.join(", ")}${disagree ? `; the Curve Judge disagrees on ${count(disagree)}` : ""}.`;
  }
  const domain = numericDomain(shown.map(NUMERIC[layer].get));
  if (!domain) return `${head}; none has a ${PLATE_LAYER_LABEL[layer]}.`;
  return `${head} coloured by ${PLATE_LAYER_LABEL[layer]}, ${numberText(layer, domain.lo)} to ${numberText(layer, domain.hi)}; ${count(domain.n)} have a value.`;
}
