/**
 * The frame every science chart sits in: the legend, the "View as table" switch, the caption, and
 * the live region that reads out the mark the keyboard is on. The chart itself is the child.
 */
import { useId, useState, type ReactNode } from "react";
import { BarChart3, Table2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { Glyph } from "./Glyph";
import type { Mark } from "./encodings";

export interface LegendItem {
  mark?: Pick<Mark, "shape" | "tone">;
  /** A custom swatch (a line, a band) when the item is not a glyph. */
  swatch?: ReactNode;
  label: string;
  count?: number;
}

export function Legend({ items, className }: { items: LegendItem[]; className?: string }) {
  if (!items.length) return null;
  return (
    <ul className={cn("flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted", className)}>
      {items.map((it) => (
        <li key={it.label} className="inline-flex items-center gap-1.5">
          {it.mark ? <Glyph mark={it.mark} size={12} /> : it.swatch}
          <span>{it.label}</span>
          {it.count != null && <span className="tabular text-faint">{it.count}</span>}
        </li>
      ))}
    </ul>
  );
}

/** A line swatch for legends (call lines, group means). */
export function LineSwatch({ dashed, tone = "var(--text-faint)", width = 2 }: { dashed?: boolean; tone?: string; width?: number }) {
  return (
    <svg width="14" height="12" aria-hidden="true">
      <line x1="7" x2="7" y1="0" y2="12" stroke={tone} strokeWidth={width} strokeDasharray={dashed ? "3 2" : undefined} />
    </svg>
  );
}

export interface ChartFrameProps {
  /** One sentence that says what the chart shows, with its key numbers (the aria-label). */
  summary: string;
  legend?: LegendItem[];
  /** Controls in the frame's header row (a colour-by switch, a filter). */
  controls?: ReactNode;
  /** The table view: the same values as rows. */
  table: () => ReactNode;
  caption?: ReactNode;
  /** What the keyboard is on (announced politely). */
  live?: string;
  className?: string;
  children: ReactNode;
}

export function ChartFrame({ summary, legend, controls, table, caption, live, className, children }: ChartFrameProps) {
  const [asTable, setAsTable] = useState(false);
  const captionId = useId();
  return (
    <figure className={cn("m-0 min-w-0", className)} aria-label={summary} aria-describedby={caption ? captionId : undefined}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">{legend && !asTable && <Legend items={legend} />}</div>
        <div className="flex items-center gap-2">
          {controls}
          <button
            type="button"
            onClick={() => setAsTable((v) => !v)}
            aria-pressed={asTable}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-line bg-surface px-2 text-[12px] text-muted hover:border-line-strong hover:text-fg"
          >
            {asTable ? <BarChart3 size={14} aria-hidden /> : <Table2 size={14} aria-hidden />}
            {asTable ? "View as chart" : "View as table"}
          </button>
        </div>
      </div>
      {asTable ? (
        <div className="max-h-[480px] overflow-auto rounded-lg border border-line">{table()}</div>
      ) : (
        children
      )}
      {caption && (
        <figcaption id={captionId} className="mt-2 text-[12px] leading-relaxed text-muted">
          {caption}
        </figcaption>
      )}
      <p className="sr-only" aria-live="polite">
        {live ?? ""}
      </p>
    </figure>
  );
}
