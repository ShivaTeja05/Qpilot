/**
 * The robustness map: every gene a point — across, its fold change (log2 axis in ×); up, the share
 * of reasonable analyses that give the same call. Colour and shape come from the caller's encoding
 * (conclusion, confidence level or audit verdict). Click or Enter opens the gene.
 */
import { scaleLinear } from "d3-scale";
import { useMemo, type ReactNode } from "react";
import { ChartFrame, type LegendItem } from "./core/ChartFrame";
import { DataTable, type Column } from "./core/DataTable";
import { FOLD_AXIS_BELOW, FoldAxis } from "./core/FoldAxis";
import { foldScale } from "./core/fold";
import { fmtFoldLog2, fmtShare } from "./core/format";
import { GlyphMark } from "./core/Glyph";
import { useTip, usePointNav, useWidth } from "./core/hooks";
import { placeLabels, type Box } from "./core/layout";
import { Tooltip } from "./core/Tooltip";
import type { Mark } from "./core/encodings";

export interface MapPoint {
  gene: string;
  /** Fold change, log2. */
  log2: number;
  /** Share (0–1) of reasonable analyses giving the same call. */
  holds: number;
  mark: Mark;
  /** Always labelled (the study's headline genes). */
  headline?: boolean;
  /** Fold in words when the source gives them ("3.32× higher"); else the × form. */
  foldText?: string;
  /** More tooltip lines (level, verdict, p). */
  details?: string[];
}

export interface RobustnessMapProps {
  points: MapPoint[];
  /** The call rule's minimum |log2 fold| (1 = at least 2-fold). */
  line: number;
  lineLabel?: string;
  lower?: string;
  higher?: string;
  legend: LegendItem[];
  summary: string;
  caption?: ReactNode;
  controls?: ReactNode;
  selected?: string | null;
  /** When set, other genes are drawn faint (a filter is on). */
  highlight?: ReadonlySet<string> | null;
  /** A horizontal reference share (e.g. the robustness check's), with its words. */
  holdsLine?: { share: number; label: string } | null;
  extraColumns?: Column<MapPoint>[];
  onSelect?: (gene: string) => void;
}

const M = { top: 40, right: 18, left: 46 };

export function RobustnessMap(props: RobustnessMapProps) {
  const { points, line, lineLabel, lower, higher, legend, summary, caption, controls, selected, highlight, holdsLine, extraColumns = [], onSelect } = props;
  const [ref, width] = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTip();
  const height = Math.round(Math.max(320, Math.min(480, width * 0.5)));
  const bottom = height - FOLD_AXIS_BELOW - 6;
  const r = width < 520 ? 4.5 : 5.5;

  const fs = useMemo(() => foldScale(points.map((p) => p.log2), line, M.left + 8, width - M.right), [points, line, width]);
  const yMin = useMemo(() => {
    const lowest = Math.min(1, ...points.map((p) => p.holds), holdsLine?.share ?? 1);
    return Math.max(0, Math.floor((lowest * 100 - 6) / 10) / 10);
  }, [points, holdsLine]);
  const y = useMemo(() => scaleLinear().domain([yMin, 1]).range([bottom, M.top]), [yMin, bottom]);
  const yTicks = useMemo(() => {
    const step = bottom - M.top < 220 ? 0.2 : 0.1;
    const out: number[] = [];
    for (let v = 1; v >= yMin - 1e-9; v -= step) out.push(Math.round(v * 100) / 100);
    return out;
  }, [yMin, bottom]);

  // reading order for the keyboard: left to right
  const order = useMemo(() => [...points].sort((a, b) => a.log2 - b.log2 || a.gene.localeCompare(b.gene)), [points]);
  const nav = usePointNav(order.length, (i) => onSelect?.(order[i]!.gene));
  const active = nav.active != null ? order[nav.active] : null;

  // draw the least robust last, so they sit on top
  const drawOrder = useMemo(() => [...points].sort((a, b) => b.holds - a.holds), [points]);
  const pos = (p: MapPoint) => ({ cx: fs.x(p.log2), cy: y(p.holds) });

  const labels = useMemo(() => {
    const obstacles: Box[] = points.map((p) => {
      const cx = fs.x(p.log2);
      const cy = y(p.holds);
      return { x0: cx - r - 1, x1: cx + r + 1, y0: cy - r - 1, y1: cy + r + 1 };
    });
    const want = points
      .filter((p) => p.gene === selected || p.headline || p.holds < 0.9)
      .sort(
        (a, b) =>
          Number(b.gene === selected) - Number(a.gene === selected) ||
          Number(Boolean(b.headline)) - Number(Boolean(a.headline)) ||
          a.holds - b.holds,
      )
      .map((p) => ({ item: p, x: fs.x(p.log2), y: y(p.holds), text: p.gene }));
    return placeLabels(want, obstacles, { x0: M.left, y0: M.top - 14, x1: width - 2, y1: bottom - 2 });
  }, [points, selected, width, bottom, r, fs, y]);

  const tipFor = (p: MapPoint) => ({
    title: p.gene,
    value: `${p.foldText ?? fmtFoldLog2(p.log2)} · same call in ${fmtShare(p.holds)}`,
    lines: [p.mark.label, ...(p.details ?? [])],
  });

  const columns: Column<MapPoint>[] = [
    { key: "gene", header: "Gene", cell: (p) => p.gene, sort: (p) => p.gene },
    { key: "mark", header: "Shown as", cell: (p) => p.mark.label, sort: (p) => p.mark.label },
    { key: "fold", header: "Fold change", cell: (p) => p.foldText ?? fmtFoldLog2(p.log2), sort: (p) => p.log2, numeric: true },
    { key: "holds", header: "Same call in", cell: (p) => fmtShare(p.holds), sort: (p) => p.holds, numeric: true },
    ...extraColumns,
  ];

  return (
    <ChartFrame
      summary={summary}
      legend={legend}
      controls={controls}
      caption={caption}
      live={active ? `${active.gene}: ${tipFor(active).value}. ${active.mark.label}.` : undefined}
      table={() => (
        <DataTable columns={columns} rows={points} rowKey={(p) => p.gene} onRowClick={onSelect ? (p) => onSelect(p.gene) : undefined} caption={summary} />
      )}
    >
      <div
        ref={ref}
        className="relative rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-focus"
        tabIndex={points.length ? 0 : -1}
        role="group"
        aria-label={`${summary} Use the arrow keys to move between genes and Enter to open one.`}
        onKeyDown={nav.onKeyDown}
        onBlur={() => {
          nav.onBlur();
          hide();
        }}
      >
        <svg width={width} height={height} role="img" aria-label={summary} className="block overflow-visible" onPointerLeave={hide}>
          {/* share axis */}
          <g aria-hidden="true">
            {yTicks.map((v) => (
              <g key={v}>
                <line x1={M.left} x2={width - M.right} y1={y(v)} y2={y(v)} stroke="var(--line)" />
                <text x={M.left - 8} y={y(v) + 4} textAnchor="end" fontSize={11} fill="var(--text-faint)" className="tabular">
                  {fmtShare(v)}
                </text>
              </g>
            ))}
            <text x={0} y={12} fontSize={11} fill="var(--text-muted)">
              Share of reasonable analyses with the same call
            </text>
            {holdsLine && holdsLine.share >= yMin && (
              <g>
                <line x1={M.left} x2={width - M.right} y1={y(holdsLine.share)} y2={y(holdsLine.share)} stroke="var(--text-faint)" strokeDasharray="4 3" />
                <text x={width - M.right} y={y(holdsLine.share) - 4} textAnchor="end" fontSize={11} fill="var(--text-muted)">
                  {holdsLine.label}
                </text>
              </g>
            )}
          </g>
          <FoldAxis scale={fs} top={M.top} bottom={bottom} line={line} lineLabel={lineLabel} lower={lower} higher={higher} />
          {/* genes */}
          <g>
            {drawOrder.map((p) => {
              const { cx, cy } = pos(p);
              const dim = highlight ? !highlight.has(p.gene) : false;
              const on = p.gene === selected || p.gene === active?.gene;
              return (
                <g
                  key={p.gene}
                  style={{ opacity: dim ? 0.18 : 1, transition: "opacity 160ms ease-out" }}
                  className={onSelect ? "cursor-pointer" : undefined}
                  onPointerEnter={() => show(cx, cy, tipFor(p))}
                  onClick={onSelect ? () => onSelect(p.gene) : undefined}
                >
                  <circle cx={cx} cy={cy} r={12} fill="transparent" />
                  {on && <circle cx={cx} cy={cy} r={r + 5} fill="none" stroke="var(--accent)" strokeWidth={2} />}
                  <GlyphMark mark={p.mark} x={cx} y={cy} r={on ? r + 1 : r} />
                </g>
              );
            })}
          </g>
          <g aria-hidden="true">
            {labels.map(({ item, text, spot }) => (
              <text
                key={item.gene}
                x={spot.x}
                y={spot.y}
                textAnchor={spot.anchor}
                fontSize={11}
                fontWeight={item.gene === selected || item.headline ? 600 : 400}
                fill={item.gene === selected || item.headline ? "var(--text)" : "var(--text-muted)"}
                style={{ opacity: highlight && !highlight.has(item.gene) ? 0.25 : 1 }}
              >
                {text}
              </text>
            ))}
          </g>
        </svg>
        <Tooltip tip={active ? { x: fs.x(active.log2), y: y(active.holds), content: tipFor(active) } : tip} width={width} />
      </div>
    </ChartFrame>
  );
}
