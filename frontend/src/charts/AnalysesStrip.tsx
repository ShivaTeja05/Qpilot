/**
 * Every reasonable analysis of one gene as a dot on the fold axis, stacked where they pile up,
 * coloured and shaped by its call; the planned analysis is ringed.
 */
import { useMemo, type ReactNode } from "react";
import { ChartFrame, LineSwatch, type LegendItem } from "./core/ChartFrame";
import { DataTable, type Column } from "./core/DataTable";
import { FOLD_AXIS_BELOW, FoldAxis } from "./core/FoldAxis";
import { foldScale } from "./core/fold";
import { fmtFoldLog2 } from "./core/format";
import { GlyphMark } from "./core/Glyph";
import { useTip, usePointNav, useWidth } from "./core/hooks";
import { dotStack } from "./core/layout";
import { Tooltip } from "./core/Tooltip";
import { CALLS, CALL_ORDER, type CallKey } from "./core/encodings";

export interface AnalysisDot {
  log2: number;
  call: CallKey;
  /** Same call as the planned analysis. */
  same: boolean;
  planned: boolean;
  /** The choices that differ from the planned analysis (empty for the planned one). */
  choices: string[];
  /** The fold in the source's words ("3.38× higher"). */
  foldText?: string;
  /** The call in the source's words. */
  callText?: string;
}

export interface AnalysesStripProps {
  rows: AnalysisDot[];
  line: number;
  lineLabel?: string;
  lower?: string;
  higher?: string;
  summary: string;
  caption?: ReactNode;
}

const TOP = 26;
const MAX_STACK_PX = 190;

export function AnalysesStrip({ rows, line, lineLabel, lower, higher, summary, caption }: AnalysesStripProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTip();
  const fs = useMemo(() => foldScale(rows.map((d) => d.log2), line, 14, width - 14, 44, false), [rows, line, width]);

  const { placed, r, step } = useMemo(() => {
    // shrink the dots until the tallest pile fits, then squeeze if it still does not
    let r = width < 520 ? 4 : 4.5;
    let placed = dotStack(rows, (d) => fs.x(d.log2), r, (d) => CALL_ORDER.indexOf(d.call) * 2 + Number(d.planned));
    let tallest = Math.max(0, ...placed.map((p) => p.dy));
    while (tallest > MAX_STACK_PX && r > 2.5) {
      r -= 0.5;
      placed = dotStack(rows, (d) => fs.x(d.log2), r, (d) => CALL_ORDER.indexOf(d.call) * 2 + Number(d.planned));
      tallest = Math.max(0, ...placed.map((p) => p.dy));
    }
    const k = tallest > MAX_STACK_PX ? MAX_STACK_PX / tallest : 1;
    return { placed: placed.map((p) => ({ ...p, dy: p.dy * k })), r, step: 2 * r + 1.5 };
  }, [rows, fs, width]);

  const stackH = Math.max(4 * step, ...placed.map((p) => p.dy + step));
  const bottom = TOP + stackH + 8;
  const height = bottom + FOLD_AXIS_BELOW + 2;
  const order = useMemo(() => [...placed].sort((a, b) => a.x - b.x || a.dy - b.dy), [placed]);
  const nav = usePointNav(order.length);
  const active = nav.active != null ? order[nav.active] : null;
  const cy = (dy: number) => bottom - r - 3 - dy;

  const tipFor = (d: AnalysisDot) => ({
    title: d.planned ? "Your planned analysis" : d.choices.join(" + "),
    value: d.foldText ?? fmtFoldLog2(d.log2),
    lines: [d.callText ?? CALLS[d.call].label, d.planned ? null : d.same ? "Same call as planned" : "A different call from planned"],
  });

  const counts = CALL_ORDER.map((c) => ({ c, n: rows.filter((d) => d.call === c).length })).filter((x) => x.n);
  const legend: LegendItem[] = [
    ...counts.map(({ c, n }) => ({ mark: CALLS[c], label: CALLS[c].label, count: n })),
    {
      swatch: (
        <svg width="14" height="14" aria-hidden="true">
          <circle cx="7" cy="7" r="5.5" fill="none" stroke="var(--accent)" strokeWidth="2" />
        </svg>
      ),
      label: "Your planned analysis",
    },
    ...(line ? [{ swatch: <LineSwatch dashed />, label: lineLabel ?? "Call line" }] : []),
  ];

  const columns: Column<AnalysisDot>[] = [
    { key: "choices", header: "Choices that differ from planned", cell: (d) => (d.planned ? "None (your planned analysis)" : d.choices.join(" + ")), sort: (d) => d.choices.join(" ") },
    { key: "fold", header: "Fold change", cell: (d) => d.foldText ?? fmtFoldLog2(d.log2), sort: (d) => d.log2, numeric: true },
    { key: "call", header: "Call", cell: (d) => d.callText ?? CALLS[d.call].label, sort: (d) => d.call },
    { key: "same", header: "Same as planned", cell: (d) => (d.same ? "yes" : "no"), sort: (d) => Number(d.same) },
  ];

  return (
    <ChartFrame
      summary={summary}
      legend={legend}
      caption={caption}
      live={active ? `${tipFor(active.item).title}: ${tipFor(active.item).value}, ${tipFor(active.item).lines[0]}` : undefined}
      table={() => <DataTable columns={columns} rows={rows} rowKey={(_d, i) => String(i)} caption={summary} />}
    >
      <div
        ref={ref}
        className="relative rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-focus"
        tabIndex={rows.length ? 0 : -1}
        role="group"
        aria-label={`${summary} Use the arrow keys to read the analyses one by one.`}
        onKeyDown={nav.onKeyDown}
        onBlur={() => {
          nav.onBlur();
          hide();
        }}
      >
        <svg width={width} height={height} role="img" aria-label={summary} className="block overflow-visible" onPointerLeave={hide}>
          <FoldAxis scale={fs} top={TOP} bottom={bottom} line={line} lineLabel={lineLabel} lower={lower} higher={higher} />
          {placed.map((p, i) => {
            const d = p.item;
            const y = cy(p.dy);
            const on = active === p;
            return (
              <g key={i} onPointerEnter={() => show(p.x, y, tipFor(d))}>
                <circle cx={p.x} cy={y} r={Math.max(6, r + 2)} fill="transparent" />
                <GlyphMark mark={CALLS[d.call]} x={p.x} y={y} r={on ? r + 1.5 : r} />
                {(d.planned || on) && <circle cx={p.x} cy={y} r={r + 3.5} fill="none" stroke="var(--accent)" strokeWidth={2} />}
              </g>
            );
          })}
        </svg>
        <Tooltip tip={active ? { x: active.x, y: cy(active.dy), content: tipFor(active.item) } : tip} width={width} />
      </div>
    </ChartFrame>
  );
}
