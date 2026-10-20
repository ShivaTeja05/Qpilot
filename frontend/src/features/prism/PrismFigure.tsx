/**
 * The figure Prism will draw for one gene, approximated: every biological unit as a dot in its
 * group's column, the group mean as a bar and its 95 % confidence interval as a whisker, on a
 * linear axis of log2 relative quantities (the `two_groups_log2` template's graph). Prism draws
 * the real one; this shows what goes in. Built on the charts' frame (View as table, keyboard,
 * tooltip) so it behaves like every other chart on the page.
 */
import { scaleLinear } from "d3-scale";
import { useMemo } from "react";
import { ChartFrame, DataTable, LineSwatch, type Column, type LegendItem } from "@/charts";
import { usePointNav, useTip, useWidth } from "@/charts/core/hooks";
import { beeswarm } from "@/charts/core/layout";
import { Tooltip } from "@/charts/core/Tooltip";
import { count, fixed, MINUS } from "@/lib/format";
import type { FigureGroup, PrismFigureData } from "./api";

const TONES = ["var(--accent)", "var(--text-muted)", "var(--info)", "var(--warn)"];
const TOP = 12;
const AXIS_W = 52;
const BOTTOM = 44;

/** A log2 value as the axis and the table print it: `2.88`, `−0.41`. */
export function log2Text(v: number | null | undefined): string {
  return fixed(v, 2).replace("-", MINUS);
}

interface Dot {
  unit: string;
  value: number;
  gi: number;
  x: number;
  y: number;
}

export function PrismFigure({ figure, caption }: { figure: PrismFigureData; caption?: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTip();
  const height = Math.max(260, Math.min(360, Math.round(width * 0.55)));
  const groups = figure.groups;

  const y = useMemo(() => {
    const values = groups.flatMap((g) => [
      ...g.points.map((p) => p.value),
      ...[g.ci_lo, g.ci_hi, g.mean].filter(
        (v): v is number => typeof v === "number" && Number.isFinite(v),
      ),
    ]);
    const lo = values.length ? Math.min(...values) : 0;
    const hi = values.length ? Math.max(...values) : 1;
    const pad = (hi - lo || 1) * 0.06;
    return scaleLinear()
      .domain([lo - pad, hi + pad])
      .range([height - BOTTOM, TOP])
      .nice();
  }, [groups, height]);

  const plotW = Math.max(120, width - AXIS_W - 8);
  const band = plotW / Math.max(1, groups.length);
  const centreX = (gi: number) => AXIS_W + band * gi + band / 2;
  const r = width < 480 ? 2.4 : 2.9;

  const dots = useMemo<Dot[]>(() => {
    const out: Dot[] = [];
    groups.forEach((g, gi) => {
      const half = Math.min(band * 0.34, 90);
      for (const b of beeswarm(g.points, (p) => y(p.value), r, half, 0.5)) {
        out.push({ unit: b.item.unit, value: b.item.value, gi, x: centreX(gi) + b.dy, y: b.x });
      }
    });
    return out;
    // centreX depends on band only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups, y, band, r]);

  const order = useMemo(() => [...dots].sort((a, b) => a.gi - b.gi || b.value - a.value), [dots]);
  const nav = usePointNav(order.length);
  const active = nav.active != null ? order[nav.active] : null;

  const tipFor = (d: Dot) => ({
    title: `Unit ${d.unit}`,
    value: log2Text(d.value),
    lines: [groups[d.gi]?.name, "log2 relative quantity"],
  });

  const summary = summaryOf(figure);
  const legend: LegendItem[] = [
    ...groups.slice(0, 4).map((g, gi) => ({
      mark: { shape: "circle" as const, tone: TONES[gi]! },
      label: `${g.name} (${count(g.n)})`,
    })),
    {
      swatch: <LineSwatch tone="var(--text)" width={3} />,
      label: "Mean and 95 % confidence interval",
    },
  ];

  const columns: Column<Dot>[] = [
    { key: "unit", header: "Biological unit", cell: (d) => d.unit, sort: (d) => d.unit },
    { key: "group", header: "Group", cell: (d) => groups[d.gi]?.name ?? "", sort: (d) => d.gi },
    {
      key: "value",
      header: "log2 relative quantity",
      cell: (d) => log2Text(d.value),
      sort: (d) => d.value,
      numeric: true,
    },
  ];

  const ticks = y.ticks(Math.max(3, Math.round(height / 60)));
  return (
    <ChartFrame
      summary={summary}
      legend={legend}
      caption={caption}
      live={
        active
          ? `${tipFor(active).title}, ${groups[active.gi]?.name}: ${tipFor(active).value}`
          : undefined
      }
      table={() => (
        <DataTable
          columns={columns}
          rows={order}
          rowKey={(d) => `${d.gi}:${d.unit}`}
          caption={summary}
        />
      )}
    >
      <div
        ref={ref}
        className="relative rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-focus"
        tabIndex={dots.length ? 0 : -1}
        role="group"
        aria-label={`${summary} Use the arrow keys to move between units.`}
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
          {ticks.map((t) => (
            <g key={t}>
              <line
                x1={AXIS_W}
                x2={width - 4}
                y1={y(t)}
                y2={y(t)}
                stroke="var(--line)"
                strokeDasharray={t === 0 ? undefined : "2 3"}
              />
              <text
                x={AXIS_W - 6}
                y={y(t) + 4}
                textAnchor="end"
                fontSize={11}
                fill="var(--text-muted)"
                className="tabular"
              >
                {log2Text(t)}
              </text>
            </g>
          ))}
          <text
            transform={`translate(12 ${(TOP + height - BOTTOM) / 2}) rotate(-90)`}
            textAnchor="middle"
            fontSize={11}
            fill="var(--text-muted)"
          >
            log2 relative quantity
          </text>
          {groups.map((g, gi) => {
            const cx = centreX(gi);
            return (
              <g key={g.name}>
                <text
                  x={cx}
                  y={height - BOTTOM + 18}
                  textAnchor="middle"
                  fontSize={12}
                  fontWeight={600}
                  fill="var(--text)"
                >
                  {g.name}
                </text>
                <text
                  x={cx}
                  y={height - BOTTOM + 33}
                  textAnchor="middle"
                  fontSize={11}
                  fill="var(--text-muted)"
                  className="tabular"
                >
                  {count(g.n)} units
                </text>
              </g>
            );
          })}
          {dots.map((d) => {
            const on = active === d;
            return (
              <g key={`${d.gi}:${d.unit}`} onPointerEnter={() => show(d.x, d.y, tipFor(d))}>
                <circle cx={d.x} cy={d.y} r={Math.max(5, r + 2)} fill="transparent" />
                <circle
                  cx={d.x}
                  cy={d.y}
                  r={on ? r + 1.5 : r}
                  fill={TONES[d.gi % TONES.length]}
                  fillOpacity={0.55}
                />
                {on ? (
                  <circle
                    cx={d.x}
                    cy={d.y}
                    r={r + 5}
                    fill="none"
                    stroke="var(--accent)"
                    strokeWidth={2}
                  />
                ) : null}
              </g>
            );
          })}
          {groups.map((g, gi) => (
            <SummaryMarks key={g.name} group={g} cx={centreX(gi)} band={band} y={y} />
          ))}
        </svg>
        <Tooltip
          tip={active ? { x: active.x, y: active.y, content: tipFor(active) } : tip}
          width={width}
        />
      </div>
    </ChartFrame>
  );
}

/** One sentence for screen readers: the gene, each group's n and mean with its interval. */
export function summaryOf(figure: PrismFigureData): string {
  const parts = figure.groups.map((g) => {
    const mean = g.mean != null ? `, mean ${log2Text(g.mean)}` : "";
    const ci =
      g.ci_lo != null && g.ci_hi != null
        ? ` (95 % CI ${log2Text(g.ci_lo)} to ${log2Text(g.ci_hi)})`
        : "";
    return `${g.name}: ${count(g.n)} units${mean}${ci}`;
  });
  return `${figure.gene}, log2 relative quantity per biological unit. ${parts.join("; ")}.`;
}

/**
 * A group's mean (a bar) and its 95 % confidence interval (a capped whisker), drawn over the
 * dots with a halo in the surface colour so they stay readable on a dense swarm.
 */
function SummaryMarks({
  group: g,
  cx,
  band,
  y,
}: {
  group: FigureGroup;
  cx: number;
  band: number;
  y: (v: number) => number;
}) {
  const finite = (v: number | null | undefined): v is number =>
    typeof v === "number" && Number.isFinite(v);
  const capW = Math.min(band * 0.22, 26);
  const meanW = Math.min(band * 0.42, 52);
  const lines: { x1: number; x2: number; y1: number; y2: number; w: number }[] = [];
  if (finite(g.ci_lo) && finite(g.ci_hi)) {
    const lo = y(g.ci_lo);
    const hi = y(g.ci_hi);
    lines.push({ x1: cx, x2: cx, y1: lo, y2: hi, w: 2 });
    lines.push({ x1: cx - capW / 2, x2: cx + capW / 2, y1: lo, y2: lo, w: 2 });
    lines.push({ x1: cx - capW / 2, x2: cx + capW / 2, y1: hi, y2: hi, w: 2 });
  }
  if (finite(g.mean)) {
    const m = y(g.mean);
    lines.push({ x1: cx - meanW / 2, x2: cx + meanW / 2, y1: m, y2: m, w: 3 });
  }
  return (
    <g aria-hidden="true" strokeLinecap="round">
      {lines.map((l, i) => (
        <line key={`h${i}`} {...l} stroke="var(--surface)" strokeWidth={l.w + 3} />
      ))}
      {lines.map((l, i) => (
        <line key={`l${i}`} {...l} stroke="var(--text)" strokeWidth={l.w} />
      ))}
    </g>
  );
}
