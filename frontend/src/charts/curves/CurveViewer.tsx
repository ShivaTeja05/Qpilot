/**
 * The curve viewer (uPlot): fluorescence by cycle for one or more wells, a linear/log switch, the
 * Cq marker and the baseline when known, neighbouring wells of the same sample overlaid faint,
 * themed for light and dark (re-drawn when the theme changes), sized to its container, with an
 * accessible summary and "View as table". Drag across the plot to zoom; double-click to reset.
 */
import { LineChart, Table2 } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { cn } from "@/lib/cn";
import { count, fixed } from "@/lib/format";
import { useTheme } from "@/lib/theme";
import { SegmentedControl } from "@/ui";
import { CurveTable } from "./CurveTable";
import { SERIES_TOKENS, align, curvesSummary, decimalsFor, type CurveScale, type CurveSeries } from "./data";

export interface CurveViewerProps {
  series: readonly CurveSeries[];
  /** What the y values are ("Fluorescence (raw)", "Fluorescence ÷ the curve's minimum"). */
  yLabel: string;
  /** What these curves are, for the table caption ("Well A1 of plate ODC1_20080226"). */
  label: string;
  /** Controlled scale; uncontrolled (starting at `defaultScale`) when omitted. */
  scale?: CurveScale;
  defaultScale?: CurveScale;
  onScaleChange?: (scale: CurveScale) => void;
  /** Plot height in CSS pixels (default 280). */
  height?: number;
  /** Controls in the header row, before the scale switch. */
  controls?: ReactNode;
  caption?: ReactNode;
  className?: string;
}

function cssVar(name: string): string {
  if (typeof document === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** A colour with transparency, from a token's resolved hex (`#rrggbb`) or any CSS colour. */
function withAlpha(color: string, alpha: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(color);
  if (!m) return color;
  const n = parseInt(m[1]!, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

function tick(v: number): string {
  if (!Number.isFinite(v)) return "";
  return Math.abs(v) >= 1000 ? count(v) : String(Number(v.toPrecision(3)));
}

export function CurveViewer({
  series,
  yLabel,
  label,
  scale: scaleProp,
  defaultScale = "linear",
  onScaleChange,
  height = 280,
  controls,
  caption,
  className,
}: CurveViewerProps) {
  const [ownScale, setOwnScale] = useState<CurveScale>(defaultScale);
  const scale = scaleProp ?? ownScale;
  const setScale = (s: CurveScale) => {
    if (scaleProp === undefined) setOwnScale(s);
    onScaleChange?.(s);
  };
  const [asTable, setAsTable] = useState(false);
  const captionId = useId();
  const summary = curvesSummary(series, yLabel);
  const aligned = useMemo(() => align(series, scale), [series, scale]);
  const decimals = useMemo(() => decimalsFor(series), [series]);
  const hidden = aligned.hidden.reduce((a, b) => a + b, 0);

  return (
    <figure className={cn("m-0 min-w-0", className)} aria-label={summary} aria-describedby={caption ? captionId : undefined}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">{!asTable ? <SeriesLegend series={series} /> : null}</div>
        <div className="flex flex-wrap items-center gap-2">
          {controls}
          <SegmentedControl<CurveScale>
            size="sm"
            label="Fluorescence axis"
            value={scale}
            onValueChange={setScale}
            options={[
              { value: "linear", label: "Linear" },
              { value: "log", label: "Log" },
            ]}
          />
          <button
            type="button"
            onClick={() => setAsTable((v) => !v)}
            aria-pressed={asTable}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-line bg-surface px-2 text-[12px] text-muted hover:border-line-strong hover:text-fg"
          >
            {asTable ? <LineChart size={14} aria-hidden /> : <Table2 size={14} aria-hidden />}
            {asTable ? "View as chart" : "View as table"}
          </button>
        </div>
      </div>
      {asTable ? (
        <CurveTable series={series} label={label} decimals={decimals} />
      ) : series.length ? (
        <Plot series={series} aligned={aligned} scale={scale} yLabel={yLabel} height={height} decimals={decimals} summary={summary} />
      ) : (
        <div
          className="flex items-center justify-center rounded-lg border border-dashed border-line-strong text-[13px] text-muted"
          style={{ height }}
        >
          No curve to show.
        </div>
      )}
      {scale === "log" && hidden > 0 && !asTable ? (
        <p className="mt-1.5 text-[12px] text-muted">
          {hidden === 1 ? "One value" : `${count(hidden)} values`} at or below zero cannot be drawn on a log scale; the
          table lists {hidden === 1 ? "it" : "them"}.
        </p>
      ) : null}
      {caption ? (
        <figcaption id={captionId} className="mt-2 text-[12px] leading-relaxed text-muted">
          {caption}
        </figcaption>
      ) : null}
    </figure>
  );
}

// ---------------------------------------------------------------------------------------------

function seriesColorVar(s: CurveSeries, focusIndex: number): string {
  return s.role === "context" ? "--text-faint" : SERIES_TOKENS[focusIndex % SERIES_TOKENS.length]!;
}

/** The focus index of each series (context series get -1). */
function focusIndices(series: readonly CurveSeries[]): number[] {
  let i = 0;
  return series.map((s) => (s.role === "context" ? -1 : i++));
}

function SeriesLegend({ series }: { series: readonly CurveSeries[] }) {
  const idx = focusIndices(series);
  const focus = series.filter((s) => s.role !== "context");
  const context = series.filter((s) => s.role === "context");
  if (!series.length) return null;
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
      {focus.map((s) => {
        const i = idx[series.indexOf(s)]!;
        return (
          <li key={s.id} className="inline-flex items-center gap-1.5">
            <svg width="16" height="10" aria-hidden="true">
              <line x1="1" x2="15" y1="5" y2="5" strokeWidth="2.5" strokeLinecap="round" style={{ stroke: `var(${seriesColorVar(s, i)})` }} />
            </svg>
            <span className="text-fg">{s.label}</span>
            <span className="font-mono text-faint tabular">{s.cq != null && Number.isFinite(s.cq) ? `Cq ${fixed(s.cq, 1)}` : "no Cq"}</span>
          </li>
        );
      })}
      {context.length ? (
        <li className="inline-flex items-center gap-1.5">
          <svg width="16" height="10" aria-hidden="true">
            <line x1="1" x2="15" y1="5" y2="5" strokeWidth="1.5" style={{ stroke: "var(--text-faint)" }} />
          </svg>
          <span>
            {context.length === 1 ? "Another well" : `${count(context.length)} other wells`} of the same sample
          </span>
        </li>
      ) : null}
      {focus.some((s) => s.baseline != null) ? (
        <li className="inline-flex items-center gap-1.5">
          <svg width="16" height="10" aria-hidden="true">
            <line x1="1" x2="15" y1="5" y2="5" strokeWidth="1.5" strokeDasharray="3 2" style={{ stroke: "var(--text-muted)" }} />
          </svg>
          <span>Baseline</span>
        </li>
      ) : null}
    </ul>
  );
}

function Plot({
  series,
  aligned,
  scale,
  yLabel,
  height,
  decimals,
  summary,
}: {
  series: readonly CurveSeries[];
  aligned: ReturnType<typeof align>;
  scale: CurveScale;
  yLabel: string;
  height: number;
  decimals: number;
  summary: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const plot = useRef<uPlot | null>(null);
  const { theme } = useTheme();
  const [cursor, setCursor] = useState<number | null>(null);
  const cursorRef = useRef<number | null>(null);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const idx = focusIndices(series);
    const colors = series.map((s, i) => cssVar(seriesColorVar(s, idx[i]!)) || "#888");
    const muted = cssVar("--text-muted");
    const faint = cssVar("--text-faint");
    const line = cssVar("--line");
    const font = '12px "Inter Variable", ui-sans-serif, system-ui, sans-serif';
    const mono = '11px "JetBrains Mono Variable", ui-monospace, monospace';
    const axis = {
      stroke: muted,
      grid: { stroke: line, width: 1 },
      ticks: { stroke: line, width: 1, size: 4 },
      font: mono,
      labelFont: font,
    };

    const drawMarkers = (u: uPlot) => {
      const ctx = u.ctx;
      const ratio = uPlot.pxRatio;
      const { left, top, width, height: h } = u.bbox;
      ctx.save();
      ctx.beginPath();
      ctx.rect(left, top, width, h);
      ctx.clip();
      ctx.font = `${11 * ratio}px "JetBrains Mono Variable", ui-monospace, monospace`;
      ctx.textBaseline = "top";
      series.forEach((s, i) => {
        if (s.role === "context") return;
        const color = colors[i]!;
        if (s.baseline != null && Number.isFinite(s.baseline) && (scale === "linear" || s.baseline > 0)) {
          const y = u.valToPos(s.baseline, "y", true);
          if (y >= top && y <= top + h) {
            ctx.strokeStyle = withAlpha(color, 0.85);
            ctx.lineWidth = 1.25 * ratio;
            ctx.setLineDash([4 * ratio, 3 * ratio]);
            ctx.beginPath();
            ctx.moveTo(left, y);
            ctx.lineTo(left + width, y);
            ctx.stroke();
          }
        }
        if (s.cq != null && Number.isFinite(s.cq)) {
          const x = u.valToPos(s.cq, "x", true);
          if (x >= left && x <= left + width) {
            ctx.strokeStyle = color;
            ctx.lineWidth = 1.25 * ratio;
            ctx.setLineDash([2 * ratio, 2 * ratio]);
            ctx.beginPath();
            ctx.moveTo(x, top);
            ctx.lineTo(x, top + h);
            ctx.stroke();
            ctx.setLineDash([]);
            const text = `Cq ${fixed(s.cq, 1)}`;
            const tw = ctx.measureText(text).width;
            const tx = x + 4 * ratio + tw > left + width ? x - 4 * ratio - tw : x + 4 * ratio;
            const ty = top + 4 * ratio + idx[i]! * 15 * ratio;
            ctx.fillStyle = withAlpha(cssVar("--surface") || "#fff", 0.85);
            ctx.fillRect(tx - 2 * ratio, ty - 1 * ratio, tw + 4 * ratio, 14 * ratio);
            ctx.fillStyle = color;
            ctx.fillText(text, tx, ty);
          }
        }
      });
      ctx.restore();
    };

    const opts: uPlot.Options = {
      width: Math.max(160, el.clientWidth),
      height,
      pxAlign: 0,
      legend: { show: false },
      scales: {
        x: { time: false },
        y: scale === "log" ? { distr: 3, log: 10 } : { distr: 1 },
      },
      axes: [
        { ...axis, label: "Cycle", size: 40, labelSize: 18, values: (_u, splits) => splits.map((v) => String(v)) },
        { ...axis, label: yLabel, size: 64, labelSize: 18, values: (_u, splits) => splits.map(tick) },
      ],
      cursor: {
        points: { size: 6 },
        drag: { x: true, y: false, setScale: true },
      },
      series: [
        { label: "Cycle" },
        ...series.map((s, i) => ({
          label: s.label,
          stroke: s.role === "context" ? withAlpha(faint || colors[i]!, 0.75) : colors[i]!,
          width: s.role === "context" ? 1.25 : 2,
          points: { show: false },
          spanGaps: false,
        })),
      ],
      hooks: {
        draw: [drawMarkers],
        setCursor: [
          (u) => {
            const i = u.cursor.idx ?? null;
            if (i !== cursorRef.current) {
              cursorRef.current = i;
              setCursor(i);
            }
          },
        ],
      },
    };
    const u = new uPlot(opts, [aligned.x, ...aligned.ys] as uPlot.AlignedData, el);
    plot.current = u;
    const ro = new ResizeObserver(() => {
      const w = Math.max(160, el.clientWidth);
      if (w !== u.width) u.setSize({ width: w, height });
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      u.destroy();
      plot.current = null;
    };
  }, [series, aligned, scale, yLabel, height, theme]);

  const focus = series.map((s, i) => ({ s, i })).filter(({ s }) => s.role !== "context");
  const x = cursor != null ? aligned.x[cursor] : undefined;
  return (
    <div>
      <div ref={host} role="img" aria-label={summary} className="qp-curve w-full" style={{ minHeight: height }} />
      <p className="mt-1 min-h-5 font-mono text-[12px] text-muted tabular" aria-hidden="true">
        {x !== undefined ? (
          <>
            <span className="text-fg">Cycle {x}</span>
            {focus.slice(0, 6).map(({ s, i }) => (
              <span key={s.id} className="ml-3">
                {s.label.split(" · ")[0]} {fixed(aligned.ys[i]![cursor!], decimals)}
              </span>
            ))}
          </>
        ) : (
          <span className="font-sans">Point at the plot for the values at a cycle; drag across it to zoom, double-click to reset.</span>
        )}
      </p>
    </div>
  );
}
