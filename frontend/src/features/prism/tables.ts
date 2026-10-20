/**
 * Reading the previewed tables: the CSV lines exactly as the bundle will hold them (comma
 * separated, `"` quotes doubled inside quoted cells; `qpilot/prism/tables.py`). Nothing is
 * computed here: the figure's statistics come from the server.
 */
import type { FigureGroup, GeneFigure, PreviewTable } from "./api";

/** One CSV line as cells (RFC 4180 quoting; no line breaks inside cells: the export refuses them). */
export function parseCsvLine(line: string): string[] {
  const cells: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]!;
    if (quoted) {
      if (ch === '"') {
        if (line[i + 1] === '"') {
          cell += '"';
          i++;
        } else {
          quoted = false;
        }
      } else {
        cell += ch;
      }
    } else if (ch === '"' && cell === "") {
      quoted = true;
    } else if (ch === ",") {
      cells.push(cell);
      cell = "";
    } else {
      cell += ch;
    }
  }
  cells.push(cell);
  return cells;
}

/** A previewed table as its header and rows of cells. */
export function readTable(table: PreviewTable): { columns: string[]; rows: string[][] } {
  const lines = table.head.filter((l) => l.length > 0);
  const parsed = lines.map(parseCsvLine);
  const columns = parsed[0] ?? table.columns;
  return { columns, rows: parsed.slice(1) };
}

/** A cell as a finite number, or null (an empty cell is a unit without a value in that group). */
export function cellNumber(cell: string | undefined): number | null {
  if (cell == null || cell.trim() === "") return null;
  const v = Number(cell);
  return Number.isFinite(v) ? v : null;
}

/**
 * The points of a column-layout table (`Sample, <group>, <group>`) when the server sent no
 * figure: every unit's value per group, with no mean or interval (those come from the server).
 * Returns null for any other layout or when the table holds only its first rows.
 */
export function pointsFromTable(gene: string, table: PreviewTable, layout: string): GeneFigure | null {
  if (layout !== "column") return null;
  const { columns, rows } = readTable(table);
  if (rows.length < table.n_rows) return null;
  const groups: FigureGroup[] = columns.slice(1).map((name) => ({ name, n: 0, mean: null, ci_lo: null, ci_hi: null, points: [] }));
  for (const row of rows) {
    const unit = row[0] ?? "";
    groups.forEach((g, i) => {
      const v = cellNumber(row[i + 1]);
      if (v != null) g.points.push({ unit, value: v });
    });
  }
  for (const g of groups) g.n = g.points.length;
  return { gene, groups };
}
