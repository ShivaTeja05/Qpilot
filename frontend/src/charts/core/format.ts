/**
 * How the charts write numbers: the page's own formats (`@/lib/format`, docs/app.md §5) under the
 * names the charts and their adapters use. Every number comes from the API; these only format it.
 */
import { NNBSP, ci, count, fixed, fold, foldFromLog2, percent, plural, pValue } from "@/lib/format";

/** A fold change: `3.59×`, `0.57×`, `0.0042×`. */
export const fmtFold = (fc: number | null | undefined): string => fold(fc);

/** A fold change given as log2. */
export const fmtFoldLog2 = (log2: number | null | undefined): string => foldFromLog2(log2);

/** A fold change in words, relative to the comparison group: "3.32× higher", "2.10× lower". */
export function fmtFoldWords(log2: number): string {
  if (!Number.isFinite(log2)) return fold(null);
  return log2 >= 0 ? `${fold(2 ** log2)} higher` : `${fold(2 ** -log2)} lower`;
}

/** A confidence interval of fold changes: `[2.42–5.33]`. */
export function fmtCI(v: readonly number[] | null | undefined): string {
  return ci(v?.[0], v?.[1]);
}

/** A p-value: `0.003`, `0.41`, `< 0.001` (never rounded across 0.05). */
export const fmtP = (p: number | null | undefined): string => pValue(p);

/** A share of analyses (0–1): `64 %`. A robustness fraction, never a confidence. */
export const fmtShare = (share: number | null | undefined): string => percent(share);

/** A percentage already in 0–100: `64 %`. */
export const fmtPct = (pct: number | null | undefined): string =>
  percent(pct == null ? pct : pct / 100);

/** A count with narrow spaces between thousands: `24 576`. */
export const fmtCount = (n: number | null | undefined): string => count(n);

/** A plain number with fixed decimals (geNorm M, V). */
export const fmtNum = (v: number | null | undefined, digits = 2): string => fixed(v, digits);

/** "1 gene", "3 genes": the page's own (`@/lib/format`). */
export { plural };

export { NNBSP };
