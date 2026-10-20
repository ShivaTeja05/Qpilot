/** Reading the previewed tables' cells (text, exactly as the CSV holds them). */

/** A cell as a finite number, or null (an empty cell is a unit of the other group). */
export function cellNumber(cell: string | undefined): number | null {
  if (cell == null || cell.trim() === "") return null;
  const v = Number(cell);
  return Number.isFinite(v) ? v : null;
}
