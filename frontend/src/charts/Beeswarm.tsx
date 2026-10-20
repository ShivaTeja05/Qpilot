/**
 * Your samples: each sample's normalised level (log2, relative to the comparison group's mean) as a
 * dot, one swarm per group, the group means as bars and the fold change between them. Late Cq,
 * non-detects and flagged wells have their own marks; samples whose removal alone changes the call
 * are ringed. Click (or Enter) a sample to open its well.
 */
import { useMemo, type ReactNode } from "react";
import { ChartFrame, type LegendItem } from "./core/ChartFrame";
import { DataTable, type Column } from "./core/DataTable";
import { FOLD_AXIS_BELOW, FoldAxis } from "./core/FoldAxis";
import { foldScale } from "./core/fold";
import { fmtFoldWords } from "./core/format";
import { GlyphMark } from "./core/Glyph";
import { useTip, usePointNav, useWidth } from "./core/hooks";
import { beeswarm } from "./core/layout";
import { Tooltip } from "./core/Tooltip";
import type { Mark } from "./core/encodings";

export interface SamplePoint {
  sample: string;
  /** The group key this sample belongs to (matches a {@link SampleGroup}). */
  group: string;
  /** log2 level relative to the comparison group's mean. */
  x: number;
  plate?: string;
  well?: string;
  cq?: string | null;
  late?: boolean;
  nondetect?: boolean;
  flagged?: boolean;
  /** Removing this sample alone changes the call. */
  carries?: boolean;
  /** The level in the source's words ("3.90× higher"). */
  valueText?: string;
}

export interface SampleGroup {
  key: string;
  label: string;
  n: number;
  missing?: number;
  /** The group's mean, log2, on the same scale as the points. */
  mean: number;
}

export interface BeeswarmProps {
  groups: SampleGroup[];
  points: SamplePoint[];
  /** The gap between the first two groups' means, in words ("3.32× higher"). */
  foldText?: string;
  /** The Cq above which a well counts as late (for the legend: "Cq above 35"). */
  lateCut?: string;
  lower?: string;
  higher?: string;
  summary: string;
  caption?: ReactNode;
  selected?: string | null;
  onSelectSample?: (p: SamplePoint) => void;
}

const TOP = 18;
const GROUP_TONES = ["var(--accent)", "var(--text-muted)", "var(--info)", "var(--warn)"];

function markFor(p: SamplePoint, gi: number): Mark {
  if (p.nondetect) return { shape: "cross", tone: "var(--warn)", label: "No Cq (non-detect)" };
  if (p.late) return { shape: "ring", tone: "var(--warn)", label: "Late Cq" };
  if (p.flagged) return { shape: "diamond", tone: "var(--v-check)", label: "Flagged by LinRegPCR" };
  return { shape: "circle", tone: GROUP_TONES[gi % GROUP_TONES.length]!, label: "A sample" };
}

interface Dot {
  p: SamplePoint;
  gi: number;
  x: number;
  y: number;
}

export function Beeswarm({
  groups,
  points,
  foldText,
  lateCut,
  lower,
  higher,
  summary,
  caption,
  selected,
  onSelectSample,
}: BeeswarmProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTip();
  const narrow = width < 560;
  const labelW = narrow ? 0 : Math.min(200, Math.round(width * 0.27));
  const rowH = narrow ? 128 : Math.max(100, Math.min(150, Math.round(width * 0.13)));
  const bandTop = narrow ? 34 : 6;
  const r = narrow ? 2.8 : 3.2;
  const fs = useMemo(
    () =>
      foldScale(
        points.map((p) => p.x).concat(groups.map((g) => g.mean)),
        0,
        labelW + 12,
        width - 14,
      ),
    [points, groups, labelW, width],
  );
  const bottom = TOP + rowH * groups.length;
  const height = bottom + FOLD_AXIS_BELOW + 2;

  const dots = useMemo<Dot[]>(() => {
    const out: Dot[] = [];
    groups.forEach((g, gi) => {
      const top = TOP + gi * rowH + bandTop;
      const half = (rowH - bandTop - 10) / 2;
      const centre = top + half;
      const mine = points.filter((p) => p.group === g.key);
      for (const b of beeswarm(mine, (p) => fs.x(p.x), r, half - r, 0.6))
        out.push({ p: b.item, gi, x: b.x, y: centre + b.dy });
    });
    return out;
  }, [groups, points, fs, rowH, bandTop, r]);
  const order = useMemo(() => [...dots].sort((a, b) => a.gi - b.gi || a.x - b.x), [dots]);
  const nav = usePointNav(order.length, (i) => onSelectSample?.(order[i]!.p));
  const active = nav.active != null ? order[nav.active] : null;

  const tipFor = (d: Dot) => {
    const g = groups[d.gi];
    return {
      title: `Sample ${d.p.sample}`,
      value: d.p.valueText ?? fmtFoldWords(d.p.x),
      lines: [
        g?.label,
        [d.p.plate && `plate ${d.p.plate}`, d.p.well && `well ${d.p.well}`]
          .filter(Boolean)
          .join(" · "),
        d.p.cq ? `Cq ${d.p.cq}` : d.p.nondetect ? "No Cq (non-detect)" : null,
        d.p.late ? `Cq above ${lateCut ?? "the late cut-off"}` : null,
        d.p.flagged ? "Flagged by LinRegPCR" : null,
        d.p.carries ? "Removing it alone changes the call" : null,
        onSelectSample ? "Click to open its well" : null,
      ],
    };
  };

  const has = (f: (p: SamplePoint) => boolean | undefined) => points.some((p) => f(p));
  const legend: LegendItem[] = [
    ...groups
      .slice(0, 4)
      .map((g, gi) => ({
        mark: { shape: "circle" as const, tone: GROUP_TONES[gi]! },
        label: g.label,
      })),
    ...(has((p) => p.late)
      ? [
          {
            mark: { shape: "ring" as const, tone: "var(--warn)" },
            label: `Cq above ${lateCut ?? "the late cut-off"}`,
          },
        ]
      : []),
    ...(has((p) => p.nondetect)
      ? [{ mark: { shape: "cross" as const, tone: "var(--warn)" }, label: "No Cq" }]
      : []),
    ...(has((p) => p.flagged)
      ? [{ mark: { shape: "diamond" as const, tone: "var(--v-check)" }, label: "Flagged well" }]
      : []),
    ...(has((p) => p.carries)
      ? [
          {
            swatch: (
              <svg width="14" height="14" aria-hidden="true">
                <circle cx="7" cy="7" r="5.5" fill="none" stroke="var(--text)" strokeWidth="1.6" />
              </svg>
            ),
            label: "Removing it alone changes the call",
          },
        ]
      : []),
    {
      swatch: (
        <svg width="10" height="14" aria-hidden="true">
          <line
            x1="5"
            x2="5"
            y1="1"
            y2="13"
            stroke="var(--text)"
            strokeWidth="3"
            strokeLinecap="round"
          />
        </svg>
      ),
      label: "Group mean",
    },
  ];

  const columns: Column<SamplePoint>[] = [
    { key: "sample", header: "Sample", cell: (p) => p.sample, sort: (p) => p.sample },
    {
      key: "group",
      header: "Group",
      cell: (p) => groups.find((g) => g.key === p.group)?.label ?? p.group,
      sort: (p) => p.group,
    },
    {
      key: "level",
      header: "Level",
      cell: (p) => p.valueText ?? fmtFoldWords(p.x),
      sort: (p) => p.x,
      numeric: true,
    },
    {
      key: "well",
      header: "Plate · well",
      cell: (p) => [p.plate, p.well].filter(Boolean).join(" · "),
      sort: (p) => `${p.plate}${p.well}`,
    },
    {
      key: "cq",
      header: "Cq",
      cell: (p) => p.cq ?? (p.nondetect ? "none" : ""),
      sort: (p) => (p.cq ? Number(p.cq) : null),
      numeric: true,
    },
    {
      key: "flags",
      header: "Notes",
      cell: (p) =>
        [
          p.late && "late Cq",
          p.nondetect && "no Cq",
          p.flagged && "flagged",
          p.carries && "removing it changes the call",
        ]
          .filter(Boolean)
          .join(", "),
    },
  ];

  const g0 = groups[0];
  const g1 = groups[1];
  return (
    <ChartFrame
      summary={summary}
      legend={legend}
      caption={caption}
      live={active ? `${tipFor(active).title}: ${tipFor(active).value}` : undefined}
      table={() => (
        <DataTable
          columns={columns}
          rows={points}
          rowKey={(p) => `${p.group}:${p.sample}`}
          onRowClick={onSelectSample}
          caption={summary}
        />
      )}
    >
      <div
        ref={ref}
        className="relative rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-focus"
        tabIndex={points.length ? 0 : -1}
        role="group"
        aria-label={`${summary} Use the arrow keys to move between samples${onSelectSample ? " and Enter to open one" : ""}.`}
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
          <FoldAxis scale={fs} top={TOP} bottom={bottom} lower={lower} higher={higher} />
          {groups.map((g, gi) => {
            const rowTop = TOP + gi * rowH;
            const half = (rowH - bandTop - 10) / 2;
            const centre = rowTop + bandTop + half;
            const meanX = fs.x(g.mean);
            const missing = g.missing ? ` · ${g.missing} without a value` : "";
            return (
              <g key={g.key}>
                {gi > 0 && <line x1={0} x2={width} y1={rowTop} y2={rowTop} stroke="var(--line)" />}
                {narrow ? (
                  <>
                    <text x={2} y={rowTop + 14} fontSize={12} fontWeight={600} fill="var(--text)">
                      {g.label}
                    </text>
                    <text x={2} y={rowTop + 28} fontSize={11} fill="var(--text-muted)">
                      {g.n} samples{missing}
                    </text>
                  </>
                ) : (
                  <>
                    <text x={0} y={centre - 2} fontSize={12} fontWeight={600} fill="var(--text)">
                      {g.label}
                    </text>
                    <text x={0} y={centre + 14} fontSize={11} fill="var(--text-muted)">
                      {g.n} samples{missing}
                    </text>
                  </>
                )}
                <line
                  x1={meanX}
                  x2={meanX}
                  y1={centre - half - 2}
                  y2={centre + half + 2}
                  stroke="var(--text)"
                  strokeWidth={3}
                  strokeLinecap="round"
                />
              </g>
            );
          })}
          {dots
            .slice()
            .sort((a, b) => Number(a.p.carries) - Number(b.p.carries))
            .map((d) => {
              const on = active === d || selected === d.p.sample;
              return (
                <g
                  key={`${d.p.group}:${d.p.sample}`}
                  className={onSelectSample ? "cursor-pointer" : undefined}
                  onPointerEnter={() => show(d.x, d.y, tipFor(d))}
                  onClick={onSelectSample ? () => onSelectSample(d.p) : undefined}
                >
                  <circle cx={d.x} cy={d.y} r={Math.max(5, r + 2)} fill="transparent" />
                  <GlyphMark
                    mark={markFor(d.p, d.gi)}
                    x={d.x}
                    y={d.y}
                    r={on ? r + 1.5 : r}
                    ring={false}
                    style={{
                      opacity: d.p.late || d.p.nondetect || d.p.flagged || d.p.carries ? 1 : 0.7,
                    }}
                  />
                  {d.p.carries && (
                    <circle
                      cx={d.x}
                      cy={d.y}
                      r={r + 3}
                      fill="none"
                      stroke="var(--text)"
                      strokeWidth={1.6}
                    />
                  )}
                  {on && (
                    <circle
                      cx={d.x}
                      cy={d.y}
                      r={r + 5}
                      fill="none"
                      stroke="var(--accent)"
                      strokeWidth={2}
                    />
                  )}
                </g>
              );
            })}
          {g0 && g1 && foldText && (
            <g aria-hidden="true">
              {(() => {
                const yb = TOP + rowH;
                const xa = fs.x(g1.mean);
                const xb = fs.x(g0.mean);
                const mid = (xa + xb) / 2;
                const w = foldText.length * 6.6 + 12;
                return (
                  <>
                    <line x1={xa} x2={xb} y1={yb} y2={yb} stroke="var(--text)" strokeWidth={1.5} />
                    <rect
                      x={mid - w / 2}
                      y={yb - 9}
                      width={w}
                      height={18}
                      rx={9}
                      fill="var(--surface)"
                      stroke="var(--line-strong)"
                    />
                    <text
                      x={mid}
                      y={yb + 4}
                      textAnchor="middle"
                      fontSize={11.5}
                      fontWeight={600}
                      fill="var(--text)"
                      className="tabular"
                    >
                      {foldText}
                    </text>
                  </>
                );
              })()}
            </g>
          )}
        </svg>
        <Tooltip
          tip={active ? { x: active.x, y: active.y, content: tipFor(active) } : tip}
          width={width}
        />
      </div>
    </ChartFrame>
  );
}
