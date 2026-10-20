/**
 * Power against samples per group, one gene a curve, at the noise this study measured.
 *
 * Solid: how often qPilot's rule calls the change (p < α and at least the rule's fold, the right
 * way); dashed: how often it is only significant. Both are the server's simulations
 * (`simulate_calls`), never drawn from a formula here. The target power is a dashed line; the
 * plan's size and this study's own size (as a balanced equivalent) are marked. One gene is in
 * focus (accent); the others are drawn faint and named at their ends.
 */
import { scaleLinear, scaleLog } from "d3-scale";
import { line as d3line } from "d3-shape";
import { useMemo, type PointerEvent } from "react";
import { ChartFrame, LineSwatch } from "@/charts";
import { usePointNav, useTip, useWidth } from "@/charts/core/hooks";
import { localPoint } from "@/charts/core/layout";
import { Tooltip } from "@/charts/core/Tooltip";
import { count, percent } from "@/lib/format";
import { DataTable, type ColumnDef } from "@/ui";
import type { PlanPowerCurve } from "./api";

export interface PowerChartProps {
  curves: PlanPowerCurve[];
  /** The power asked for (0–1). */
  power: number;
  nPlan: number;
  /** This study's groups as one balanced size (harmonic mean). */
  nEquivalent: number;
  /** The study's own sizes, for the marker's words ("53 vs 294"). */
  nCurrent: number[];
  focus: string | null;
  onFocus: (gene: string) => void;
  minFold: number;
  targetText: string;
}

const MARGIN = { top: 18, right: 96, bottom: 40, left: 46 };
const TICKS = [2, 3, 5, 10, 20, 30, 50, 100, 200, 300, 500, 1000];

interface Row {
  key: string;
  gene: string;
  n: number;
  sig: number;
  called: number;
}

export function PowerChart({
  curves,
  power,
  nPlan,
  nEquivalent,
  nCurrent,
  focus,
  onFocus,
  minFold,
  targetText,
}: PowerChartProps) {
  const [ref, width] = useWidth<HTMLDivElement>(720);
  const { tip, show, hide } = useTip();
  const narrow = width < 560;
  const margin = { ...MARGIN, right: narrow ? 16 : MARGIN.right };
  const height = narrow ? 280 : 340;
  const lead = curves.find((c) => c.gene === focus) ?? curves[0] ?? null;
  const points = lead?.points ?? [];
  const nav = usePointNav(points.length);

  const maxN = Math.max(4, ...curves.flatMap((c) => c.points.map((p) => p.n)));
  const x = useMemo(
    () =>
      scaleLog()
        .domain([2, maxN])
        .range([margin.left, width - margin.right])
        .clamp(true),
    [maxN, width, margin.left, margin.right],
  );
  const y = useMemo(
    () =>
      scaleLinear()
        .domain([0, 1])
        .range([height - margin.bottom, margin.top]),
    [height, margin.bottom, margin.top],
  );
  const path = (key: "p_called" | "p_significant") =>
    d3line<PlanPowerCurve["points"][number]>()
      .x((p) => x(p.n))
      .y((p) => y(p[key]));

  const ticks = TICKS.filter((t) => t <= maxN);
  const nEq = Math.max(2, Math.min(maxN, nEquivalent));
  const showCurrent = nEquivalent >= 2 && nEquivalent <= maxN * 1.0001;

  // Gene names at the right ends of the call curves, nudged apart (never on top of each other).
  const ends = useMemo(() => {
    if (narrow) return [];
    const placed = curves
      .map((c) => ({ gene: c.gene, y: y(c.points[c.points.length - 1]?.p_called ?? 0) }))
      .sort((a, b) => a.y - b.y);
    for (let i = 1; i < placed.length; i++)
      if (placed[i]!.y - placed[i - 1]!.y < 13) placed[i]!.y = placed[i - 1]!.y + 13;
    return placed;
  }, [curves, y, narrow]);

  const active = nav.active != null ? points[nav.active] : null;
  const rows = useMemo<Row[]>(
    () =>
      curves.flatMap((c) =>
        c.points.map((p) => ({
          key: `${c.gene}:${p.n}`,
          gene: c.gene,
          n: p.n,
          sig: p.p_significant,
          called: p.p_called,
        })),
      ),
    [curves],
  );
  const columns = useMemo<ColumnDef<Row, unknown>[]>(
    () => [
      { id: "gene", header: "Gene", accessorKey: "gene" },
      { id: "n", header: "Per group", accessorKey: "n", meta: { numeric: true } },
      {
        id: "called",
        header: "Called by qPilot's rule",
        accessorKey: "called",
        meta: { numeric: true },
        cell: ({ row }) => percent(row.original.called),
      },
      {
        id: "sig",
        header: "Significant",
        accessorKey: "sig",
        meta: { numeric: true },
        cell: ({ row }) => percent(row.original.sig),
      },
    ],
    [],
  );

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    if (!lead || !points.length) return;
    const { x: px } = localPoint(e);
    const n = x.invert(px);
    let best = 0;
    for (let i = 1; i < points.length; i++)
      if (Math.abs(Math.log(points[i]!.n / n)) < Math.abs(Math.log(points[best]!.n / n))) best = i;
    const p = points[best]!;
    nav.setActive(best);
    show(x(p.n), y(p.p_called), {
      title: `${lead.gene}, ${count(p.n)} per group`,
      value: `called ${percent(p.p_called)}`,
      lines: [`significant ${percent(p.p_significant)}`, `σ ${lead.sigma.toFixed(2)} (log2)`],
    });
  };

  const summary = lead
    ? `How often a true ${targetText} change in ${lead.gene} is called by qPilot's rule (solid) or only significant (dashed), from 2 to ${count(maxN)} samples per group, at this study's noise. ` +
      (lead.n_for_call != null
        ? `It is called with ${percent(power)} power from ${count(lead.n_for_call)} per group.`
        : `No size reaches ${percent(power)} for a call: the change is at or below the rule's ${minFold}-fold line, or needs more than the planner lays out.`)
    : "No genes chosen.";

  return (
    <ChartFrame
      summary={summary}
      legend={[
        {
          swatch: <LineSwatch tone="var(--accent)" width={2.5} />,
          label: "Called by qPilot's rule",
        },
        { swatch: <LineSwatch tone="var(--accent)" dashed />, label: "Significant (p < α)" },
        {
          swatch: <LineSwatch tone="var(--text-faint)" dashed width={1.25} />,
          label: `${percent(power)} power`,
        },
      ]}
      live={
        active && lead
          ? `${lead.gene}, ${count(active.n)} per group: called ${percent(active.p_called)}, significant ${percent(active.p_significant)}`
          : undefined
      }
      table={() => (
        <DataTable
          data={rows}
          columns={columns}
          getRowId={(r) => r.key}
          label="Power by samples per group"
          height={420}
        />
      )}
    >
      <div
        ref={ref}
        className="relative rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-focus"
        tabIndex={points.length ? 0 : -1}
        role="group"
        aria-label={`${summary} Use the arrow keys to read ${lead?.gene ?? "the"} curve.`}
        onKeyDown={(e) => {
          nav.onKeyDown(e);
        }}
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
          onPointerMove={onMove}
          onPointerLeave={() => {
            hide();
            nav.setActive(null);
          }}
        >
          {/* grid and axes */}
          <g aria-hidden="true" fontSize={11} fill="var(--text-muted)">
            {[0, 0.25, 0.5, 0.75, 1].map((v) => (
              <g key={v}>
                <line
                  x1={margin.left}
                  x2={width - margin.right}
                  y1={y(v)}
                  y2={y(v)}
                  stroke="var(--line)"
                  strokeWidth={1}
                />
                <text x={margin.left - 8} y={y(v) + 4} textAnchor="end" className="tabular">
                  {Math.round(v * 100)}
                </text>
              </g>
            ))}
            {ticks.map((t) => (
              <g key={t}>
                <line
                  x1={x(t)}
                  x2={x(t)}
                  y1={height - margin.bottom}
                  y2={height - margin.bottom + 4}
                  stroke="var(--line-strong)"
                />
                <text
                  x={x(t)}
                  y={height - margin.bottom + 16}
                  textAnchor="middle"
                  className="tabular"
                >
                  {count(t)}
                </text>
              </g>
            ))}
            <text x={margin.left - 36} y={margin.top - 6} fill="var(--text-muted)">
              %
            </text>
            <text x={(margin.left + width - margin.right) / 2} y={height - 6} textAnchor="middle">
              Samples per group (log scale)
            </text>
          </g>

          {/* target power */}
          <g aria-hidden="true">
            <line
              x1={margin.left}
              x2={width - margin.right}
              y1={y(power)}
              y2={y(power)}
              stroke="var(--text-faint)"
              strokeWidth={1.25}
              strokeDasharray="5 4"
            />
          </g>

          {/* this study, as a balanced equivalent */}
          {showCurrent && (
            <g aria-hidden="true">
              <line
                x1={x(nEq)}
                x2={x(nEq)}
                y1={margin.top}
                y2={height - margin.bottom}
                stroke="var(--text-muted)"
                strokeWidth={1}
                strokeDasharray="2 3"
              />
              <text
                x={x(nEq) + (x(nEq) > width - 150 ? -4 : 4)}
                y={margin.top + 10}
                fontSize={11}
                fill="var(--text-muted)"
                textAnchor={x(nEq) > width - 150 ? "end" : "start"}
              >
                {nCurrent.length >= 2
                  ? `this study (${nCurrent.map((n) => count(n)).join(" vs ")})`
                  : "this study"}
              </text>
            </g>
          )}

          {/* the plan's size */}
          <g aria-hidden="true">
            <line
              x1={x(nPlan)}
              x2={x(nPlan)}
              y1={margin.top}
              y2={height - margin.bottom}
              stroke="var(--accent)"
              strokeWidth={1.5}
            />
            <text
              x={x(nPlan) + (x(nPlan) > width - 150 ? -4 : 4)}
              y={height - margin.bottom - 6}
              fontSize={11}
              fontWeight={600}
              fill="var(--accent-strong)"
              textAnchor={x(nPlan) > width - 150 ? "end" : "start"}
            >
              plan: {count(nPlan)} per group
            </text>
          </g>

          {/* the curves: others first (faint), the focus gene last (on top) */}
          {[...curves]
            .sort((a, b) => (a.gene === lead?.gene ? 1 : 0) - (b.gene === lead?.gene ? 1 : 0))
            .map((c) => {
              const on = c.gene === lead?.gene;
              const tone = on ? "var(--accent)" : "var(--text-faint)";
              return (
                <g key={c.gene} aria-hidden="true">
                  <path
                    d={path("p_significant")(c.points) ?? ""}
                    fill="none"
                    stroke={tone}
                    strokeWidth={on ? 1.75 : 1}
                    strokeDasharray="5 3"
                    opacity={on ? 0.9 : 0.55}
                  />
                  <path
                    d={path("p_called")(c.points) ?? ""}
                    fill="none"
                    stroke={tone}
                    strokeWidth={on ? 2.75 : 1.25}
                    opacity={on ? 1 : 0.7}
                    style={{ cursor: "pointer" }}
                    onClick={() => onFocus(c.gene)}
                  />
                  {on && c.n_for_call != null && c.n_for_call <= maxN && (
                    <circle
                      cx={x(c.n_for_call)}
                      cy={y(power)}
                      r={4.5}
                      fill="var(--surface)"
                      stroke="var(--accent)"
                      strokeWidth={2}
                    />
                  )}
                </g>
              );
            })}

          {/* names at the ends */}
          {ends.map((e) => (
            <text
              key={e.gene}
              x={width - margin.right + 8}
              y={e.y + 4}
              fontSize={11}
              fontWeight={e.gene === lead?.gene ? 600 : 400}
              fill={e.gene === lead?.gene ? "var(--accent-strong)" : "var(--text-muted)"}
              style={{ cursor: "pointer" }}
              onClick={() => onFocus(e.gene)}
            >
              {e.gene}
            </text>
          ))}

          {/* the keyboard's / pointer's point */}
          {active && (
            <g aria-hidden="true">
              <line
                x1={x(active.n)}
                x2={x(active.n)}
                y1={margin.top}
                y2={height - margin.bottom}
                stroke="var(--line-strong)"
              />
              <circle cx={x(active.n)} cy={y(active.p_called)} r={4} fill="var(--accent)" />
              <circle
                cx={x(active.n)}
                cy={y(active.p_significant)}
                r={3.5}
                fill="var(--surface)"
                stroke="var(--accent)"
                strokeWidth={1.5}
              />
            </g>
          )}
        </svg>
        <Tooltip tip={tip} width={width} />
      </div>
    </ChartFrame>
  );
}
