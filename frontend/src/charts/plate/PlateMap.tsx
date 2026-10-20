/**
 * The plate map: every well of one plate (96 or 384, rows A–P × columns 1–24) coloured by a
 * layer, with a legend, a hover card, keyboard navigation, single or multiple selection and a
 * table view. It never shows group labels: {@link PlateWell} has no group (blind stages).
 *
 * Keyboard (ARIA grid, one tab stop): arrows move; Shift+arrows extend the selection; Space adds
 * or removes the well; Enter selects it and opens it (`onActivate`); Home/End go to the row's
 * ends, ⌘/Ctrl+Home/End to the plate's; ⌘/Ctrl+A selects every well shown; Escape clears.
 * Mouse: click selects one well, ⌘/Ctrl-click adds or removes, Shift-click selects the
 * rectangle from the last well; a row letter or column number selects the row or column.
 */
import { Table2, LayoutGrid } from "lucide-react";
import {
  memo,
  useCallback,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FocusEvent,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { cn } from "@/lib/cn";
import { fixed } from "@/lib/format";
import { NumberCell, Table, TBody, TD, TH, THead, TR } from "@/ui";
import { compareWells, parseWell, plateShape, rectangle, rowLetters, wellLabel, type WellPosition } from "./geometry";
import {
  CALL_STYLE,
  NUMERIC,
  PLATE_LAYER_LABEL,
  callKey,
  isNumericLayer,
  numberText,
  numericDomain,
  plateSummary,
  roleStyle,
  roleWords,
  wellSummary,
  type Domain,
  type PlateLayer,
  type PlateWell,
} from "./layers";
import { PlateLegend } from "./PlateLegend";
import { WellGlyph } from "./WellGlyph";

export interface PlateMapProps {
  wells: readonly PlateWell[];
  layer: PlateLayer;
  /** What this plate is, for screen readers and the table caption ("Plate ODC1_20080226"). */
  label: string;
  /** The plate's shape; inferred from the labels (96, else 384) when not given. */
  rows?: number;
  columns?: number;
  /** Selected well labels (controlled). Without `onSelectedChange` the map is read-only. */
  selected?: readonly string[];
  onSelectedChange?: (wells: string[]) => void;
  /** Enter, or a double-click, on a well. */
  onActivate?: (well: string) => void;
  /** Allow more than one selected well (default true). */
  multiple?: boolean;
  /** Controls in the header row (a layer switch, a filter). */
  controls?: ReactNode;
  caption?: ReactNode;
  hideLegend?: boolean;
  /** Extra lines in the hover card for a well (plain text or nodes). */
  renderDetails?: (well: PlateWell) => ReactNode;
  className?: string;
}

interface Located extends PlateWell, WellPosition {}

const ROW_HEAD = "1.75rem";

export function PlateMap({
  wells,
  layer,
  label,
  rows,
  columns,
  selected,
  onSelectedChange,
  onActivate,
  multiple = true,
  controls,
  caption,
  hideLegend,
  renderDetails,
  className,
}: PlateMapProps) {
  const [asTable, setAsTable] = useState(false);
  const captionId = useId();

  // Wells by position; labels that are not plate labels are listed in the table only.
  const { grid, located, unplaced, shape } = useMemo(() => {
    const located: Located[] = [];
    const unplaced: PlateWell[] = [];
    for (const w of wells) {
      const p = parseWell(w.well);
      if (p) located.push({ ...w, ...p });
      else unplaced.push(w);
    }
    const shape = plateShape(located, { rows, columns });
    const grid = new Map<string, Located>();
    for (const w of located) if (w.row < shape.rows && w.column < shape.columns) grid.set(`${w.row}:${w.column}`, w);
    return { grid, located, unplaced, shape };
  }, [wells, rows, columns]);

  const domain = useMemo<Domain | null>(
    () => (isNumericLayer(layer) ? numericDomain(wells.filter((w) => !w.dimmed).map(NUMERIC[layer].get)) : null),
    [wells, layer],
  );

  const selectedSet = useMemo(() => new Set(selected ?? []), [selected]);
  const selectable = Boolean(onSelectedChange);
  const summary = `${label}. ${plateSummary(wells, layer)}`;

  return (
    <figure className={cn("m-0 min-w-0", className)} aria-label={summary} aria-describedby={caption ? captionId : undefined}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          {!hideLegend && !asTable ? <PlateLegend wells={wells} layer={layer} domain={domain} /> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {controls}
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
      </div>

      {asTable ? (
        <WellTable
          wells={[...located, ...unplaced]}
          label={label}
          selected={selectedSet}
          onPick={
            selectable || onActivate
              ? (w) => {
                  onSelectedChange?.([w]);
                  onActivate?.(w);
                }
              : undefined
          }
        />
      ) : (
        <PlateGrid
          grid={grid}
          rows={shape.rows}
          columns={shape.columns}
          layer={layer}
          domain={domain}
          label={label}
          summary={summary}
          selected={selectedSet}
          onSelectedChange={onSelectedChange}
          onActivate={onActivate}
          multiple={multiple}
          renderDetails={renderDetails}
        />
      )}
      {unplaced.length && !asTable ? (
        <p className="mt-2 text-[12px] text-muted">
          {unplaced.length === 1 ? "One well has" : `${unplaced.length} wells have`} a position that is not a plate
          label; “View as table” lists {unplaced.length === 1 ? "it" : "them"}.
        </p>
      ) : null}
      {caption ? (
        <figcaption id={captionId} className="mt-2 text-[12px] leading-relaxed text-muted">
          {caption}
        </figcaption>
      ) : null}
    </figure>
  );
}

// ---------------------------------------------------------------------------------------------
// The grid

interface GridProps {
  grid: Map<string, Located>;
  rows: number;
  columns: number;
  layer: PlateLayer;
  domain: Domain | null;
  label: string;
  summary: string;
  selected: ReadonlySet<string>;
  onSelectedChange?: (wells: string[]) => void;
  onActivate?: (well: string) => void;
  multiple: boolean;
  renderDetails?: (well: PlateWell) => ReactNode;
}

function PlateGrid({
  grid,
  rows,
  columns,
  layer,
  domain,
  label,
  summary,
  selected,
  onSelectedChange,
  onActivate,
  multiple,
  renderDetails,
}: GridProps) {
  const gridRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [cursor, setCursor] = useState<WellPosition>(() => firstWell(grid) ?? { row: 0, column: 0 });
  const [hover, setHover] = useState<{ pos: WellPosition; x: number; y: number; flip: boolean } | null>(null);
  const [keyboard, setKeyboard] = useState(false);
  const anchor = useRef<WellPosition | null>(null);
  const live = useRef<HTMLParagraphElement>(null);
  const summaryId = useId();

  const selectable = Boolean(onSelectedChange);
  const at = useCallback((p: WellPosition) => grid.get(`${p.row}:${p.column}`) ?? null, [grid]);
  const pickable = useCallback((p: WellPosition) => {
    const w = at(p);
    return w != null && !w.dimmed;
  }, [at]);

  const cellMin = columns > 12 ? 22 : 30;
  const cellMax = columns > 12 ? 40 : 56;
  const template = `${ROW_HEAD} repeat(${columns}, minmax(${cellMin}px, 1fr))`;
  const style: CSSProperties = { gridTemplateColumns: template };

  const select = useCallback(
    (labels: string[]) => {
      if (!onSelectedChange) return;
      const keep = labels.filter((l) => {
        const p = parseWell(l);
        return p != null && pickable(p);
      });
      onSelectedChange(multiple ? keep : keep.slice(-1));
    },
    [onSelectedChange, pickable, multiple],
  );

  const place = useCallback(
    (cell: HTMLElement, pos: WellPosition) => {
      const wrap = wrapRef.current;
      if (!wrap) return;
      const a = cell.getBoundingClientRect();
      const b = wrap.getBoundingClientRect();
      const x = a.left - b.left + a.width / 2;
      const y = a.bottom - b.top + 6;
      setHover({ pos, x, y, flip: x > b.width - 240 });
    },
    [],
  );

  const focusCell = useCallback((p: WellPosition) => {
    setCursor(p);
    const el = gridRef.current?.querySelector<HTMLElement>(`[data-pos="${p.row}:${p.column}"]`);
    if (el) {
      el.focus({ preventScroll: false });
      place(el, p);
    }
  }, [place]);

  const announce = (text: string) => {
    if (live.current) live.current.textContent = text;
  };

  const posOf = (target: EventTarget | null): { el: HTMLElement; pos: WellPosition } | null => {
    const el = (target as HTMLElement | null)?.closest?.<HTMLElement>("[data-pos]");
    if (!el) return null;
    const [r, c] = (el.dataset.pos ?? "").split(":").map(Number);
    return { el, pos: { row: r!, column: c! } };
  };

  const onClick = (e: MouseEvent) => {
    const hit = posOf(e.target);
    if (!hit) return;
    setKeyboard(false);
    const label = wellLabel(hit.pos.row, hit.pos.column);
    if (!selectable || !pickable(hit.pos)) return;
    if (e.shiftKey && anchor.current && multiple) {
      select(rectangle(anchor.current, hit.pos));
    } else if ((e.metaKey || e.ctrlKey) && multiple) {
      const next = new Set(selected);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      select([...next]);
      anchor.current = hit.pos;
    } else {
      select([label]);
      anchor.current = hit.pos;
    }
  };

  const onDoubleClick = (e: MouseEvent) => {
    const hit = posOf(e.target);
    if (hit && pickable(hit.pos)) onActivate?.(wellLabel(hit.pos.row, hit.pos.column));
  };

  const onKeyDown = (e: KeyboardEvent) => {
    const mod = e.metaKey || e.ctrlKey;
    let next: WellPosition | null = null;
    const { row, column } = cursor;
    switch (e.key) {
      case "ArrowUp":
        next = { row: Math.max(0, row - 1), column };
        break;
      case "ArrowDown":
        next = { row: Math.min(rows - 1, row + 1), column };
        break;
      case "ArrowLeft":
        next = { row, column: Math.max(0, column - 1) };
        break;
      case "ArrowRight":
        next = { row, column: Math.min(columns - 1, column + 1) };
        break;
      case "Home":
        next = mod ? { row: 0, column: 0 } : { row, column: 0 };
        break;
      case "End":
        next = mod ? { row: rows - 1, column: columns - 1 } : { row, column: columns - 1 };
        break;
      case "PageUp":
        next = { row: 0, column };
        break;
      case "PageDown":
        next = { row: rows - 1, column };
        break;
      case " ":
      case "Spacebar": {
        e.preventDefault();
        if (!selectable || !pickable(cursor)) return;
        const l = wellLabel(row, column);
        const set = new Set(multiple ? selected : []);
        if (set.has(l)) set.delete(l);
        else set.add(l);
        select([...set]);
        anchor.current = cursor;
        announce(set.has(l) ? `${l} selected; ${set.size} selected` : `${l} not selected; ${set.size} selected`);
        return;
      }
      case "Enter": {
        e.preventDefault();
        if (!pickable(cursor)) return;
        const l = wellLabel(row, column);
        if (selectable) select([l]);
        anchor.current = cursor;
        onActivate?.(l);
        return;
      }
      case "Escape":
        if (selectable && selected.size) {
          e.preventDefault();
          select([]);
          announce("Selection cleared");
        }
        setHover(null);
        return;
      case "a":
      case "A":
        if (mod && selectable && multiple) {
          e.preventDefault();
          const all = [...grid.values()].filter((w) => !w.dimmed).map((w) => w.well);
          select(all);
          announce(`${all.length} wells selected`);
        }
        return;
      default:
        return;
    }
    e.preventDefault();
    setKeyboard(true);
    if (e.shiftKey && selectable && multiple) {
      anchor.current ??= cursor;
      select(rectangle(anchor.current, next));
    }
    focusCell(next);
  };

  const onFocus = (e: FocusEvent) => {
    const hit = posOf(e.target);
    if (!hit) return;
    setCursor(hit.pos);
    if (keyboard || e.target.matches(":focus-visible")) place(hit.el, hit.pos);
  };

  const onMouseOver = (e: MouseEvent) => {
    const hit = posOf(e.target);
    if (!hit) return;
    if (hover && hover.pos.row === hit.pos.row && hover.pos.column === hit.pos.column) return;
    place(hit.el, hit.pos);
  };

  const selectLine = (labels: string[], additive: boolean) => {
    if (!selectable || !multiple) return;
    select(additive ? [...new Set([...selected, ...labels])] : labels);
  };

  const hoverWell = hover ? at(hover.pos) : null;
  const hoverLabel = hover ? wellLabel(hover.pos.row, hover.pos.column) : "";

  return (
    <div ref={wrapRef} className="relative">
      <div className="-mx-1 overflow-x-auto px-1 pb-1">
        <div
          ref={gridRef}
          role="grid"
          aria-label={label}
          aria-describedby={summaryId}
          aria-multiselectable={selectable && multiple ? true : undefined}
          aria-rowcount={rows + 1}
          aria-colcount={columns + 1}
          className="select-none"
          style={{ minWidth: `calc(${ROW_HEAD} + ${columns * cellMin}px)`, maxWidth: `calc(${ROW_HEAD} + ${columns * cellMax}px)` }}
          onClick={onClick}
          onDoubleClick={onDoubleClick}
          onKeyDown={onKeyDown}
          onFocus={onFocus}
          onMouseOver={onMouseOver}
          onMouseLeave={() => setHover(null)}
          onBlur={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setHover(null);
          }}
        >
          <div role="row" aria-rowindex={1} className="grid" style={style}>
            <div role="columnheader" aria-colindex={1} className="sr-only">
              Row
            </div>
            {Array.from({ length: columns }, (_, c) => (
              <div
                key={c}
                role="columnheader"
                aria-colindex={c + 2}
                title={selectable && multiple ? `Select column ${c + 1}` : undefined}
                onClick={(e) =>
                  selectLine(
                    Array.from({ length: rows }, (_, r) => wellLabel(r, c)),
                    e.metaKey || e.ctrlKey || e.shiftKey,
                  )
                }
                className={cn(
                  "pb-0.5 text-center font-mono text-[10px] leading-4 text-faint tabular",
                  selectable && multiple && "cursor-pointer hover:text-fg",
                )}
              >
                {c + 1}
              </div>
            ))}
          </div>
          {Array.from({ length: rows }, (_, r) => (
            <div key={r} role="row" aria-rowindex={r + 2} className="grid" style={style}>
              <div
                role="rowheader"
                aria-colindex={1}
                title={selectable && multiple ? `Select row ${rowLetters(r)}` : undefined}
                onClick={(e) =>
                  selectLine(
                    Array.from({ length: columns }, (_, c) => wellLabel(r, c)),
                    e.metaKey || e.ctrlKey || e.shiftKey,
                  )
                }
                className={cn(
                  "flex items-center justify-center font-mono text-[10px] text-faint",
                  selectable && multiple && "cursor-pointer hover:text-fg",
                )}
              >
                {rowLetters(r)}
              </div>
              {Array.from({ length: columns }, (_, c) => {
                const w = grid.get(`${r}:${c}`) ?? null;
                const l = wellLabel(r, c);
                return (
                  <Cell
                    key={c}
                    row={r}
                    column={c}
                    well={w}
                    wellLabel={l}
                    layer={layer}
                    domain={domain}
                    selected={selected.has(l)}
                    focusable={cursor.row === r && cursor.column === c}
                    selectable={selectable}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>
      {hover ? (
        <HoverCard
          well={hoverWell}
          label={hoverLabel}
          layer={layer}
          x={hover.x}
          y={hover.y}
          flip={hover.flip}
          extra={hoverWell && renderDetails ? renderDetails(hoverWell) : null}
        />
      ) : null}
      <p ref={live} className="sr-only" aria-live="polite" />
      <p id={summaryId} className="sr-only">
        {summary}
      </p>
    </div>
  );
}

function firstWell(grid: Map<string, Located>): WellPosition | null {
  let best: Located | null = null;
  for (const w of grid.values()) {
    if (w.dimmed) continue;
    if (!best || w.row < best.row || (w.row === best.row && w.column < best.column)) best = w;
  }
  return best ? { row: best.row, column: best.column } : null;
}

const Cell = memo(function Cell({
  row,
  column,
  well,
  wellLabel: label,
  layer,
  domain,
  selected,
  focusable,
  selectable,
}: {
  row: number;
  column: number;
  well: PlateWell | null;
  wellLabel: string;
  layer: PlateLayer;
  domain: Domain | null;
  selected: boolean;
  focusable: boolean;
  selectable: boolean;
}) {
  return (
    <div
      role="gridcell"
      aria-colindex={column + 2}
      aria-label={well ? wellSummary(well, layer) : `${label}, empty`}
      aria-selected={selectable && well ? selected : undefined}
      aria-disabled={well?.dimmed || !well ? true : undefined}
      tabIndex={focusable ? 0 : -1}
      data-pos={`${row}:${column}`}
      className={cn(
        "relative m-px aspect-square rounded-md p-[6%] transition-[background-color,box-shadow,opacity] duration-150 ease-out outline-none focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus",
        well && !well.dimmed && selectable && "cursor-pointer hover:bg-bg-subtle",
        well?.dimmed && "opacity-20",
        selected && well && "bg-accent-soft shadow-[inset_0_0_0_2px_var(--accent-strong)] hover:bg-accent-soft",
      )}
    >
      <WellGlyph well={well} layer={layer} domain={domain} />
    </div>
  );
});

// ---------------------------------------------------------------------------------------------
// Hover card

function HoverCard({
  well,
  label,
  layer,
  x,
  y,
  flip,
  extra,
}: {
  well: PlateWell | null;
  label: string;
  layer: PlateLayer;
  x: number;
  y: number;
  flip: boolean;
  extra: ReactNode;
}) {
  const rows: [string, ReactNode][] = [];
  if (well) {
    if (well.sample) rows.push(["Sample", well.sample]);
    if (well.target) rows.push(["Target", well.target]);
    rows.push(["Type", roleStyle(well.role).label]);
    if (well.amplified !== undefined) rows.push(["Call", CALL_STYLE[callKey(well.amplified)].label]);
    if (well.cq !== undefined) rows.push(["Cq", numberText("cq", well.cq)]);
    if (well.efficiency !== undefined) rows.push(["Efficiency", numberText("efficiency", well.efficiency)]);
    if (well.r2 !== undefined) rows.push(["R²", numberText("r2", well.r2)]);
  }
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute z-20 w-max max-w-[260px] rounded-lg border border-line bg-surface px-3 py-2 text-[12px] text-fg shadow-md"
      style={{ left: x, top: y, transform: flip ? "translateX(-100%) translateX(12px)" : "translateX(-12px)" }}
    >
      <div className="mb-1 flex items-baseline gap-2">
        <span className="font-mono text-[13px] font-semibold">{label}</span>
        {well ? (
          <span className="text-muted">{PLATE_LAYER_LABEL[layer]}</span>
        ) : (
          <span className="text-muted">empty position</span>
        )}
      </div>
      {well ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
          {rows.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted">{k}</dt>
              <dd className="m-0 truncate font-mono tabular">{v}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {well?.disagree ? <p className="mt-1.5 text-[12px] text-fg">The Curve Judge reads this curve differently.</p> : null}
      {well?.personCall ? <p className="mt-1 text-[12px] text-muted">A person set this well’s call.</p> : null}
      {well?.flagged ? (
        <p className="mt-1 text-[12px] text-danger">Its names read like instructions; qPilot never acts on them.</p>
      ) : null}
      {well?.notes?.map((n, i) => (
        <p key={i} className="mt-1 text-[12px] text-muted">
          {n}
        </p>
      ))}
      {extra}
      {well?.dimmed ? <p className="mt-1 text-[12px] text-faint">Filtered out.</p> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Table view

function WellTable({
  wells,
  label,
  selected,
  onPick,
}: {
  wells: PlateWell[];
  label: string;
  selected: ReadonlySet<string>;
  onPick?: (well: string) => void;
}) {
  const rows = useMemo(() => [...wells].sort((a, b) => compareWells(a.well, b.well)), [wells]);
  const has = (k: keyof PlateWell) => wells.some((w) => w[k] !== undefined);
  return (
    <div className="max-h-[480px] overflow-auto rounded-lg border border-line">
      <Table caption={`${label}: every well`}>
        <THead>
          <TR>
            <TH>Well</TH>
            <TH>Sample</TH>
            <TH>Target</TH>
            <TH>Type</TH>
            {has("amplified") ? <TH>Call</TH> : null}
            {has("cq") ? <TH numeric>Cq</TH> : null}
            {has("efficiency") ? <TH numeric>Efficiency</TH> : null}
            {has("r2") ? <TH numeric>R²</TH> : null}
            {has("disagree") ? <TH>Curve Judge</TH> : null}
          </TR>
        </THead>
        <TBody>
          {rows.map((w) => (
            <TR
              key={w.well}
              aria-selected={selected.has(w.well) || undefined}
              className={cn(selected.has(w.well) && "bg-accent-soft", w.dimmed && "opacity-50")}
            >
              <TD>
                {onPick && !w.dimmed ? (
                  <button
                    type="button"
                    onClick={() => onPick(w.well)}
                    className="font-mono text-accent underline-offset-2 hover:underline"
                  >
                    {w.well}
                  </button>
                ) : (
                  <span className="font-mono">{w.well}</span>
                )}
              </TD>
              <TD>{w.sample ?? "—"}</TD>
              <TD>{w.target ?? "—"}</TD>
              <TD title={roleWords(w.role)}>{roleStyle(w.role).label}</TD>
              {has("amplified") ? <TD>{CALL_STYLE[callKey(w.amplified)].label}</TD> : null}
              {has("cq") ? (
                <TD numeric>
                  <NumberCell>{numberText("cq", w.cq)}</NumberCell>
                </TD>
              ) : null}
              {has("efficiency") ? (
                <TD numeric>
                  <NumberCell>{numberText("efficiency", w.efficiency)}</NumberCell>
                </TD>
              ) : null}
              {has("r2") ? (
                <TD numeric>
                  <NumberCell>{w.r2 == null ? "—" : fixed(w.r2, 4)}</NumberCell>
                </TD>
              ) : null}
              {has("disagree") ? <TD>{w.disagree ? "disagrees" : ""}</TD> : null}
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}
