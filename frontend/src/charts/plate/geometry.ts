/**
 * Plate geometry: well labels ↔ grid positions, and the plate's shape. Labels are the engine's
 * (`qpilot/qpcr/curves.py` `well_label`): row letters A–Z, then AA, AB, … from row 27; columns
 * from 1. A 96-well plate is 8 × 12 (A–H, 1–12), a 384-well plate 16 × 24 (A–P, 1–24).
 */

export interface WellPosition {
  /** 0-based row (A = 0). */
  row: number;
  /** 0-based column (1 = 0). */
  column: number;
}

export interface PlateShape {
  rows: number;
  columns: number;
}

const LABEL = /^([A-Z]+)(\d+)$/;

/** The row letters of a 0-based row: 0 → A, 25 → Z, 26 → AA. */
export function rowLetters(row: number): string {
  let n = row + 1;
  let out = "";
  while (n > 0) {
    const r = (n - 1) % 26;
    out = String.fromCharCode(65 + r) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

/** The label of a position: (1, 2) → B3. */
export function wellLabel(row: number, column: number): string {
  return `${rowLetters(row)}${column + 1}`;
}

/** A well label's position, or null when it is not a plate label (B3 → {row 1, column 2}). */
export function parseWell(label: string): WellPosition | null {
  const m = LABEL.exec(label.trim().toUpperCase());
  if (!m) return null;
  const letters = m[1]!;
  let row = 0;
  for (const ch of letters) row = row * 26 + (ch.charCodeAt(0) - 64);
  const column = Number(m[2]) - 1;
  if (column < 0) return null;
  return { row: row - 1, column };
}

/** The standard plate formats, smallest first. */
export const PLATE_FORMATS: readonly PlateShape[] = [
  { rows: 8, columns: 12 },
  { rows: 16, columns: 24 },
];

/**
 * The plate a set of well positions sits on: the smallest standard format that holds them all
 * (96, then 384), else exactly as large as the wells need.
 */
export function plateShape(
  positions: readonly WellPosition[],
  declared?: Partial<PlateShape>,
): PlateShape {
  if (declared?.rows && declared.columns) return { rows: declared.rows, columns: declared.columns };
  let rows = 0;
  let columns = 0;
  for (const p of positions) {
    rows = Math.max(rows, p.row + 1);
    columns = Math.max(columns, p.column + 1);
  }
  const standard = PLATE_FORMATS.find((f) => f.rows >= rows && f.columns >= columns);
  return standard ?? { rows: Math.max(rows, 1), columns: Math.max(columns, 1) };
}

/** The wells of the rectangle between two positions (inclusive), as labels. */
export function rectangle(a: WellPosition, b: WellPosition): string[] {
  const out: string[] = [];
  const [r0, r1] = a.row <= b.row ? [a.row, b.row] : [b.row, a.row];
  const [c0, c1] = a.column <= b.column ? [a.column, b.column] : [b.column, a.column];
  for (let r = r0; r <= r1; r += 1) for (let c = c0; c <= c1; c += 1) out.push(wellLabel(r, c));
  return out;
}

/** Natural order of well labels: by row, then column (A1, A2, …, A10, B1). */
export function compareWells(a: string, b: string): number {
  const pa = parseWell(a);
  const pb = parseWell(b);
  if (!pa || !pb) return a.localeCompare(b);
  return pa.row - pb.row || pa.column - pb.column;
}
