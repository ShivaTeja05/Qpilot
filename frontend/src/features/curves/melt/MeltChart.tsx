/**
 * The melt chart (uPlot): −dF/dT by temperature for one or more wells, each well's counted peaks
 * marked at their Tm (the product filled, extra peaks hollow), and the assay's expected
 * temperature with the rule's tolerance as a band. Themed for light and dark, sized to its
 * container, with an accessible summary and "View as table". Drag to zoom; double-click to reset.
 */
import { LineChart, Table2 } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { SERIES_TOKENS } from "@/charts/curves/data";
import { cn } from "@/lib/cn";
import { count, fixed } from "@/lib/format";
import { useTheme } from "@/lib/theme";
import { NumberCell, Table, TBody, TD, TH, THead, TR } from "@/ui";
import { celsius } from "./words";

export interface MeltSeries {
  /** The well key (`plate/well`). */
  id: string;
  /** The legend label (`A1 · sample`). */
  label: string;
  temperature: readonly number[];
  derivative: readonly number[];
  peaks: readonly { tm: number; height: number; role: "main" | "extra" | "minor" }[];
}

export interface MeltBand {
  /** The expected melting temperature (°C) and the rule's tolerance either side. */
  center: number;
  tolerance: number;
  /** What the band is, for the legend ("the product of hmuY on this plate"). */
  label: string;
}

function cssVar(name: string): string {
  if (typeof document === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

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

/** Every series on the union of their temperatures (each well has its own readings). */
export function alignMelt(series: readonly MeltSeries[]): { x: number[]; ys: (number | null)[][] } {
  const xs = new Set<number>();
  for (const s of series) for (const t of s.temperature) if (Number.isFinite(t)) xs.add(t);
  const x = [...xs].sort((a, b) => a - b);
  const index = new Map(x.map((t, i) => [t, i]));
  const ys = series.map((s) => {
    const y: (number | null)[] = new Array<number | null>(x.length).fill(null);
    s.temperature.forEach((t, i) => {
      const at = index.get(t);
      const v = s.derivative[i];
      if (at !== undefined && v != null && Number.isFinite(v)) y[at] = v;
    });
    return y;
  });
  return { x, ys };
}

/** One sentence about the curves on show (the chart's accessible summary). */
export function meltSummary(series: readonly MeltSeries[], band: MeltBand | null): string {
  if (!series.length) return "No melt curve to show.";
  const parts = series.map((s) => {
    const peaks = s.peaks.filter((p) => p.role !== "minor");
    return peaks.length
      ? `${s.label}: ${peaks.map((p) => `${p.role === "main" ? "peak" : "extra peak"} at ${celsius(p.tm)}`).join(", ")}`
      : `${s.label}: no peak`;
  });
  const where = band
    ? `; ${band.label} at ${celsius(band.center)} ± ${fixed(band.tolerance, 1)} °C`
    : "";
  const n = series.length === 1 ? "one well" : `${count(series.length)} wells`;
  return `Melt curves (−dF/dT by temperature) of ${n}${where}. ${parts.join("; ")}.`;
}

function decimalsFor(series: readonly MeltSeries[]): number {
  let max = 0;
  for (const s of series)
    for (const v of s.derivative) if (Number.isFinite(v)) max = Math.max(max, Math.abs(v));
  return max >= 1000 ? 0 : max >= 100 ? 1 : max >= 10 ? 2 : max >= 1 ? 3 : 5;
}

export function MeltChart({
  series,
  band,
  label,
  height = 260,
  caption,
  className,
}: {
  series: readonly MeltSeries[];
  band: MeltBand | null;
  /** What these curves are, for the table caption ("Well A1 of plate P"). */
  label: string;
  height?: number;
  caption?: ReactNode;
  className?: string;
}) {
  const [asTable, setAsTable] = useState(false);
  const captionId = useId();
  const summary = meltSummary(series, band);
  const aligned = useMemo(() => alignMelt(series), [series]);
  const decimals = useMemo(() => decimalsFor(series), [series]);
  return (
    <figure
      className={cn("m-0 min-w-0", className)}
      aria-label={summary}
      aria-describedby={caption ? captionId : undefined}
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="min-w-[14rem] flex-1">
          {!asTable ? <Legend series={series} band={band} /> : null}
        </div>
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
      {asTable ? (
        <MeltTable series={series} aligned={aligned} label={label} decimals={decimals} />
      ) : series.length ? (
        <Plot
          series={series}
          band={band}
          aligned={aligned}
          height={height}
          decimals={decimals}
          summary={summary}
        />
      ) : (
        <div
          className="flex items-center justify-center rounded-lg border border-dashed border-line-strong text-[13px] text-muted"
          style={{ height }}
        >
          No melt curve to show.
        </div>
      )}
      {caption ? (
        <figcaption id={captionId} className="mt-2 text-[12px] leading-relaxed text-muted">
          {caption}
        </figcaption>
      ) : null}
    </figure>
  );
}

function Legend({ series, band }: { series: readonly MeltSeries[]; band: MeltBand | null }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
      {series.map((s, i) => {
        const product = s.peaks.find((p) => p.role === "main");
        return (
          <li key={s.id} className="inline-flex items-center gap-1.5 whitespace-nowrap">
            <svg width="16" height="10" aria-hidden="true">
              <line
                x1="1"
                x2="15"
                y1="5"
                y2="5"
                strokeWidth="2.5"
                strokeLinecap="round"
                style={{ stroke: `var(${SERIES_TOKENS[i % SERIES_TOKENS.length]})` }}
              />
            </svg>
            <span className="text-fg">{s.label}</span>
            <span className="font-mono text-faint tabular">
              {product ? `Tm ${celsius(product.tm)}` : "no peak"}
            </span>
          </li>
        );
      })}
      {band ? (
        <li className="inline-flex items-center gap-1.5">
          <svg width="16" height="10" aria-hidden="true">
            <rect
              x="1"
              y="0"
              width="14"
              height="10"
              rx="2"
              style={{ fill: "var(--accent-soft)" }}
            />
          </svg>
          <span>
            {band.label}: {celsius(band.center)} ± {fixed(band.tolerance, 1)} °C
          </span>
        </li>
      ) : null}
      {series.some((s) => s.peaks.some((p) => p.role === "extra")) ? (
        <li className="inline-flex items-center gap-1.5">
          <svg width="12" height="12" aria-hidden="true">
            <circle cx="6" cy="6" r="4" strokeWidth="1.5" fill="none" stroke="var(--text-muted)" />
          </svg>
          <span>Extra peak</span>
        </li>
      ) : null}
    </ul>
  );
}

function MeltTable({
  series,
  aligned,
  label,
  decimals,
}: {
  series: readonly MeltSeries[];
  aligned: ReturnType<typeof alignMelt>;
  label: string;
  decimals: number;
}) {
  if (!series.length) return <p className="text-[13px] text-muted">No melt curve to show.</p>;
  return (
    <div
      className="max-h-[420px] overflow-auto rounded-lg border border-line"
      tabIndex={0}
      role="region"
      aria-label={`${label}: −dF/dT by temperature`}
    >
      <Table caption={`${label}: −dF/dT by temperature`}>
        <THead>
          <TR>
            <TH numeric>Temperature (°C)</TH>
            {series.map((s) => (
              <TH key={s.id} numeric>
                {s.label}
              </TH>
            ))}
          </TR>
        </THead>
        <TBody>
          <TR>
            <TD className="text-muted">Peaks (°C)</TD>
            {series.map((s) => (
              <TD key={s.id} numeric>
                <NumberCell>
                  {s.peaks.length
                    ? s.peaks
                        .filter((p) => p.role !== "minor")
                        .map((p) => fixed(p.tm, 1))
                        .join(", ")
                    : "—"}
                </NumberCell>
              </TD>
            ))}
          </TR>
          {aligned.x.map((t, r) => (
            <TR key={t}>
              <TD numeric>
                <NumberCell>{fixed(t, 2)}</NumberCell>
              </TD>
              {aligned.ys.map((y, i) => (
                <TD key={series[i]!.id} numeric>
                  <NumberCell>{fixed(y[r], decimals)}</NumberCell>
                </TD>
              ))}
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

function Plot({
  series,
  band,
  aligned,
  height,
  decimals,
  summary,
}: {
  series: readonly MeltSeries[];
  band: MeltBand | null;
  aligned: ReturnType<typeof alignMelt>;
  height: number;
  decimals: number;
  summary: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();
  const [cursor, setCursor] = useState<number | null>(null);
  const cursorRef = useRef<number | null>(null);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const colors = series.map(
      (_s, i) => cssVar(SERIES_TOKENS[i % SERIES_TOKENS.length]!) || "#888",
    );
    const muted = cssVar("--text-muted");
    const line = cssVar("--line");
    const accent = cssVar("--accent") || "#0f766e";
    const surface = cssVar("--surface") || "#fff";
    const font = '12px "Inter Variable", ui-sans-serif, system-ui, sans-serif';
    const mono = '11px "JetBrains Mono Variable", ui-monospace, monospace';
    const axis = {
      stroke: muted,
      grid: { stroke: line, width: 1 },
      ticks: { stroke: line, width: 1, size: 4 },
      font: mono,
      labelFont: font,
    };

    const drawBand = (u: uPlot) => {
      if (!band) return;
      const ctx = u.ctx;
      const { left, top, width, height: h } = u.bbox;
      const x0 = u.valToPos(band.center - band.tolerance, "x", true);
      const x1 = u.valToPos(band.center + band.tolerance, "x", true);
      const xc = u.valToPos(band.center, "x", true);
      ctx.save();
      ctx.beginPath();
      ctx.rect(left, top, width, h);
      ctx.clip();
      ctx.fillStyle = withAlpha(accent, 0.1);
      ctx.fillRect(Math.min(x0, x1), top, Math.abs(x1 - x0), h);
      ctx.strokeStyle = withAlpha(accent, 0.7);
      ctx.lineWidth = 1 * uPlot.pxRatio;
      ctx.setLineDash([4 * uPlot.pxRatio, 3 * uPlot.pxRatio]);
      ctx.beginPath();
      ctx.moveTo(xc, top);
      ctx.lineTo(xc, top + h);
      ctx.stroke();
      ctx.restore();
    };

    const drawPeaks = (u: uPlot) => {
      const ctx = u.ctx;
      const ratio = uPlot.pxRatio;
      const { left, top, width, height: h } = u.bbox;
      ctx.save();
      ctx.beginPath();
      ctx.rect(left, top, width, h);
      ctx.clip();
      ctx.font = `${11 * ratio}px "JetBrains Mono Variable", ui-monospace, monospace`;
      ctx.textBaseline = "bottom";
      series.forEach((s, i) => {
        const color = colors[i]!;
        for (const p of s.peaks) {
          if (p.role === "minor") continue;
          const x = u.valToPos(p.tm, "x", true);
          const y = u.valToPos(p.height, "y", true);
          if (x < left || x > left + width) continue;
          ctx.beginPath();
          ctx.arc(x, y, 4 * ratio, 0, 2 * Math.PI);
          ctx.lineWidth = 1.5 * ratio;
          ctx.strokeStyle = color;
          if (p.role === "main") {
            ctx.fillStyle = color;
            ctx.fill();
          } else {
            ctx.fillStyle = surface;
            ctx.fill();
            ctx.stroke();
          }
          if (series.length <= 4) {
            // one label row per well at the top, so wells peaking together never overlap
            const text = `${fixed(p.tm, 1)}°`;
            const tw = ctx.measureText(text).width;
            const tx = Math.min(Math.max(x + 6 * ratio, left + 2 * ratio), left + width - tw - 2);
            const ty = top + (14 + i * 14) * ratio;
            ctx.fillStyle = withAlpha(surface, 0.85);
            ctx.fillRect(tx - 2 * ratio, ty - 12 * ratio, tw + 4 * ratio, 13 * ratio);
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
      scales: { x: { time: false }, y: { distr: 1 } },
      axes: [
        {
          ...axis,
          label: "Temperature (°C)",
          size: 40,
          labelSize: 18,
          values: (_u, splits) => splits.map((v) => String(Number(v.toPrecision(4)))),
        },
        {
          ...axis,
          label: "−dF/dT",
          size: 64,
          labelSize: 18,
          values: (_u, splits) => splits.map(tick),
        },
      ],
      cursor: { points: { size: 6 }, drag: { x: true, y: false, setScale: true } },
      series: [
        { label: "Temperature" },
        ...series.map((s, i) => ({
          label: s.label,
          stroke: colors[i]!,
          width: 2,
          points: { show: false },
          spanGaps: true,
        })),
      ],
      hooks: {
        drawClear: [drawBand],
        draw: [drawPeaks],
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
    const ro = new ResizeObserver(() => {
      const w = Math.max(160, el.clientWidth);
      if (w !== u.width) u.setSize({ width: w, height });
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      u.destroy();
    };
  }, [series, band, aligned, height, theme]);

  const t = cursor != null ? aligned.x[cursor] : undefined;
  return (
    <div>
      <div
        ref={host}
        role="img"
        aria-label={summary}
        className="qp-curve w-full"
        style={{ minHeight: height }}
      />
      <p className="mt-1 min-h-5 font-mono text-[12px] text-muted tabular" aria-hidden="true">
        {t !== undefined ? (
          <>
            <span className="text-fg">{celsius(t, 2)}</span>
            {series.slice(0, 6).map((s, i) => (
              <span key={s.id} className="ml-3">
                {s.label.split(" · ")[0]} {fixed(aligned.ys[i]![cursor!], decimals)}
              </span>
            ))}
          </>
        ) : (
          <span className="font-sans">
            Point at the plot for −dF/dT at a temperature; drag across it to zoom, double-click to
            reset.
          </span>
        )}
      </p>
    </div>
  );
}
