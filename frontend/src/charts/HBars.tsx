/**
 * Horizontal bars with the value at the tip and an optional reference line: calls changed by one
 * choice alone, share of the spread, geNorm M and V. Bars are ≤ 16 px thick with a rounded data end.
 */
import { scaleLinear } from "d3-scale";
import type { ReactNode } from "react";
import { ChartFrame, LineSwatch, type LegendItem } from "./core/ChartFrame";
import { DataTable, type Column } from "./core/DataTable";
import { useTip, usePointNav, useWidth } from "./core/hooks";
import { Tooltip } from "./core/Tooltip";

export interface BarRow {
  key: string;
  label: string;
  value: number;
  /** The value as written at the bar's tip ("31 genes", "48 %", "1.64"). */
  valueText: string;
  /** A short note after the value ("differs between groups"). */
  note?: string;
  /** A CSS colour token for the bar (default the accent). */
  tone?: string;
  /** Bold label (the rows that matter). */
  strong?: boolean;
}

export interface HBarsProps {
  rows: BarRow[];
  summary: string;
  caption?: ReactNode;
  /** The axis maximum (default: the largest value or the reference line). */
  max?: number;
  ref_?: { value: number; label: string } | null;
  legend?: LegendItem[];
  valueHeader?: string;
  onSelect?: (key: string) => void;
}

/** A bar's path: square at the baseline, 4 px rounded data end. */
export function barPath(x0: number, x1: number, y: number, h: number): string {
  const w = x1 - x0;
  if (w <= 0) return "";
  const r = Math.min(4, w, h / 2);
  return `M${x0} ${y} H${x1 - r} Q${x1} ${y} ${x1} ${y + r} V${y + h - r} Q${x1} ${y + h} ${x1 - r} ${y + h} H${x0} Z`;
}

export function HBars({ rows, summary, caption, max, ref_, legend, valueHeader = "Value", onSelect }: HBarsProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTip();
  const narrow = width < 520;
  const labelW = narrow ? 0 : Math.min(240, Math.round(width * 0.38));
  const rowH = narrow ? 40 : 30;
  const top = ref_ ? 22 : 4;
  const height = top + rows.length * rowH + 4;
  const textRoom = narrow ? 64 : 150;
  const vmax = Math.max(max ?? 0, ref_?.value ?? 0, ...rows.map((r) => r.value), 1e-9);
  const x = scaleLinear().domain([0, vmax]).range([labelW, Math.max(labelW + 40, width - textRoom)]);
  const nav = usePointNav(rows.length, (i) => onSelect?.(rows[i]!.key));
  const active = nav.active != null ? rows[nav.active] : null;
  const bh = 14;

  const columns: Column<BarRow>[] = [
    { key: "label", header: "", cell: (r) => r.label, sort: (r) => r.label },
    { key: "value", header: valueHeader, cell: (r) => r.valueText, sort: (r) => r.value, numeric: true },
    { key: "note", header: "Note", cell: (r) => r.note ?? "" },
  ];

  return (
    <ChartFrame
      summary={summary}
      legend={legend ?? (ref_ ? [{ swatch: <LineSwatch dashed />, label: ref_.label }] : undefined)}
      caption={caption}
      live={active ? `${active.label}: ${active.valueText}${active.note ? `, ${active.note}` : ""}` : undefined}
      table={() => <DataTable columns={columns} rows={rows} rowKey={(r) => r.key} onRowClick={onSelect ? (r) => onSelect(r.key) : undefined} caption={summary} />}
    >
      <div
        ref={ref}
        className="relative rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-focus"
        tabIndex={rows.length ? 0 : -1}
        role="group"
        aria-label={`${summary} Use the arrow keys to read the bars.`}
        onKeyDown={nav.onKeyDown}
        onBlur={() => {
          nav.onBlur();
          hide();
        }}
      >
        <svg width={width} height={height} role="img" aria-label={summary} className="block overflow-visible" onPointerLeave={hide}>
          {ref_ && (
            <g aria-hidden="true">
              <line x1={x(ref_.value)} x2={x(ref_.value)} y1={top - 4} y2={height} stroke="var(--text-faint)" strokeWidth={1.25} strokeDasharray="4 3" />
              <text x={x(ref_.value)} y={top - 8} textAnchor="middle" fontSize={11} fill="var(--text-muted)">
                {ref_.label}
              </text>
            </g>
          )}
          {rows.map((r, i) => {
            const y = top + i * rowH;
            const by = narrow ? y + 20 : y + (rowH - bh) / 2;
            const x1 = x(r.value);
            const on = active === r;
            return (
              <g
                key={r.key}
                onPointerEnter={() => show(Math.max(x1, labelW + 8), by + bh / 2, { title: r.label, value: r.valueText, lines: [r.note] })}
                onClick={onSelect ? () => onSelect(r.key) : undefined}
                className={onSelect ? "cursor-pointer" : undefined}
              >
                <rect x={0} y={y} width={width} height={rowH} fill={on ? "var(--accent-soft)" : "transparent"} fillOpacity={0.6} />
                {narrow ? (
                  <text x={0} y={y + 14} fontSize={12} fill="var(--text)" fontWeight={r.strong ? 600 : 400}>
                    {r.label}
                  </text>
                ) : (
                  <text x={labelW - 10} y={by + 11} textAnchor="end" fontSize={12} fill="var(--text)" fontWeight={r.strong ? 600 : 400}>
                    {r.label}
                  </text>
                )}
                <rect x={labelW} y={by} width={Math.max(0, x(vmax) - labelW)} height={bh} rx={2} fill="var(--surface-sunken)" />
                {r.value > 0 && <path d={barPath(labelW, Math.max(labelW + 2, x1), by, bh)} fill={r.tone ?? "var(--accent)"} />}
                <text x={Math.max(x1, labelW) + 6} y={by + 11} fontSize={12} fill="var(--text)" className="tabular">
                  {r.valueText}
                  {r.note && !narrow && <tspan fill="var(--text-muted)"> · {r.note}</tspan>}
                </text>
              </g>
            );
          })}
        </svg>
        <Tooltip tip={tip} width={width} />
      </div>
    </ChartFrame>
  );
}
