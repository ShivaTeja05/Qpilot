/**
 * How the charts write numbers (docs/app.md §5 "Numbers"). Every number comes from the API; these
 * only format it. Thin no-break spaces keep "64 %" and "24 576" on one line.
 */

const NNBSP = " ";

/** A fold change as the page shows it: `3.59×`, `0.57×`, `0.0042×`, `123×`. */
export function fmtFold(fc: number | null | undefined): string {
  if (fc == null || !Number.isFinite(fc) || fc <= 0) return "–";
  if (fc >= 100) return `${Math.round(fc)}×`;
  if (fc >= 0.1) return `${fc.toFixed(2)}×`;
  return `${Number(fc.toPrecision(2))}×`;
}

/** A fold change given as log2. */
export function fmtFoldLog2(log2: number | null | undefined): string {
  return log2 == null || !Number.isFinite(log2) ? "–" : fmtFold(2 ** log2);
}

/** A fold change in words, relative to the comparison group: "3.32× higher", "2.10× lower". */
export function fmtFoldWords(log2: number): string {
  if (!Number.isFinite(log2)) return "–";
  return log2 >= 0 ? `${fmtFold(2 ** log2)} higher` : `${fmtFold(2 ** -log2)} lower`;
}

/** A confidence interval of fold changes: `[2.42–5.33]`. */
export function fmtCI(ci: readonly [number, number] | readonly number[] | null | undefined): string {
  if (!ci || ci.length < 2) return "–";
  return `[${fmtFold(ci[0]).replace("×", "")}–${fmtFold(ci[1]).replace("×", "")}]`;
}

/** A p-value: `0.003`, `0.41`, `< 0.001`. */
export function fmtP(p: number | null | undefined): string {
  if (p == null || !Number.isFinite(p)) return "–";
  if (p < 0.001) return `<${NNBSP}0.001`;
  return String(Number(p.toPrecision(2)));
}

/** A share of analyses (0–1) as a percentage: `64 %`. Never a confidence. */
export function fmtShare(share: number | null | undefined): string {
  if (share == null || !Number.isFinite(share)) return "–";
  return `${Math.round(share * 100)}${NNBSP}%`;
}

/** A percentage already in 0–100: `64 %`. */
export function fmtPct(pct: number | null | undefined): string {
  if (pct == null || !Number.isFinite(pct)) return "–";
  return `${Math.round(pct)}${NNBSP}%`;
}

/** A count with thin spaces between thousands: `24 576`, `90 396`. */
export function fmtCount(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "–";
  const s = String(Math.round(Math.abs(n)));
  const grouped = s.length > 4 ? s.replace(/\B(?=(\d{3})+(?!\d))/g, NNBSP) : s;
  return n < 0 ? `−${grouped}` : grouped;
}

/** A plain number with fixed decimals (geNorm M, V). */
export function fmtNum(v: number | null | undefined, digits = 2): string {
  return v == null || !Number.isFinite(v) ? "–" : v.toFixed(digits);
}

/** "1 gene", "3 genes". */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${fmtCount(n)} ${n === 1 ? one : many}`;
}
