/**
 * Table primitives (semantic <table>, dense, tabular numbers) and a virtualised, sortable
 * DataTable on TanStack Table + Virtual for long lists (all genes, wells, the chain).
 */
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type FilterFn,
  type Row,
  type SortingState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import {
  useMemo,
  useRef,
  useState,
  type HTMLAttributes,
  type ReactNode,
  type TdHTMLAttributes,
  type ThHTMLAttributes,
} from "react";
import { cn } from "@/lib/cn";

// ---------------------------------------------------------------------------------------------
// Primitives

/** A table in a scrollable box; `caption` names it for screen readers. */
export function Table({
  className,
  children,
  caption,
  ...rest
}: HTMLAttributes<HTMLTableElement> & { caption?: string }) {
  return (
    <table className={cn("w-full border-collapse text-[13px]", className)} {...rest}>
      {caption ? <caption className="sr-only">{caption}</caption> : null}
      {children}
    </table>
  );
}

export function THead({ className, ...rest }: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn("sticky top-0 z-10 bg-surface-2", className)} {...rest} />;
}

export function TBody(props: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody {...props} />;
}

export function TR({ className, ...rest }: HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("border-b border-line last:border-b-0", className)} {...rest} />;
}

/** A header cell; `numeric` right-aligns it. */
export function TH({
  className,
  numeric,
  ...rest
}: ThHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }) {
  return (
    <th
      scope="col"
      className={cn(
        "h-8 border-b border-line px-3 text-left align-middle text-xs font-medium whitespace-nowrap text-muted",
        numeric && "text-right",
        className,
      )}
      {...rest}
    />
  );
}

/** A body cell; `numeric` right-aligns it in mono tabular figures. */
export function TD({
  className,
  numeric,
  ...rest
}: TdHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }) {
  return (
    <td
      className={cn(
        "h-9 px-3 align-middle text-fg",
        numeric && "text-right font-mono text-[12.5px] tabular whitespace-nowrap",
        className,
      )}
      {...rest}
    />
  );
}

/** A number cell's content: mono, tabular, right-aligned; `muted` for secondary values. */
export function NumberCell({
  children,
  muted,
  className,
}: {
  children: ReactNode;
  muted?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "font-mono text-[12.5px] tabular whitespace-nowrap",
        muted ? "text-muted" : "text-fg",
        className,
      )}
    >
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------------------------
// DataTable

/** Per-column extras, set as `meta` on a column def. */
export interface ColumnMeta {
  /** Right-align and use tabular mono figures. */
  numeric?: boolean;
  /** CSS width of the column (e.g. "8rem", "20%"). */
  width?: string;
  /** Extra classes for this column's cells. */
  className?: string;
}

export interface DataTableProps<T> {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  /** A stable id per row (gene name, well key …). */
  getRowId: (row: T, index: number) => string;
  /** Accessible name of the table. */
  label: string;
  /** Height of the scroll box in px (rows beyond it are virtualised). Default 480. */
  height?: number;
  /** Row height in px. Default 36. */
  rowHeight?: number;
  /** Initial sort, e.g. `[{ id: "p", desc: false }]`. */
  initialSorting?: SortingState;
  /** Free-text filter over every column's value. */
  globalFilter?: string;
  /** A custom filter (keeps rows for which it returns true). */
  rowFilter?: (row: T) => boolean;
  /** Clicking (or Enter on) a row. */
  onRowClick?: (row: T) => void;
  /** The id of the highlighted row. */
  selectedId?: string | null;
  /** Shown when there are no rows (say what to do). */
  empty?: ReactNode;
  className?: string;
}

const includesText: FilterFn<unknown> = (row, columnId, value: string) => {
  const v = row.getValue(columnId);
  return v != null && String(v).toLowerCase().includes(value.toLowerCase());
};

/** A sortable, filterable, virtualised table (tens of thousands of rows stay smooth). */
export function DataTable<T>({
  data,
  columns,
  getRowId,
  label,
  height = 480,
  rowHeight = 36,
  initialSorting = [],
  globalFilter,
  rowFilter,
  onRowClick,
  selectedId,
  empty,
  className,
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>(initialSorting);
  // The rows must keep their identity between renders: a new array makes TanStack reset the
  // page index, which re-renders, which makes a new array… (a render loop that pegged a core).
  const rows = useMemo(() => (rowFilter ? data.filter(rowFilter) : data), [data, rowFilter]);
  // TanStack Table returns functions that cannot be memoised; the compiler lint is told so.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: rows,
    columns,
    getRowId: (r, i) => getRowId(r, i),
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    globalFilterFn: includesText as FilterFn<T>,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    // There is no pagination: never reset state when the data changes.
    autoResetPageIndex: false,
    autoResetExpanded: false,
  });
  const model = table.getRowModel().rows;
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: model.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 12,
  });
  const items = virtualizer.getVirtualItems();
  const top = items[0]?.start ?? 0;
  const bottom = virtualizer.getTotalSize() - (items[items.length - 1]?.end ?? 0);
  const nCols = table.getVisibleLeafColumns().length;

  const activate = (row: Row<T>) => onRowClick?.(row.original);

  // Roving focus: one row is the Tab stop; arrows, Home/End and PageUp/PageDown move it.
  const [cursor, setCursor] = useState(0);
  const active = Math.min(cursor, Math.max(0, model.length - 1));
  const moveTo = (index: number) => {
    const next = Math.max(0, Math.min(model.length - 1, index));
    setCursor(next);
    virtualizer.scrollToIndex(next, { align: "auto" });
    requestAnimationFrame(() =>
      scrollRef.current?.querySelector<HTMLElement>(`tr[data-index="${next}"]`)?.focus(),
    );
  };
  const page = Math.max(1, Math.floor(height / rowHeight) - 1);
  const onRowKey = (e: React.KeyboardEvent, index: number, row: Row<T>) => {
    const step: Record<string, number> = {
      ArrowDown: index + 1,
      ArrowUp: index - 1,
      PageDown: index + page,
      PageUp: index - page,
      Home: 0,
      End: model.length - 1,
    };
    if (e.key in step) {
      e.preventDefault();
      moveTo(step[e.key]!);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      activate(row);
    }
  };

  return (
    <div
      ref={scrollRef}
      className={cn(
        "qp-scroll relative overflow-auto rounded-xl border border-line bg-surface",
        className,
      )}
      style={{ maxHeight: height }}
      // Without row actions the scroller itself takes focus, so the keyboard can scroll it.
      tabIndex={onRowClick ? -1 : 0}
      role={onRowClick ? undefined : "region"}
      aria-label={onRowClick ? undefined : label}
    >
      <Table caption={label} aria-rowcount={model.length + 1} className="table-fixed">
        <colgroup>
          {table.getVisibleLeafColumns().map((c) => (
            <col
              key={c.id}
              style={{ width: (c.columnDef.meta as ColumnMeta | undefined)?.width }}
            />
          ))}
        </colgroup>
        <THead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => {
                const meta = h.column.columnDef.meta as ColumnMeta | undefined;
                const sorted = h.column.getIsSorted();
                const canSort = h.column.getCanSort();
                return (
                  <TH
                    key={h.id}
                    numeric={meta?.numeric}
                    aria-sort={
                      sorted === "asc"
                        ? "ascending"
                        : sorted === "desc"
                          ? "descending"
                          : canSort
                            ? "none"
                            : undefined
                    }
                  >
                    {h.isPlaceholder ? null : canSort ? (
                      <button
                        type="button"
                        onClick={h.column.getToggleSortingHandler()}
                        className={cn(
                          "inline-flex items-center gap-1 rounded hover:text-fg",
                          meta?.numeric && "flex-row-reverse",
                          sorted && "text-fg",
                        )}
                      >
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {sorted === "asc" ? (
                          <ArrowUp className="size-3" aria-hidden />
                        ) : sorted === "desc" ? (
                          <ArrowDown className="size-3" aria-hidden />
                        ) : (
                          <ChevronsUpDown className="size-3 opacity-40" aria-hidden />
                        )}
                      </button>
                    ) : (
                      flexRender(h.column.columnDef.header, h.getContext())
                    )}
                  </TH>
                );
              })}
            </tr>
          ))}
        </THead>
        <TBody>
          {model.length === 0 ? (
            <tr>
              <td colSpan={nCols} className="p-6 text-center text-[13px] text-muted">
                {empty ?? "Nothing matches."}
              </td>
            </tr>
          ) : null}
          {top > 0 ? (
            <tr aria-hidden>
              <td colSpan={nCols} style={{ height: top, padding: 0 }} />
            </tr>
          ) : null}
          {items.map((v) => {
            const row = model[v.index]!;
            const selected = selectedId != null && row.id === selectedId;
            return (
              <tr
                key={row.id}
                data-index={v.index}
                aria-rowindex={v.index + 2}
                aria-selected={onRowClick ? selected : undefined}
                tabIndex={onRowClick ? (v.index === active ? 0 : -1) : undefined}
                onClick={
                  onRowClick
                    ? () => {
                        setCursor(v.index);
                        activate(row);
                      }
                    : undefined
                }
                onFocus={onRowClick ? () => setCursor(v.index) : undefined}
                onKeyDown={onRowClick ? (e) => onRowKey(e, v.index, row) : undefined}
                style={{ height: rowHeight }}
                className={cn(
                  "border-b border-line last:border-b-0",
                  onRowClick &&
                    "cursor-pointer hover:bg-surface-2 focus-visible:bg-surface-2 focus-visible:outline-offset-[-2px]",
                  selected && "bg-accent-soft/60 hover:bg-accent-soft/60",
                )}
              >
                {row.getVisibleCells().map((cell) => {
                  const meta = cell.column.columnDef.meta as ColumnMeta | undefined;
                  const value = cell.getValue();
                  return (
                    <TD
                      key={cell.id}
                      numeric={meta?.numeric}
                      className={cn("truncate", meta?.className)}
                      // The full text of a cell the column cuts short.
                      title={typeof value === "string" ? value : undefined}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TD>
                  );
                })}
              </tr>
            );
          })}
          {bottom > 0 ? (
            <tr aria-hidden>
              <td colSpan={nCols} style={{ height: bottom, padding: 0 }} />
            </tr>
          ) : null}
        </TBody>
      </Table>
    </div>
  );
}

export type { ColumnDef, SortingState };
