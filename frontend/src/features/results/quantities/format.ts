/**
 * How the Quantities view writes its numbers: quantities (copies) with three significant digits,
 * grouped (`2 610`, `56.8`), in powers of ten when large or small (`3.25 × 10⁸`); efficiencies
 * as percentages with one decimal; intervals with an en dash. Numbers are the API's; these only
 * format them.
 */
import { EN_DASH, MISSING, NNBSP, fixed } from "@/lib/format";

const SUPERSCRIPT: Record<string, string> = {
  "-": "⁻",
  "0": "⁰",
  "1": "¹",
  "2": "²",
  "3": "³",
  "4": "⁴",
  "5": "⁵",
  "6": "⁶",
  "7": "⁷",
  "8": "⁸",
  "9": "⁹",
};

/** `10⁸`, `10⁻²`: a power of ten. */
export function powerOfTen(exponent: number): string {
  return `10${String(exponent)
    .split("")
    .map((c) => SUPERSCRIPT[c] ?? c)
    .join("")}`;
}

function finite(x: number | null | undefined): x is number {
  return typeof x === "number" && Number.isFinite(x);
}

/**
 * A quantity: `2 610`, `56.8`, `0.118`, `3.25 × 10⁸` (three significant digits; a standard's
 * declared quantity is given with four, `18 750`, `1.875`, so it reads as it was declared).
 */
export function fmtQuantity(q: number | null | undefined, digits = 3): string {
  if (!finite(q) || q <= 0) return MISSING;
  const exponent = Math.floor(Math.log10(q));
  if (exponent >= 6 || exponent <= -3) {
    let mantissa = q / 10 ** exponent;
    let e = exponent;
    if (Number(mantissa.toPrecision(digits)) >= 10) {
      mantissa /= 10;
      e += 1;
    }
    return `${mantissa.toPrecision(digits)}${NNBSP}×${NNBSP}${powerOfTen(e)}`;
  }
  const rounded = Number(q.toPrecision(digits));
  const decimals = Math.max(0, digits - 1 - exponent);
  return fixed(rounded, decimals)
    .replace(/(\.\d*?)0+$/, "$1")
    .replace(/\.$/, "");
}

/** A standard's declared quantity (four significant digits, trailing zeros dropped). */
export const fmtStandard = (q: number | null | undefined): string => fmtQuantity(q, 4);

/** An interval of quantities: `2 520–2 700`. */
export function fmtQuantityRange(
  low: number | null | undefined,
  high: number | null | undefined,
): string {
  if (!finite(low) || !finite(high)) return MISSING;
  return `${fmtQuantity(low)}${EN_DASH}${fmtQuantity(high)}`;
}

/** An efficiency (1.0 = 100 %): `94.6 %`. */
export function fmtEfficiency(e: number | null | undefined): string {
  if (!finite(e)) return MISSING;
  return `${fixed(e * 100, 1)}${NNBSP}%`;
}

/** A share of wells: `3 of 4`. */
export function fmtWells(detected: number, total: number): string {
  return `${detected} of ${total}`;
}

/** The unit in words, or the standards' unit when the file did not name one. */
export function unitWords(unit: string | null | undefined): string {
  return unit ? unit : "units of the standards";
}
