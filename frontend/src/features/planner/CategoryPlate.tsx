/**
 * One planned plate coloured by group or by gene. The plate kit's PlateMap is blind by design (a
 * well has no group) and colours by sample type, call or a number; a plan has groups and many
 * genes, so this grid draws categories with the kit's geometry and sample-type styles. Colour
 * never stands alone: every well carries its group's letter or its gene's number, the legend
 * names them, and each cell reads out in full. Arrow keys move; the hover card follows.
 */
import { LayoutGrid, Table2 } from "lucide-react";
import { useCallback, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { parseWell, rowLetters, wellLabel } from "@/charts/plate";
import { cn } from "@/lib/cn";
import { count } from "@/lib/format";
import { Table, TBody, TD, TH, THead, TR } from "@/ui";
import type { PlanLayoutPlate, PlanLayoutWell } from "./api";
import { GROUP_TONES, TARGET_TONES, TYPE_WORDS, controlStyle, groupLetter } from "./words";

export type CategoryLayer = "group" | "target";

interface Look {
  key: string;
  label: string;
  color: string;
  letter: string;
}

const PLATE_SHAPE: Record<number, [number, number]> = { 96: [8, 12], 384: [16, 24] };
const ROW_HEAD = "1.75rem";

function wellWords(w: PlanLayoutWell): string {
  const what =
    w.type === "unkn"
      ? `sample ${w.sample} (${w.group ?? "no group"})`
      : `${TYPE_WORDS[w.type] ?? w.type}${w.sample.startsWith("STD-") ? ` ${w.sample}` : ""}`;
  return `${w.well}: ${what}, ${w.target}, replicate ${w.replicate}`;
}

export function CategoryPlate({
  plate,
  layer,
  groups,
}: {
  plate: PlanLayoutPlate;
  layer: CategoryLayer;
  groups: string[];
}) {
  const [rows, columns] = PLATE_SHAPE[plate.wells_used + plate.wells_free] ?? [8, 12];
  const targets = useMemo(() => [...plate.genes, ...plate.refs], [plate]);
  const [asTable, setAsTable] = useState(false);
  const [cursor, setCursor] = useState({ row: 0, column: 0 });
  const [hover, setHover] = useState<{
    well: PlanLayoutWell;
    x: number;
    y: number;
    room: number;
  } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const summaryId = useId();

  const look = useCallback(
    (w: PlanLayoutWell): Look => {
      if (w.type !== "unkn") {
        const s = controlStyle(w.type);
        return { key: `type:${w.type}`, label: TYPE_WORDS[w.type] ?? w.type, ...s };
      }
      if (layer === "group") {
        const i = Math.max(0, groups.indexOf(w.group ?? ""));
        return {
          key: `group:${w.group}`,
          label: w.group ?? "",
          color: GROUP_TONES[i % GROUP_TONES.length]!,
          letter: groupLetter(i),
        };
      }
      const j = Math.max(0, targets.indexOf(w.target));
      return {
        key: `target:${w.target}`,
        label: `${w.target}${plate.refs.includes(w.target) ? " (reference)" : ""}`,
        color: TARGET_TONES[j % TARGET_TONES.length]!,
        letter: String(j + 1),
      };
    },
    [layer, groups, targets, plate.refs],
  );

  const byPos = useMemo(() => {
    const m = new Map<string, PlanLayoutWell>();
    for (const w of plate.wells) {
      const p = parseWell(w.well);
      if (p) m.set(`${p.row}:${p.column}`, w);
    }
    return m;
  }, [plate.wells]);

  const legend = useMemo(() => {
    const items = new Map<string, Look & { n: number }>();
    for (const w of plate.wells) {
      const l = look(w);
      const it = items.get(l.key);
      if (it) it.n += 1;
      else items.set(l.key, { ...l, n: 1 });
    }
    return [...items.values()].sort((a, b) => {
      const ca = a.key.startsWith("type:") ? 1 : 0;
      const cb = b.key.startsWith("type:") ? 1 : 0;
      return ca - cb || a.letter.localeCompare(b.letter, undefined, { numeric: true });
    });
  }, [plate.wells, look]);

  const summary = `${plate.name}: ${count(plate.wells_used)} wells used, ${count(plate.wells_free)} free; ${legend
    .map((l) => `${l.label} ${count(l.n)} wells`)
    .join(", ")}.`;

  const place = (el: HTMLElement, well: PlanLayoutWell) => {
    const a = el.getBoundingClientRect();
    const b = wrap.current?.getBoundingClientRect();
    if (!b) return;
    setHover({ well, x: a.left - b.left + a.width / 2, y: a.bottom - b.top + 6, room: b.width });
  };

  const move = (row: number, column: number) => {
    const next = {
      row: Math.max(0, Math.min(rows - 1, row)),
      column: Math.max(0, Math.min(columns - 1, column)),
    };
    setCursor(next);
    const el = gridRef.current?.querySelector<HTMLElement>(
      `[data-pos="${next.row}:${next.column}"]`,
    );
    if (el) {
      el.focus();
      const w = byPos.get(`${next.row}:${next.column}`);
      if (w) place(el, w);
      else setHover(null);
    }
  };

  const onKeyDown = (e: KeyboardEvent) => {
    const { row, column } = cursor;
    const keys: Record<string, [number, number]> = {
      ArrowUp: [row - 1, column],
      ArrowDown: [row + 1, column],
      ArrowLeft: [row, column - 1],
      ArrowRight: [row, column + 1],
      Home: [row, 0],
      End: [row, columns - 1],
    };
    const to = keys[e.key];
    if (to) {
      e.preventDefault();
      move(to[0], to[1]);
    } else if (e.key === "Escape") setHover(null);
  };

  const cellMin = columns > 12 ? 22 : 30;
  const cellMax = columns > 12 ? 40 : 56;
  const template = `${ROW_HEAD} repeat(${columns}, minmax(${cellMin}px, 1fr))`;

  return (
    <figure className="m-0 min-w-0" aria-label={summary}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <ul className="flex min-w-[14rem] flex-1 flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
          {legend.map((l) => (
            <li key={l.key} className="inline-flex items-center gap-1.5">
              <Disc color={l.color} letter={l.letter} size={16} />
              <span>{l.label}</span>
              <span className="font-mono tabular">
                {count(l.n)}
                <span className="sr-only"> wells</span>
              </span>
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={() => setAsTable((v) => !v)}
          aria-pressed={asTable}
          className="inline-flex h-7 items-center gap-1.5 rounded-md border border-line bg-surface px-2 text-[12px] text-muted hover:border-line-strong hover:text-fg"
        >
          {asTable ? <LayoutGrid size={14} aria-hidden /> : <Table2 size={14} aria-hidden />}
          {asTable ? "View as plate" : "View as table"}
        </button>
      </div>
      {asTable ? (
        <div className="max-h-[480px] overflow-auto rounded-lg border border-line">
          <Table caption={summary}>
            <THead>
              <TR>
                <TH>Well</TH>
                <TH>Sample</TH>
                <TH>Group</TH>
                <TH>Gene</TH>
                <TH>Type</TH>
                <TH numeric>Replicate</TH>
              </TR>
            </THead>
            <TBody>
              {plate.wells.map((w) => (
                <TR key={w.well}>
                  <TD className="font-mono">{w.well}</TD>
                  <TD>{w.sample}</TD>
                  <TD>{w.group ?? "—"}</TD>
                  <TD>{w.target}</TD>
                  <TD>{TYPE_WORDS[w.type] ?? w.type}</TD>
                  <TD numeric>{w.replicate}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
      ) : (
        <div ref={wrap} className="relative">
          <div className="-mx-1 overflow-x-auto px-1 pb-1">
            <div
              ref={gridRef}
              role="grid"
              aria-label={plate.name}
              aria-describedby={summaryId}
              aria-rowcount={rows + 1}
              aria-colcount={columns + 1}
              className="select-none"
              style={{
                minWidth: `calc(${ROW_HEAD} + ${columns * cellMin}px)`,
                maxWidth: `calc(${ROW_HEAD} + ${columns * cellMax}px)`,
              }}
              onKeyDown={onKeyDown}
              onMouseLeave={() => setHover(null)}
              onBlur={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setHover(null);
              }}
            >
              <div
                role="row"
                aria-rowindex={1}
                className="grid"
                style={{ gridTemplateColumns: template }}
              >
                <div role="columnheader" aria-colindex={1}>
                  <span className="sr-only">Row</span>
                </div>
                {Array.from({ length: columns }, (_, c) => (
                  <div
                    key={c}
                    role="columnheader"
                    aria-colindex={c + 2}
                    className="pb-0.5 text-center font-mono text-[10px] leading-4 text-faint tabular"
                  >
                    {c + 1}
                  </div>
                ))}
              </div>
              {Array.from({ length: rows }, (_, r) => (
                <div
                  key={r}
                  role="row"
                  aria-rowindex={r + 2}
                  className="grid"
                  style={{ gridTemplateColumns: template }}
                >
                  <div
                    role="rowheader"
                    aria-colindex={1}
                    className="flex items-center justify-center font-mono text-[10px] text-faint"
                  >
                    {rowLetters(r)}
                  </div>
                  {Array.from({ length: columns }, (_, c) => {
                    const w = byPos.get(`${r}:${c}`) ?? null;
                    const l = w ? look(w) : null;
                    const focusable = cursor.row === r && cursor.column === c;
                    return (
                      <div
                        key={c}
                        role="gridcell"
                        aria-colindex={c + 2}
                        aria-label={w ? wellWords(w) : `${wellLabel(r, c)}, empty`}
                        tabIndex={focusable ? 0 : -1}
                        data-pos={`${r}:${c}`}
                        onMouseEnter={(e) => (w ? place(e.currentTarget, w) : setHover(null))}
                        onFocus={(e) => {
                          setCursor({ row: r, column: c });
                          if (w) place(e.currentTarget, w);
                        }}
                        className={cn(
                          "relative m-px aspect-square rounded-md p-[6%] outline-none focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus",
                          w && "hover:bg-bg-subtle",
                        )}
                      >
                        {l ? <Disc color={l.color} letter={l.letter} /> : <Empty />}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
          {hover ? (
            <div
              role="presentation"
              className="pointer-events-none absolute z-20 w-max max-w-[260px] rounded-lg border border-line bg-surface px-3 py-2 text-[12px] leading-snug text-fg shadow-md"
              style={{
                left: Math.max(0, Math.min(hover.x - 120, hover.room - 250)),
                top: hover.y,
              }}
            >
              <div className="font-semibold">
                <span className="font-mono">{hover.well.well}</span> · {hover.well.sample}
              </div>
              <div className="text-muted">
                {hover.well.group ? `${hover.well.group} · ` : ""}
                {hover.well.target} · replicate {hover.well.replicate}
              </div>
              <div className="text-muted">{TYPE_WORDS[hover.well.type] ?? hover.well.type}</div>
            </div>
          ) : null}
          <p id={summaryId} className="sr-only">
            {summary}
          </p>
        </div>
      )}
    </figure>
  );
}

/** A well: a soft disc ringed in its category's colour, with its letter (or number). */
function Disc({ color, letter, size }: { color: string; letter: string; size?: number }) {
  const box = size ? { width: size, height: size } : { width: "100%", height: "100%" };
  return (
    <svg viewBox="0 0 24 24" {...box} aria-hidden="true" focusable="false">
      <circle
        cx={12}
        cy={12}
        r={9.5}
        style={{ fill: `color-mix(in oklab, ${color} 28%, var(--surface))`, stroke: color }}
        strokeWidth={2}
      />
      {letter ? (
        <text
          x={12}
          y={12}
          dy="0.35em"
          textAnchor="middle"
          fontSize={letter.length > 1 ? 8.5 : 10}
          fontWeight={700}
          style={{ fill: "var(--text)" }}
        >
          {letter}
        </text>
      ) : null}
    </svg>
  );
}

function Empty() {
  return (
    <svg viewBox="0 0 24 24" width="100%" height="100%" aria-hidden="true" focusable="false">
      <circle
        cx={12}
        cy={12}
        r={8.5}
        fill="none"
        style={{ stroke: "var(--line)" }}
        strokeWidth={1}
      />
    </svg>
  );
}
