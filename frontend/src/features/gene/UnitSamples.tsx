/**
 * "Your samples" from the engine (no audit needed): each biological unit's relative amount of the
 * gene as a large dot, its technical replicate wells as small dots on its line, each group's mean
 * as a bar with its 95 % confidence interval as a band, and the fold change between the means
 * (GET …/genes/{gene}/units). A study with many units is drawn as the audit draws it, a beeswarm,
 * with each group's interval said under it. Click a unit (or one of its wells) to open its wells.
 */
import { X } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import {
  Beeswarm,
  ChartFrame,
  DataTable,
  GlyphMark,
  type Column,
  type LegendItem,
  type SamplePoint,
} from "@/charts";
import { FOLD_AXIS_BELOW, FoldAxis } from "@/charts/core/FoldAxis";
import { foldScale } from "@/charts/core/fold";
import { usePointNav, useTip, useWidth } from "@/charts/core/hooks";
import { localPoint, nearestIndex } from "@/charts/core/layout";
import { Tooltip } from "@/charts/core/Tooltip";
import { Badge, ErrorPanel, IconButton, KeyValues, LoadingBlock } from "@/ui";
import { cn } from "@/lib/cn";
import { count, fixed, plural } from "@/lib/format";
import { sideWords } from "./AuditParts";
import { Panel, Sentences } from "./Panel";
import {
  firstWell,
  unitLabel,
  wellState,
  type GeneUnits,
  type UnitGroup,
  type UnitPoint,
  type UnitWell,
} from "./units";

/** Up to this many units in a group, each unit gets its own line (lanes); more: a beeswarm. */
export const LANE_MAX = 16;
const GROUP_TONES = ["var(--accent)", "var(--text-muted)"];
const TOP = 18;
const HEAD = 24;

type Query<T> = { data?: T; error: unknown; isPending: boolean; refetch: () => unknown };

export function UnitSamples({
  units,
  selected,
  onSelect,
  carries,
  curve,
  note,
}: {
  units: Query<GeneUnits>;
  /** The selected unit (by name). */
  selected: string | null;
  onSelect: (unit: string | null) => void;
  /** Units the audit says carry the call (when it covers the gene). */
  carries?: ReadonlySet<string>;
  /** A well's curve, when a viewer can show it. */
  curve?: (well: UnitWell) => ReactNode;
  /** Said above the chart (why the audit's own chart is not shown). */
  note?: ReactNode;
}) {
  const data = units.data;
  const second = data?.groups.rest.label;
  return (
    <Panel
      id="gene-samples"
      title="Your samples"
      hint={
        second
          ? `Each biological unit's normalised value, relative to the mean of ${second}${data.replicates ? "; the small dots are its replicate wells" : ""}. Click a unit to open its wells.`
          : "Each biological unit's normalised value. Click a unit to open its wells."
      }
    >
      {note}
      {data ? (
        <>
          <UnitChart
            data={data}
            carries={carries}
            selected={selected}
            onSelect={(unit) => onSelect(unit)}
          />
          {selected && data.points.some((p) => p.unit === selected) ? (
            <UnitDetail
              key={selected}
              point={data.points.find((p) => p.unit === selected)!}
              data={data}
              carries={carries?.has(selected) ?? false}
              curve={curve}
              onClose={() => onSelect(null)}
            />
          ) : null}
        </>
      ) : units.error ? (
        <ErrorPanel
          compact
          error={units.error}
          title="Each unit's value could not be read"
          onRetry={() => void units.refetch()}
        />
      ) : (
        <LoadingBlock label="Reading each unit's value" lines={4} />
      )}
    </Panel>
  );
}

// ---- the chart ------------------------------------------------------------------------------------

function groupsOf(data: GeneUnits): [UnitGroup, UnitGroup] {
  return [data.groups.high, data.groups.rest];
}

function summaryOf(data: GeneUnits): string {
  const [a, b] = groupsOf(data);
  const reps = data.replicates
    ? ` Each unit is the mean of up to ${plural(data.most_wells, "replicate well")}.`
    : "";
  return `${data.gene} in ${plural(a.n, "unit")} of ${a.label} and ${plural(b.n, "unit")} of ${b.label}: ${data.fold}.${reps}`;
}

export function UnitChart({
  data,
  carries,
  selected,
  onSelect,
}: {
  data: GeneUnits;
  carries?: ReadonlySet<string>;
  selected: string | null;
  onSelect: (unit: string) => void;
}) {
  const [a, b] = groupsOf(data);
  const lanes = Math.max(a.n, b.n) <= LANE_MAX;
  const summary = summaryOf(data);
  const caption = (
    <>
      <Sentences items={data.how} className="text-[12px] text-muted" />
      {!lanes ? (
        <p className="mt-1.5">
          {[a, b]
            .filter((g) => g.mean_text)
            .map(
              (g) => `${g.label}: mean ${g.mean_text}${g.ci_text ? ` (95 % CI ${g.ci_text})` : ""}`,
            )
            .join(" · ")}
        </p>
      ) : null}
    </>
  );
  if (!lanes) {
    const points: SamplePoint[] = data.points.map((p) => {
      const one = p.wells.length === 1 ? p.wells[0] : undefined;
      return {
        sample: p.unit,
        group: p.group,
        x: p.x,
        plate: one?.plate,
        well: one?.well,
        cq: one?.cq ?? null,
        late: one?.late ?? false,
        nondetect: p.capped,
        flagged: p.wells.some((w) => w.flagged),
        carries: carries?.has(p.unit) ?? false,
        valueText: p.value,
      };
    });
    return (
      <Beeswarm
        groups={groupsOf(data).map((g, i) => ({
          key: i === 0 ? "high" : "rest",
          label: g.label,
          n: g.n,
          missing: g.missing,
          mean: g.mean ?? Number.NaN,
        }))}
        points={points}
        foldText={data.fold}
        lateCut={data.late_cut}
        {...sideWords(a.label)}
        summary={summary}
        caption={caption}
        selected={selected}
        onSelectSample={(p) => onSelect(p.sample)}
      />
    );
  }
  return (
    <ChartFrame
      summary={summary}
      legend={legendFor(data, carries)}
      caption={caption}
      table={() => (
        <DataTable
          columns={tableColumns(data, carries)}
          rows={data.points}
          rowKey={(p) => p.unit}
          onRowClick={(p) => onSelect(p.unit)}
          caption={summary}
        />
      )}
    >
      <Lanes data={data} carries={carries} selected={selected} onSelect={onSelect} />
    </ChartFrame>
  );
}

function legendFor(data: GeneUnits, carries?: ReadonlySet<string>): LegendItem[] {
  const [a, b] = groupsOf(data);
  const items: LegendItem[] = [
    { mark: { shape: "circle", tone: GROUP_TONES[0]! }, label: a.label },
    { mark: { shape: "circle", tone: GROUP_TONES[1]! }, label: b.label },
  ];
  if (data.replicates)
    items.push({
      swatch: (
        <svg width="14" height="14" aria-hidden="true">
          <circle cx="7" cy="7" r="3" fill="var(--surface)" stroke="var(--text-muted)" />
        </svg>
      ),
      label: "A replicate well",
    });
  if (data.points.some((p) => p.capped))
    items.push({
      mark: { shape: "cross", tone: "var(--warn)" },
      label: "Every well undetermined",
    });
  if (data.points.some((p) => p.wells.some((w) => w.late)))
    items.push({
      swatch: (
        <svg width="14" height="14" aria-hidden="true">
          <circle
            cx="7"
            cy="7"
            r="3"
            fill="var(--surface)"
            stroke="var(--warn)"
            strokeWidth="1.5"
          />
        </svg>
      ),
      label: `A well with Cq above ${data.late_cut}`,
    });
  if (carries && data.points.some((p) => carries.has(p.unit)))
    items.push({
      swatch: (
        <svg width="14" height="14" aria-hidden="true">
          <circle cx="7" cy="7" r="5.5" fill="none" stroke="var(--text)" strokeWidth="1.6" />
        </svg>
      ),
      label: "Removing it alone changes the call",
    });
  items.push({
    swatch: (
      <svg width="16" height="14" aria-hidden="true">
        <rect x="1" y="2" width="14" height="10" rx="2" fill="var(--text-muted)" opacity="0.18" />
        <line x1="8" x2="8" y1="1" y2="13" stroke="var(--text)" strokeWidth="3" />
      </svg>
    ),
    label: "Group mean and its 95 % CI",
  });
  return items;
}

function wellsText(p: UnitPoint): string {
  return p.wells
    .map((w) => `${w.well} ${w.cq ?? "no Cq"}${w.state === "used" ? "" : ` (${wellState(w)})`}`)
    .join(", ");
}

function tableColumns(data: GeneUnits, carries?: ReadonlySet<string>): Column<UnitPoint>[] {
  const [a, b] = groupsOf(data);
  return [
    { key: "unit", header: "Unit", cell: (p) => unitLabel(p), sort: (p) => p.unit },
    {
      key: "group",
      header: "Group",
      cell: (p) => (p.group === "high" ? a.label : b.label),
      sort: (p) => p.group,
    },
    { key: "level", header: "Level", cell: (p) => p.value, sort: (p) => p.x, numeric: true },
    {
      key: "used",
      header: "Wells used",
      cell: (p) => `${count(p.n_wells)} of ${count(p.wells.length)}`,
      sort: (p) => p.n_wells,
      numeric: true,
    },
    {
      key: "spread",
      header: "Cq spread",
      cell: (p) => (p.cq_range == null ? "" : `${fixed(p.cq_range, 2)} cycles`),
      sort: (p) => p.cq_range,
      numeric: true,
    },
    { key: "wells", header: "Wells (Cq)", cell: wellsText },
    {
      key: "notes",
      header: "Notes",
      cell: (p) =>
        [
          p.capped && "every well undetermined",
          p.wells.some((w) => w.flagged) && "a flagged well",
          carries?.has(p.unit) && "removing it changes the call",
        ]
          .filter(Boolean)
          .join(", "),
    },
  ];
}

interface Mark {
  kind: "unit" | "well";
  point: UnitPoint;
  well?: UnitWell;
  gi: number;
  x: number;
  y: number;
}

function Lanes({
  data,
  carries,
  selected,
  onSelect,
}: {
  data: GeneUnits;
  carries?: ReadonlySet<string>;
  selected: string | null;
  onSelect: (unit: string) => void;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTip();
  const [hover, setHover] = useState(-1);
  const narrow = width < 560;
  const groups = useMemo(() => groupsOf(data), [data]);
  const most = Math.max(groups[0].n, groups[1].n);
  const lane = most > 8 ? 16 : 20;
  const labelW = narrow ? 0 : Math.min(180, Math.round(width * 0.24));
  const r = narrow ? 3.6 : 4.4;

  const byGroup = useMemo(
    () =>
      (["high", "rest"] as const).map((key) =>
        data.points.filter((p) => p.group === key).sort((p, q) => q.x - p.x),
      ),
    [data.points],
  );
  const fs = useMemo(() => {
    const values: number[] = [];
    for (const p of data.points) {
      values.push(p.x);
      for (const w of p.wells) if (w.x != null) values.push(w.x);
    }
    for (const g of groups) {
      if (g.mean != null) values.push(g.mean);
      if (g.ci) values.push(...g.ci);
    }
    return foldScale(values, 0, labelW + 12, width - 14);
  }, [data.points, groups, labelW, width]);

  // block tops: a heading row, then one lane per unit
  const { blocks, tops } = useMemo(() => {
    const sizes = byGroup.map((units) => HEAD + Math.max(1, units.length) * lane + 8);
    return { blocks: sizes, tops: [TOP, TOP + sizes[0]!] };
  }, [byGroup, lane]);
  const bottom = TOP + blocks[0]! + blocks[1]!;
  const height = bottom + FOLD_AXIS_BELOW + 2;

  const marks = useMemo<Mark[]>(() => {
    const out: Mark[] = [];
    byGroup.forEach((units, gi) => {
      units.forEach((p, li) => {
        const y = tops[gi]! + HEAD + li * lane + lane / 2;
        out.push({ kind: "unit", point: p, gi, x: fs.x(p.x), y });
        for (const w of p.wells)
          if (w.x != null) out.push({ kind: "well", point: p, well: w, gi, x: fs.x(w.x), y });
      });
    });
    return out;
  }, [byGroup, fs, tops, lane]);
  const unitMarks = useMemo(() => marks.filter((m) => m.kind === "unit"), [marks]);
  const nav = usePointNav(unitMarks.length, (i) => onSelect(unitMarks[i]!.point.unit));
  const active = nav.active != null ? unitMarks[nav.active] : null;

  const tipFor = (m: Mark) => {
    const g = groups[m.gi]!;
    if (m.kind === "well" && m.well) {
      const w = m.well;
      return {
        title: `Well ${w.well} of ${m.point.unit}`,
        value: w.value ?? "",
        lines: [
          `plate ${w.plate}`,
          w.cq ? `Cq ${w.cq}` : "No Cq",
          w.late ? `Cq above ${data.late_cut}` : null,
          w.flagged ? "Flagged by LinRegPCR" : null,
          "Click to open the unit's wells",
        ],
      };
    }
    const p = m.point;
    return {
      title: `Unit ${unitLabel(p)}`,
      value: p.value,
      lines: [
        g.label,
        data.replicates
          ? `the mean of ${plural(p.n_wells, "well")}${p.cq_range != null ? `, Cq spread ${fixed(p.cq_range, 2)} cycles` : ""}`
          : null,
        p.capped ? "Every well undetermined: set to the lowest amount detected" : null,
        carries?.has(p.unit) ? "Removing it alone changes the call" : null,
        "Click to open its wells",
      ],
    };
  };

  const [g0, g1] = groups;
  const maxChars = Math.max(6, Math.floor((labelW - 8) / 6.4));
  const short = (s: string) => (s.length > maxChars ? `${s.slice(0, maxChars - 1)}…` : s);
  return (
    <div
      ref={ref}
      className="relative rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-focus"
      tabIndex={unitMarks.length ? 0 : -1}
      role="group"
      aria-label={`${summaryOf(data)} Use the arrow keys to move between units and Enter to open one.`}
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
        aria-label={summaryOf(data)}
        className={cn("block overflow-visible", hover >= 0 && "cursor-pointer")}
        onPointerLeave={() => {
          setHover(-1);
          hide();
        }}
        onPointerMove={(e) => {
          const { x, y } = localPoint(e);
          const i = nearestIndex(marks, x, y, 9);
          setHover(i);
          if (i >= 0) show(marks[i]!.x, marks[i]!.y, tipFor(marks[i]!));
          else hide();
        }}
        onClick={(e) => {
          const { x, y } = localPoint(e);
          const i = nearestIndex(marks, x, y, 9);
          if (i >= 0) onSelect(marks[i]!.point.unit);
        }}
      >
        <FoldAxis scale={fs} top={TOP} bottom={bottom} {...sideWords(g0.label)} />
        {groups.map((g, gi) => {
          const top = tops[gi]!;
          const laneTop = top + HEAD;
          const laneBottom = top + blocks[gi]! - 8;
          const tone = GROUP_TONES[gi]!;
          const missing = g.missing ? ` · ${g.missing} without a value` : "";
          return (
            <g key={gi}>
              {gi > 0 && <line x1={0} x2={width} y1={top} y2={top} stroke="var(--line)" />}
              <text x={2} y={top + 15} fontSize={12} fontWeight={600} fill="var(--text)">
                {g.label}
                <tspan fontWeight={400} fill="var(--text-muted)">
                  {` · ${plural(g.n, "unit")}${missing}`}
                </tspan>
              </text>
              {g.ci && g.ci.length === 2 && (
                <rect
                  x={fs.x(g.ci[0]!)}
                  width={Math.max(1, fs.x(g.ci[1]!) - fs.x(g.ci[0]!))}
                  y={laneTop - 2}
                  height={laneBottom - laneTop + 4}
                  rx={3}
                  fill={tone}
                  opacity={0.12}
                />
              )}
              {g.mean != null && (
                <line
                  x1={fs.x(g.mean)}
                  x2={fs.x(g.mean)}
                  y1={laneTop - 4}
                  y2={laneBottom + 4}
                  stroke="var(--text)"
                  strokeWidth={3}
                  strokeLinecap="round"
                />
              )}
              {byGroup[gi]!.map((p, li) => {
                const y = laneTop + li * lane + lane / 2;
                const xs = p.wells.flatMap((w) => (w.x == null ? [] : [fs.x(w.x)]));
                return (
                  <g key={p.unit}>
                    {!narrow && (
                      <text
                        x={labelW}
                        y={y + 4}
                        textAnchor="end"
                        fontSize={11}
                        fill="var(--text-muted)"
                      >
                        {short(p.unit)}
                      </text>
                    )}
                    {xs.length > 1 && (
                      <line
                        x1={Math.min(...xs)}
                        x2={Math.max(...xs)}
                        y1={y}
                        y2={y}
                        stroke={tone}
                        strokeWidth={1.5}
                        opacity={0.55}
                      />
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}
        {marks
          .filter((m) => m.kind === "well")
          .map((m) => (
            <circle
              key={`${m.point.unit}:${m.well!.plate}/${m.well!.well}`}
              cx={m.x}
              cy={m.y}
              r={2.6}
              fill="var(--surface)"
              stroke={m.well!.late ? "var(--warn)" : GROUP_TONES[m.gi]}
              strokeWidth={m.well!.late ? 1.6 : 1.2}
            />
          ))}
        {unitMarks.map((m) => {
          const on = active === m || selected === m.point.unit || marks[hover]?.point === m.point;
          const carried = carries?.has(m.point.unit) ?? false;
          return (
            <g key={m.point.unit}>
              <GlyphMark
                mark={
                  m.point.capped
                    ? { shape: "cross", tone: "var(--warn)" }
                    : { shape: "circle", tone: GROUP_TONES[m.gi]! }
                }
                x={m.x}
                y={m.y}
                r={on ? r + 1.4 : r}
                ring={false}
              />
              {carried && (
                <circle
                  cx={m.x}
                  cy={m.y}
                  r={r + 3}
                  fill="none"
                  stroke="var(--text)"
                  strokeWidth={1.6}
                />
              )}
              {on && (
                <circle
                  cx={m.x}
                  cy={m.y}
                  r={r + 5}
                  fill="none"
                  stroke="var(--accent)"
                  strokeWidth={2}
                />
              )}
            </g>
          );
        })}
        {g0.mean != null && g1.mean != null && (
          <g aria-hidden="true">
            {(() => {
              const yb = tops[1]!;
              const xa = fs.x(g1.mean);
              const xb = fs.x(g0.mean);
              const mid = (xa + xb) / 2;
              const w = data.fold.length * 6.6 + 12;
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
                    {data.fold}
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
      <p className="sr-only" aria-live="polite">
        {active ? `${tipFor(active).title}: ${tipFor(active).value}` : ""}
      </p>
    </div>
  );
}

// ---- one unit ---------------------------------------------------------------------------------------

function detailRows(point: UnitPoint, second: string): [ReactNode, ReactNode][] {
  const rows: [ReactNode, ReactNode][] = [
    [`Value, relative to ${second}'s mean`, point.value],
    ["Wells used", `${count(point.n_wells)} of ${count(point.wells.length)}`],
  ];
  if (point.cq_range != null)
    rows.push(["Cq spread of the used wells", `${fixed(point.cq_range, 2)} cycles`]);
  return rows;
}

export function UnitDetail({
  point,
  data,
  carries,
  curve,
  onClose,
}: {
  point: UnitPoint;
  data: GeneUnits;
  carries: boolean;
  curve?: (well: UnitWell) => ReactNode;
  onClose: () => void;
}) {
  const [shown, setShown] = useState<UnitWell | undefined>(() => firstWell(point));
  const group = point.group === "high" ? data.groups.high : data.groups.rest;
  const second = data.groups.rest.label;
  const flags = [
    carries ? (
      <Badge key="carries" tone="warn">
        Leaving it out changes the call
      </Badge>
    ) : null,
    point.capped ? (
      <Badge key="capped" tone="warn">
        Every well undetermined: set to the lowest amount detected
      </Badge>
    ) : null,
  ].filter(Boolean);
  return (
    <section
      aria-label={`Unit ${point.unit}`}
      className="mt-4 rounded-lg border border-line-strong bg-surface-2 p-3"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-fg">Unit {unitLabel(point)}</h3>
          <p className="text-xs text-muted">{group.label}</p>
        </div>
        <IconButton size="sm" variant="ghost" label="Close the unit" onClick={onClose}>
          <X />
        </IconButton>
      </div>
      {flags.length ? <div className="mt-2 flex flex-wrap gap-1.5">{flags}</div> : null}
      <KeyValues className="mt-3" rows={detailRows(point, second)} />
      <table className="mt-3 w-full text-left text-[13px]">
        <caption className="sr-only">The wells of unit {point.unit}</caption>
        <thead className="text-xs text-muted">
          <tr>
            <th scope="col" className="py-1 pr-2 font-medium">
              Well
            </th>
            <th scope="col" className="py-1 pr-2 font-medium">
              Cq
            </th>
            <th scope="col" className="py-1 pr-2 font-medium">
              Value
            </th>
            <th scope="col" className="py-1 pr-2 font-medium">
              Counts
            </th>
            {curve ? <th className="sr-only">Curve</th> : null}
          </tr>
        </thead>
        <tbody>
          {point.wells.map((w) => (
            <tr key={`${w.plate}/${w.well}`} className="border-t border-line">
              <td className="py-1 pr-2 font-mono">{w.well}</td>
              <td className="py-1 pr-2 tabular">
                {w.cq ?? "none"}
                {w.late ? <span className="ml-1 text-warn">late</span> : null}
              </td>
              <td className="py-1 pr-2 tabular">{w.value ?? "–"}</td>
              <td className="py-1 pr-2 text-muted">
                {wellState(w)}
                {w.flagged ? ", flagged by LinRegPCR" : ""}
              </td>
              {curve ? (
                <td className="py-1 text-right">
                  <button
                    type="button"
                    aria-pressed={shown === w}
                    onClick={() => setShown(w)}
                    className="rounded-md px-1.5 text-xs text-accent underline-offset-4 hover:underline aria-pressed:font-semibold"
                  >
                    Curve
                  </button>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
      {curve && shown ? <div className="mt-3">{curve(shown)}</div> : null}
      {point.wells.length > 1 ? (
        <p className="mt-2 text-xs text-muted">
          The unit's value ({point.value}) is the mean of its used wells' values; the groups compare
          units, never wells.
        </p>
      ) : null}
    </section>
  );
}
