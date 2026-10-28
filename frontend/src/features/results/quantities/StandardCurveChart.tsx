/**
 * One standard curve: Cq against log10 quantity. Every standard well is a dot (a cross at the
 * foot of the chart when it was not detected), the fitted line runs through them with its 95 %
 * prediction band for one new well, the LOD and LOQ are dashed verticals, and each unknown unit
 * read from this curve is a diamond at its quantity and mean Cq. Every number is the API's.
 * Hover or the arrow keys show a well; "View as table" lists the levels.
 */
import { useMemo, useState } from "react";
import { ChartFrame, DataTable, LineSwatch, type Column, type LegendItem } from "@/charts";
import { usePointNav, useTip, useWidth } from "@/charts/core/hooks";
import { localPoint, nearestIndex } from "@/charts/core/layout";
import { Tooltip } from "@/charts/core/Tooltip";
import { GlyphMark } from "@/ui";
import { fixed } from "@/lib/format";
import type { CurveDetail, UnitQuantity } from "./api";
import { fmtEfficiency, fmtQuantity, fmtStandard, fmtWells, powerOfTen, unitWords } from "./format";

const HEIGHT = 300;
const M = { top: 22, right: 18, bottom: 44, left: 48 };
const ND_GAP = 22; // the strip under the axis where undetected wells sit

interface Dot {
  x: number;
  y: number;
  kind: "standard" | "missing" | "unknown";
  title: string;
  value: string;
  lines: string[];
}

function niceStep(span: number): number {
  const raw = span / 5;
  for (const s of [0.5, 1, 2, 5, 10]) if (raw <= s) return s;
  return 10;
}

export function curveSummary(curve: CurveDetail, unit: string): string {
  if (!curve.fitted || curve.slope == null) {
    return `${curve.target}: no standard curve (${curve.problem}).`;
  }
  return (
    `Standard curve of ${curve.target} (${curve.runs.join(", ")}): slope ${fixed(curve.slope, 3)}, ` +
    `efficiency ${fmtEfficiency(curve.efficiency)}, R² ${fixed(curve.r2, 4)}, ` +
    `${curve.n_levels} levels from ${fmtStandard(curve.lowest)} to ${fmtStandard(curve.top)} ` +
    `${unitWords(unit)}.`
  );
}

export function StandardCurveChart({
  curve,
  unknowns,
  unit,
}: {
  curve: CurveDetail;
  unknowns: UnitQuantity[];
  unit: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>(640);
  const { tip, show, hide } = useTip();
  const [hover, setHover] = useState(-1);
  const read = useMemo(
    () =>
      unknowns.filter(
        (u) => u.quantity != null && u.mean_cq != null && u.curves.includes(curve.id),
      ),
    [unknowns, curve.id],
  );

  const geometry = useMemo(() => {
    const xs: number[] = [
      ...curve.points.map((p) => Math.log10(p.quantity)),
      ...curve.band.map((b) => b.log10_quantity),
    ];
    const ys: number[] = [
      ...curve.points.flatMap((p) => (p.cq != null ? [p.cq] : [])),
      ...curve.band.flatMap((b) => [b.low, b.high]),
    ];
    const lo = Math.min(...xs);
    const hi = Math.max(...xs);
    // unknowns widen the axis by at most one decade each side (extrapolation stays visible)
    const ux = read.map((u) => Math.log10(u.quantity!));
    const x0 = Math.max(lo - 1, Math.min(lo, ...ux)) - 0.15;
    const x1 = Math.min(hi + 1, Math.max(hi, ...ux)) + 0.15;
    for (const u of read) ys.push(u.mean_cq!);
    const y0 = Math.floor(Math.min(...ys) - 1);
    const y1 = Math.ceil(Math.max(...ys) + 1);
    const plotW = Math.max(120, width - M.left - M.right);
    const plotH = HEIGHT - M.top - M.bottom - ND_GAP;
    const sx = (x: number) => M.left + ((x - x0) / (x1 - x0)) * plotW;
    const sy = (y: number) => M.top + ((y1 - y) / (y1 - y0)) * plotH;
    return { x0, x1, y0, y1, sx, sy, plotW, plotH };
  }, [curve, read, width]);
  const { x0, x1, y0, y1, sx, sy, plotH } = geometry;
  const floor = M.top + plotH;

  const dots: Dot[] = useMemo(() => {
    const out: Dot[] = curve.points.map((p) => {
      const x = sx(Math.log10(p.quantity));
      const where = `${p.run_id} · ${p.well} (${p.sample})`;
      if (!p.detected || p.cq == null) {
        return {
          x,
          y: floor + ND_GAP / 2 + 2,
          kind: "missing" as const,
          title: `Standard ${fmtStandard(p.quantity)}`,
          value: "not detected",
          lines: [where],
        };
      }
      return {
        x,
        y: sy(p.cq),
        kind: "standard" as const,
        title: `Standard ${fmtStandard(p.quantity)}`,
        value: `Cq ${fixed(p.cq, 2)}`,
        lines: [
          where,
          p.back_quantity != null ? `reads back as ${fmtQuantity(p.back_quantity)}` : null,
          p.residual != null ? `${fixed(p.residual, 2)} cycles off the line` : null,
        ].filter((l): l is string => Boolean(l)),
      };
    });
    for (const u of read) {
      out.push({
        x: sx(Math.log10(u.quantity!)),
        y: sy(u.mean_cq!),
        kind: "unknown",
        title: u.group ? `${u.unit} (${u.group})` : u.unit,
        value: `${fmtQuantity(u.quantity)} ${unitWords(unit)}`,
        lines: [
          `mean Cq ${fixed(u.mean_cq, 2)} of ${fmtWells(u.n_detected, u.n_wells)} wells`,
          ...u.flags.map((f) => f.words),
        ],
      });
    }
    return out;
  }, [curve.points, read, sx, sy, floor, unit]);

  const nav = usePointNav(dots.length);
  const active = nav.active != null ? dots[nav.active] : undefined;
  const shown = active ?? (hover >= 0 ? dots[hover] : undefined);

  const band = curve.band;
  const bandPath = band.length
    ? `M${band.map((b) => `${sx(b.log10_quantity)},${sy(b.high)}`).join("L")}L${[...band]
        .reverse()
        .map((b) => `${sx(b.log10_quantity)},${sy(b.low)}`)
        .join("L")}Z`
    : "";
  const linePath = band.length
    ? `M${band.map((b) => `${sx(b.log10_quantity)},${sy(b.cq)}`).join("L")}`
    : "";
  const xTicks: number[] = [];
  for (let e = Math.ceil(x0); e <= Math.floor(x1); e++) xTicks.push(e);
  const step = niceStep(y1 - y0);
  const yTicks: number[] = [];
  for (let v = Math.ceil(y0 / step) * step; v <= y1; v += step) yTicks.push(v);
  const limits = [
    { key: "LOD", q: curve.lod.quantity, at_most: curve.lod.at_most },
    { key: "LOQ", q: curve.loq.quantity, at_most: false },
  ].filter((l) => l.q != null && Math.log10(l.q) >= x0 && Math.log10(l.q) <= x1);

  const summary = curveSummary(curve, unit);
  const legend: LegendItem[] = [
    { mark: { shape: "circle", tone: "var(--accent)" }, label: "Standard well" },
    ...(dots.some((d) => d.kind === "missing")
      ? [{ mark: { shape: "cross" as const, tone: "var(--warn)" }, label: "Standard not detected" }]
      : []),
    { swatch: <LineSwatch tone="var(--accent)" />, label: "Fitted line" },
    {
      swatch: (
        <svg width="14" height="12" aria-hidden="true">
          <rect x="1" y="2" width="12" height="8" rx="2" fill="var(--accent-soft)" />
        </svg>
      ),
      label: "95 % prediction band (one well)",
    },
    ...(read.length
      ? [
          {
            mark: { shape: "diamond" as const, tone: "var(--text-muted)" },
            label: "Unknown (unit)",
          },
        ]
      : []),
    ...(limits.length ? [{ swatch: <LineSwatch dashed />, label: "LOD / LOQ" }] : []),
  ];
  const levelColumns: Column<CurveDetail["levels"][number]>[] = [
    {
      key: "q",
      header: "Quantity",
      cell: (l) => fmtStandard(l.quantity),
      sort: (l) => l.quantity,
      numeric: true,
    },
    {
      key: "wells",
      header: "Detected",
      cell: (l) => fmtWells(l.n_detected, l.n_wells),
      sort: (l) => l.rate,
      numeric: true,
    },
    {
      key: "cq",
      header: "Mean Cq",
      cell: (l) => fixed(l.mean_cq, 2),
      sort: (l) => l.mean_cq,
      numeric: true,
    },
    {
      key: "sd",
      header: "SD Cq",
      cell: (l) => fixed(l.sd_cq, 2),
      sort: (l) => l.sd_cq,
      numeric: true,
    },
    {
      key: "back",
      header: "Reads back as",
      cell: (l) => fmtQuantity(l.back_quantity),
      sort: (l) => l.back_quantity,
      numeric: true,
    },
    {
      key: "cv",
      header: "CV",
      cell: (l) => (l.cv == null ? "—" : `${fixed(l.cv * 100, 1)} %`),
      sort: (l) => l.cv,
      numeric: true,
    },
  ];

  return (
    <ChartFrame
      summary={summary}
      legend={legend}
      live={shown ? `${shown.title}: ${shown.value}` : undefined}
      caption={
        <>
          Cq of each standard well against its quantity ({unitWords(unit)}, log scale). The band is
          where 95 % of new wells on this curve would fall. Diamonds are the units read from it (
          {read.length}); a unit outside the standards is extrapolated.
        </>
      }
      table={() => (
        <DataTable
          columns={levelColumns}
          rows={curve.levels}
          rowKey={(l) => String(l.quantity)}
          caption={summary}
        />
      )}
    >
      <div
        ref={ref}
        className="relative rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-focus"
        tabIndex={dots.length ? 0 : -1}
        role="group"
        aria-label={`${summary} Use the arrow keys to move between wells.`}
        onKeyDown={nav.onKeyDown}
        onBlur={() => {
          nav.onBlur();
          hide();
        }}
      >
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={summary}
          className="block overflow-visible"
          onPointerLeave={() => {
            setHover(-1);
            hide();
          }}
          onPointerMove={(e) => {
            const { x, y } = localPoint(e);
            const i = nearestIndex(dots, x, y, 12);
            setHover(i);
            if (i >= 0) show(dots[i]!.x, dots[i]!.y, dots[i]!);
            else hide();
          }}
        >
          {yTicks.map((v) => (
            <g key={`y${v}`}>
              <line x1={M.left} x2={width - M.right} y1={sy(v)} y2={sy(v)} stroke="var(--line)" />
              <text
                x={M.left - 6}
                y={sy(v) + 4}
                fontSize={11}
                textAnchor="end"
                fill="var(--text-muted)"
              >
                {fixed(v, step < 1 ? 1 : 0)}
              </text>
            </g>
          ))}
          {xTicks.map((e) => (
            <text
              key={`x${e}`}
              x={sx(e)}
              y={HEIGHT - M.bottom + 16}
              fontSize={11}
              textAnchor="middle"
              fill="var(--text-muted)"
            >
              {powerOfTen(e)}
            </text>
          ))}
          <line
            x1={M.left}
            x2={width - M.right}
            y1={floor}
            y2={floor}
            stroke="var(--line-strong)"
          />
          <text
            x={M.left - 6}
            y={floor + ND_GAP / 2 + 6}
            fontSize={10}
            textAnchor="end"
            fill="var(--text-faint)"
          >
            none
          </text>
          <text
            x={M.left + (width - M.left - M.right) / 2}
            y={HEIGHT - 6}
            fontSize={11}
            textAnchor="middle"
            fill="var(--text-muted)"
          >
            Quantity per reaction ({unitWords(unit)})
          </text>
          <text
            x={12}
            y={M.top + plotH / 2}
            fontSize={11}
            fill="var(--text-muted)"
            transform={`rotate(-90 12 ${M.top + plotH / 2})`}
            textAnchor="middle"
          >
            Cq
          </text>
          {bandPath && <path d={bandPath} fill="var(--accent-soft)" opacity={0.7} />}
          {linePath && <path d={linePath} fill="none" stroke="var(--accent)" strokeWidth={2} />}
          {limits.map((l) => {
            const x = sx(Math.log10(l.q!));
            return (
              <g key={l.key}>
                <line
                  x1={x}
                  x2={x}
                  y1={M.top - 4}
                  y2={floor}
                  stroke="var(--text-faint)"
                  strokeDasharray="4 3"
                />
                <text x={x + 3} y={M.top - 8} fontSize={11} fill="var(--text-muted)">
                  {l.at_most ? `${l.key} ≤` : l.key}
                </text>
              </g>
            );
          })}
          {dots.map((d, i) => {
            const on = shown === d;
            const mark =
              d.kind === "standard"
                ? { shape: "circle" as const, tone: "var(--accent)" }
                : d.kind === "missing"
                  ? { shape: "cross" as const, tone: "var(--warn)" }
                  : { shape: "diamond" as const, tone: "var(--text-muted)" };
            return <GlyphMark key={i} mark={mark} x={d.x} y={d.y} r={on ? 6 : 4.5} ring />;
          })}
        </svg>
        <Tooltip tip={active ? { x: active.x, y: active.y, content: active } : tip} width={width} />
      </div>
    </ChartFrame>
  );
}
