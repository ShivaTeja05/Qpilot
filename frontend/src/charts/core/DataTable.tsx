/** The "View as table" body: the chart's values as sortable rows (text only). */
import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { cn } from "@/lib/cn";

export interface Column<R> {
  key: string;
  header: string;
  cell: (row: R) => ReactNode;
  /** A sort key; columns without one are not sortable. */
  sort?: (row: R) => number | string | null | undefined;
  numeric?: boolean;
}

export function DataTable<R>({
  columns,
  rows,
  rowKey,
  onRowClick,
  caption,
}: {
  columns: Column<R>[];
  rows: readonly R[];
  rowKey: (row: R, i: number) => string;
  onRowClick?: (row: R) => void;
  caption?: string;
}) {
  const [sort, setSort] = useState<{ key: string; desc: boolean } | null>(null);
  const sorted = useMemo(() => {
    const col = sort && columns.find((c) => c.key === sort.key);
    if (!col?.sort) return rows;
    const get = col.sort;
    return [...rows].sort((a, b) => {
      const x = get(a);
      const y = get(b);
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      const c = x < y ? -1 : x > y ? 1 : 0;
      return sort!.desc ? -c : c;
    });
  }, [rows, columns, sort]);

  return (
    <table className="w-full border-collapse text-[13px]">
      {caption && <caption className="sr-only">{caption}</caption>}
      <thead className="sticky top-0 z-10 bg-surface-2">
        <tr>
          {columns.map((c) => {
            const on = sort?.key === c.key;
            return (
              <th
                key={c.key}
                scope="col"
                aria-sort={on ? (sort!.desc ? "descending" : "ascending") : undefined}
                className={cn(
                  "border-b border-line px-3 py-2 text-left text-[12px] font-medium whitespace-nowrap text-muted",
                  c.numeric && "text-right",
                )}
              >
                {c.sort ? (
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 hover:text-fg"
                    onClick={() => setSort(on ? { key: c.key, desc: !sort!.desc } : { key: c.key, desc: false })}
                  >
                    {c.header}
                    {on && (sort!.desc ? <ArrowDown size={12} aria-hidden /> : <ArrowUp size={12} aria-hidden />)}
                  </button>
                ) : (
                  c.header
                )}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {sorted.map((r, i) => (
          <tr
            key={rowKey(r, i)}
            className={cn("border-b border-line last:border-b-0", onRowClick && "cursor-pointer hover:bg-sunken")}
            onClick={onRowClick ? () => onRowClick(r) : undefined}
          >
            {columns.map((c, j) => {
              const content = c.cell(r);
              return (
                <td key={c.key} className={cn("px-3 py-1.5 align-top", c.numeric && "tabular text-right font-mono text-[12px]")}>
                  {j === 0 && onRowClick ? (
                    <button
                      type="button"
                      className="text-left font-medium text-fg underline-offset-2 hover:underline"
                      onClick={(e) => {
                        e.stopPropagation();
                        onRowClick(r);
                      }}
                    >
                      {content}
                    </button>
                  ) : (
                    content
                  )}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
