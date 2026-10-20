/**
 * How the page writes numbers (docs/app.md §5 "Numbers"). Every number on screen goes through
 * one of these, so a fold, a CI or a p-value reads the same in every section.
 *
 *   fold 3.59× · 0.57×      CI [2.42–5.33]      p 0.003 · < 0.001
 *   share of analyses 64 %   counts 24 576       2 h ago      3f2a9c1b
 */

/** Narrow no-break space: groups digits and separates units without ever wrapping. */
export const NNBSP = " ";
/** En dash for ranges. */
export const EN_DASH = "–";
/** Minus sign (not a hyphen) for negative numbers. */
export const MINUS = "−";
/** Shown for a value that is missing or not a finite number. */
export const MISSING = "—";

function finite(x: number | null | undefined): x is number {
  return typeof x === "number" && Number.isFinite(x);
}

/** Digits grouped by three with narrow no-break spaces; a real minus sign. */
function group(text: string): string {
  const negative = text.startsWith("-");
  const body = negative ? text.slice(1) : text;
  const [int = "", frac] = body.split(".");
  const grouped = int.length > 3 ? int.replace(/\B(?=(\d{3})+(?!\d))/g, NNBSP) : int;
  return (negative ? MINUS : "") + grouped + (frac !== undefined ? `.${frac}` : "");
}

/** A count: `24 576`, `7`, `1 571`. */
export function count(n: number | null | undefined): string {
  if (!finite(n)) return MISSING;
  return group(String(Math.round(n)));
}

/** A number with a fixed number of decimals, grouped: `1 234.50`. */
export function fixed(x: number | null | undefined, decimals = 2): string {
  if (!finite(x)) return MISSING;
  const text = x.toFixed(decimals);
  // -0.00 is 0.00
  return group(Number(text) === 0 ? (0).toFixed(decimals) : text);
}

/** The bare number of a fold change: two decimals from 1 up, two significant digits below. */
export function foldNumber(fc: number | null | undefined): string {
  if (!finite(fc) || fc <= 0) return MISSING;
  if (fc >= 1) return fixed(fc, 2);
  const digits = Math.max(2, 1 - Math.floor(Math.log10(fc)));
  return fc.toFixed(Math.min(digits, 6));
}

/** A fold change: `3.59×`, `0.57×`, `0.034×`. */
export function fold(fc: number | null | undefined): string {
  const n = foldNumber(fc);
  return n === MISSING ? n : `${n}×`;
}

/** A fold change given as log2: `fold(2 ** log2fc)`. */
export function foldFromLog2(log2fc: number | null | undefined): string {
  return finite(log2fc) ? fold(2 ** log2fc) : MISSING;
}

/** A confidence interval of fold changes: `[2.42–5.33]`. */
export function ci(lo: number | null | undefined, hi: number | null | undefined): string {
  if (!finite(lo) || !finite(hi)) return MISSING;
  return `[${foldNumber(lo)}${EN_DASH}${foldNumber(hi)}]`;
}

/** A plain numeric range: `[24.1–31.8]`. */
export function range(
  lo: number | null | undefined,
  hi: number | null | undefined,
  decimals = 1,
): string {
  if (!finite(lo) || !finite(hi)) return MISSING;
  return `[${fixed(lo, decimals)}${EN_DASH}${fixed(hi, decimals)}]`;
}

/**
 * A p-value: `< 0.001`, `0.003`, `0.043`, `0.43`. A value is never rounded across 0.05
 * (0.0496 is `0.0496`, not `0.050`), so the page never shows a p on the wrong side of the rule.
 */
export function pValue(p: number | null | undefined): string {
  if (!finite(p) || p < 0) return MISSING;
  if (p < 0.001) return `<${NNBSP}0.001`;
  if (p >= 0.995) return "1.00";
  let decimals = p < 0.1 ? 3 : 2;
  let text = p.toFixed(decimals);
  while (decimals < 6 && p < 0.05 !== Number(text) < 0.05) {
    decimals += 1;
    text = p.toFixed(decimals);
  }
  return text;
}

/**
 * A share of analyses (a robustness fraction, never a confidence): `64 %`. Never rounds to the
 * ends: 0.996 is `> 99 %`, 0.004 is `< 1 %`; only exactly 1 and 0 read `100 %` and `0 %`.
 */
export function percent(fraction: number | null | undefined): string {
  if (!finite(fraction)) return MISSING;
  const f = Math.min(1, Math.max(0, fraction));
  if (f > 0 && f < 0.005) return `<${NNBSP}1${NNBSP}%`;
  if (f < 1 && f >= 0.995) return `>${NNBSP}99${NNBSP}%`;
  return `${Math.round(f * 100)}${NNBSP}%`;
}

/** "120 of 186" — a fraction as its counts. */
export function ofTotal(part: number | null | undefined, total: number | null | undefined): string {
  return `${count(part)} of ${count(total)}`;
}

/** Bytes as the page says them: `7.0 MB`, `640 KB`, `12 B`. */
export function bytes(n: number | null | undefined): string {
  if (!finite(n) || n < 0) return MISSING;
  if (n < 1024) return `${n}${NNBSP}B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)}${NNBSP}KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)}${NNBSP}MB`;
  return `${(n / 1024 ** 3).toFixed(1)}${NNBSP}GB`;
}

/** Seconds as the page shows them: `8 s`, `1 min 12 s`, `2 h 5 min`. */
export function duration(s: number | null | undefined): string {
  if (!finite(s)) return MISSING;
  const total = Math.max(0, Math.round(s));
  if (total < 60) return `${total}${NNBSP}s`;
  if (total < 3600) {
    const m = Math.floor(total / 60);
    const rest = total % 60;
    return rest ? `${m}${NNBSP}min ${rest}${NNBSP}s` : `${m}${NNBSP}min`;
  }
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  return m ? `${h}${NNBSP}h ${m}${NNBSP}min` : `${h}${NNBSP}h`;
}

/** Milliseconds since the epoch from a unix time in seconds, an ISO string or a Date. */
export function toMillis(t: number | string | Date | null | undefined): number | null {
  if (t == null) return null;
  if (t instanceof Date) return t.getTime();
  if (typeof t === "number") return Number.isFinite(t) ? (t < 1e11 ? t * 1000 : t) : null;
  const ms = Date.parse(t);
  return Number.isNaN(ms) ? null : ms;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A calendar date: `18 Oct 2026` (`18 Oct` in the current year). */
export function date(
  t: number | string | Date | null | undefined,
  now: number = Date.now(),
): string {
  const ms = toMillis(t);
  if (ms == null) return MISSING;
  const d = new Date(ms);
  const sameYear = d.getFullYear() === new Date(now).getFullYear();
  return `${d.getDate()} ${MONTHS[d.getMonth()]}${sameYear ? "" : ` ${d.getFullYear()}`}`;
}

/** A date and time: `18 Oct 2026, 19:43`. */
export function dateTime(t: number | string | Date | null | undefined): string {
  const ms = toMillis(t);
  if (ms == null) return MISSING;
  const d = new Date(ms);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ${hh}:${mm}`;
}

/** Relative time: `just now`, `5 min ago`, `2 h ago`, `yesterday`, `3 d ago`, then the date. */
export function relativeTime(
  t: number | string | Date | null | undefined,
  now: number = Date.now(),
): string {
  const ms = toMillis(t);
  if (ms == null) return MISSING;
  const s = Math.round((now - ms) / 1000);
  if (s < -60) return date(ms, now);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}${NNBSP}min ago`;
  if (s < 86400) return `${Math.round(s / 3600)}${NNBSP}h ago`;
  if (s < 2 * 86400) return "yesterday";
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}${NNBSP}d ago`;
  return date(ms, now);
}

/** The short form of a sha256 or chain hash: the first `n` hex characters. */
export function shortHash(hash: string | null | undefined, n = 8): string {
  if (!hash) return MISSING;
  return hash.slice(0, n);
}

/** `1 plate` / `64 plates`. */
export function plural(n: number | null | undefined, one: string, many = `${one}s`): string {
  return `${count(n)} ${n === 1 ? one : many}`;
}
