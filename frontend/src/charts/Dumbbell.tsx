/**
 * What-if: every gene's fold change under the planned analysis (hollow) and under the chosen
 * options (filled), joined by a line; genes whose call changes come first and say how.
 */
import { useMemo, type ReactNode } from "react";
import { ChartFrame, LineSwatch, type LegendItem } from "./core/ChartFrame";
import { DataTable, type Column } from "./core/DataTable";
import { FOLD_AXIS_BELOW, FoldAxis } from "./core/FoldAxis";
import { foldScale } from "./core/fold";
import { fmtFoldLog2 } from "./core/format";
import { GlyphMark } from "./core/Glyph";
import { useTip, usePointNav, useWidth } from "./core/hooks";
import { Tooltip } from "./core/Tooltip";
import { CALLS, type CallKey } from "./core/encodings";

export interface DumbbellRow {
  gene: string;
  baseLog2: number;
  newLog2: number;
  baseCall: CallKey;
  newCall: CallKey;
  headline?: boolean;
  baseText?: string;
  newText?: string;
}

export interface DumbbellProps {
  rows: DumbbellRow[];
  line: number;
  lineLabel?: string;
  lower?: string;
  higher?: string;
  summary: string;
  caption?: ReactNode;
  /** The words for the two ends ("Planned", "With your choices"). */
  fromLabel?: string;
  toLabel?: string;
  onSelect?: (gene: string) => void;
}

const TOP = 24;

/** Changed genes first, then headline genes, then by how far the fold moved. */
export function dumbbellOrder(rows: readonly DumbbellRow[]): DumbbellRow[] {
  return [...rows].sort(
    (a, b) =>
      Number(b.baseCall !== b.newCall) - Number(a.baseCall !== a.newCall) ||
      Number(Boolean(b.headline)) - Number(Boolean(a.headline)) ||
      Math.abs(b.newLog2 - b.baseLog2) - Math.abs(a.newLog2 - a.baseLog2) ||
      a.gene.localeCompare(b.gene),
  );
}

export function Dumbbell({
  rows,
  line,
  lineLabel,
  lower,
  higher,
  summary,
  caption,
  fromLabel = "Planned",
  toLabel = "With these choices",
  onSelect,
}: DumbbellProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTip();
  const narrow = width < 560;
  const labelW = narrow ? 78 : 150;
  const rowH = 22;
  const sorted = useMemo(() => dumbbellOrder(rows), [rows]);
  const fs = useMemo(
    () =>
      foldScale(
        rows.flatMap((r) => [r.baseLog2, r.newLog2]),
        line,
        labelW + 10,
        width - 12,
      ),
    [rows, line, labelW, width],
  );
  const bottom = TOP + rowH * sorted.length + 4;
  const height = bottom + FOLD_AXIS_BELOW + 2;
  const nav = usePointNav(sorted.length, (i) => onSelect?.(sorted[i]!.gene));
  const active = nav.active != null ? sorted[nav.active] : null;

  const tipFor = (r: DumbbellRow) => ({
    title: r.gene,
    value: `${r.baseText ?? fmtFoldLog2(r.baseLog2)} → ${r.newText ?? fmtFoldLog2(r.newLog2)}`,
    lines: [
      r.baseCall !== r.newCall
        ? `Call changes: ${CALLS[r.baseCall].short} → ${CALLS[r.newCall].short}`
        : `Call stays ${CALLS[r.baseCall].short}`,
      onSelect ? "Click to open the gene" : null,
    ],
  });

  const legend: LegendItem[] = [
    { mark: { shape: "diamond", tone: "var(--accent)" }, label: fromLabel },
    { mark: CALLS.up, label: `${toLabel}: up` },
    { mark: CALLS.down, label: "down" },
    { mark: CALLS.none, label: "no call" },
    ...(line ? [{ swatch: <LineSwatch dashed />, label: lineLabel ?? "Call line" }] : []),
  ];

  const columns: Column<DumbbellRow>[] = [
    { key: "gene", header: "Gene", cell: (r) => r.gene, sort: (r) => r.gene },
    {
      key: "base",
      header: fromLabel,
      cell: (r) => `${r.baseText ?? fmtFoldLog2(r.baseLog2)} · ${CALLS[r.baseCall].short}`,
      sort: (r) => r.baseLog2,
      numeric: true,
    },
    {
      key: "new",
      header: toLabel,
      cell: (r) => `${r.newText ?? fmtFoldLog2(r.newLog2)} · ${CALLS[r.newCall].short}`,
      sort: (r) => r.newLog2,
      numeric: true,
    },
    {
      key: "changed",
      header: "Call changes",
      cell: (r) => (r.baseCall !== r.newCall ? "yes" : "no"),
      sort: (r) => Number(r.baseCall !== r.newCall),
    },
  ];

  return (
    <ChartFrame
      summary={summary}
      legend={legend}
      caption={caption}
      live={
        active ? `${active.gene}: ${tipFor(active).value}. ${tipFor(active).lines[0]}.` : undefined
      }
      table={() => (
        <DataTable
          columns={columns}
          rows={sorted}
          rowKey={(r) => r.gene}
          onRowClick={onSelect ? (r) => onSelect(r.gene) : undefined}
          caption={summary}
        />
      )}
    >
      <div
        ref={ref}
        className="relative rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-focus"
        tabIndex={sorted.length ? 0 : -1}
        role="group"
        aria-label={`${summary} Use the arrow keys to move between genes${onSelect ? " and Enter to open one" : ""}.`}
        onKeyDown={nav.onKeyDown}
        onBlur={() => {
          nav.onBlur();
          hide();
        }}
      >
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={summary}
          className="block overflow-visible"
          onPointerLeave={hide}
        >
          <FoldAxis
            scale={fs}
            top={TOP}
            bottom={bottom}
            line={line}
            lineLabel={lineLabel}
            lower={lower}
            higher={higher}
          />
          {sorted.map((r, i) => {
            const y = TOP + i * rowH + rowH / 2;
            const x0 = fs.x(r.baseLog2);
            const x1 = fs.x(r.newLog2);
            const changed = r.baseCall !== r.newCall;
            const on = active === r;
            return (
              <g
                key={r.gene}
                className={onSelect ? "cursor-pointer" : undefined}
                onPointerEnter={() => show(Math.max(x0, x1), y, tipFor(r))}
                onClick={onSelect ? () => onSelect(r.gene) : undefined}
              >
                <rect
                  x={0}
                  y={y - rowH / 2}
                  width={width}
                  height={rowH}
                  fill={on ? "var(--accent-soft)" : changed ? "var(--warn-soft)" : "transparent"}
                  fillOpacity={on ? 0.7 : changed ? 0.45 : 0}
                />
                <text
                  x={labelW - 8}
                  y={y + 4}
                  textAnchor="end"
                  fontSize={12}
                  fontWeight={changed || r.headline ? 600 : 400}
                  fill={changed ? "var(--text)" : "var(--text-muted)"}
                >
                  {r.gene}
                </text>
                <line
                  x1={x0}
                  x2={x1}
                  y1={y}
                  y2={y}
                  stroke={changed ? "var(--text)" : "var(--line-strong)"}
                  strokeWidth={2}
                  strokeLinecap="round"
                />
                <GlyphMark mark={{ shape: "diamond", tone: "var(--accent)" }} x={x0} y={y} r={4} />
                <GlyphMark mark={CALLS[r.newCall]} x={x1} y={y} r={4.5} />
              </g>
            );
          })}
        </svg>
        <Tooltip
          tip={
            active
              ? {
                  x: Math.max(fs.x(active.baseLog2), fs.x(active.newLog2)),
                  y: TOP + nav.active! * rowH + rowH / 2,
                  content: tipFor(active),
                }
              : tip
          }
          width={width}
        />
      </div>
    </ChartFrame>
  );
}
