/**
 * One choice at a time: a row per decision, a dot per option (every other choice as planned) on
 * the fold axis. The planned option is a diamond; common shortcuts are hollow; options that change
 * the call are ringed and counted beside the decision.
 */
import { useMemo, type ReactNode } from "react";
import { ChartFrame, LineSwatch, type LegendItem } from "./core/ChartFrame";
import { DataTable, type Column } from "./core/DataTable";
import { FOLD_AXIS_BELOW, FoldAxis } from "./core/FoldAxis";
import { foldScale } from "./core/fold";
import { fmtFoldLog2 } from "./core/format";
import { GlyphMark } from "./core/Glyph";
import { useTip, usePointNav, useWidth } from "./core/hooks";
import { beeswarm } from "./core/layout";
import { Tooltip } from "./core/Tooltip";
import { CALLS, TIER_WORDS, type CallKey } from "./core/encodings";

export interface ChoiceOption {
  label: string;
  /** prespecified | defensible | common_practice */
  tier: string;
  log2: number;
  call: CallKey;
  changesCall: boolean;
  planned: boolean;
  foldText?: string;
  callText?: string;
}

export interface ChoiceRow {
  id: string;
  name: string;
  options: ChoiceOption[];
}

export interface ChoiceDotPlotProps {
  decisions: ChoiceRow[];
  line: number;
  lineLabel?: string;
  lower?: string;
  higher?: string;
  summary: string;
  caption?: ReactNode;
}

const TOP = 26;

interface Flat {
  row: ChoiceRow;
  ri: number;
  o: ChoiceOption;
  x: number;
  y: number;
}

export function ChoiceDotPlot({ decisions, line, lineLabel, lower, higher, summary, caption }: ChoiceDotPlotProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTip();
  const narrow = width < 560;
  const labelW = narrow ? 0 : Math.min(230, Math.round(width * 0.32));
  const rowH = narrow ? 58 : 44;
  const fs = useMemo(
    () => foldScale(decisions.flatMap((d) => d.options.map((o) => o.log2)), line, labelW + 14, width - 14, 44, false),
    [decisions, line, labelW, width],
  );
  const bottom = TOP + rowH * decisions.length;
  const height = bottom + FOLD_AXIS_BELOW + 2;
  const r = 4.5;

  const flat = useMemo<Flat[]>(() => {
    const out: Flat[] = [];
    decisions.forEach((row, ri) => {
      const centre = TOP + ri * rowH + (narrow ? rowH - 18 : rowH / 2);
      const placed = beeswarm(row.options, (o) => fs.x(o.log2), r, narrow ? 12 : rowH / 2 - 7, 0.5);
      for (const p of placed) out.push({ row, ri, o: p.item, x: p.x, y: centre + p.dy });
    });
    return out;
  }, [decisions, fs, narrow, rowH]);
  const order = useMemo(() => [...flat].sort((a, b) => a.ri - b.ri || a.x - b.x), [flat]);
  const nav = usePointNav(order.length);
  const active = nav.active != null ? order[nav.active] : null;

  const tipFor = (f: Flat) => ({
    title: f.o.planned ? `Planned: ${f.o.label}` : f.o.label,
    value: f.o.foldText ?? fmtFoldLog2(f.o.log2),
    lines: [f.row.name, f.o.callText ?? CALLS[f.o.call].label, f.o.planned ? null : TIER_WORDS[f.o.tier] ?? f.o.tier, f.o.changesCall ? "Changes the call" : null],
  });

  const legend: LegendItem[] = [
    { mark: { shape: "diamond", tone: "var(--accent)" }, label: "Planned" },
    { mark: CALLS.up, label: "Up" },
    { mark: CALLS.down, label: "Down" },
    { mark: CALLS.none, label: "No call" },
    {
      swatch: (
        <svg width="14" height="14" aria-hidden="true">
          <circle cx="7" cy="7" r="4.5" fill="var(--surface)" stroke="var(--up)" strokeWidth="1.8" />
        </svg>
      ),
      label: "Common shortcut (hollow, in its call's colour)",
    },
    {
      swatch: (
        <svg width="14" height="14" aria-hidden="true">
          <circle cx="7" cy="7" r="5.5" fill="none" stroke="var(--text)" strokeWidth="1.6" />
        </svg>
      ),
      label: "Changes the call",
    },
    ...(line ? [{ swatch: <LineSwatch dashed />, label: lineLabel ?? "Call line" }] : []),
  ];

  const columns: Column<Flat>[] = [
    { key: "decision", header: "Decision", cell: (f) => f.row.name, sort: (f) => f.ri },
    { key: "option", header: "Option", cell: (f) => (f.o.planned ? `${f.o.label} (planned)` : f.o.label), sort: (f) => f.o.label },
    { key: "tier", header: "Kind", cell: (f) => TIER_WORDS[f.o.tier] ?? f.o.tier, sort: (f) => f.o.tier },
    { key: "fold", header: "Fold change", cell: (f) => f.o.foldText ?? fmtFoldLog2(f.o.log2), sort: (f) => f.o.log2, numeric: true },
    { key: "call", header: "Call", cell: (f) => f.o.callText ?? CALLS[f.o.call].label, sort: (f) => f.o.call },
    { key: "changes", header: "Changes the call", cell: (f) => (f.o.changesCall ? "yes" : "no"), sort: (f) => Number(f.o.changesCall) },
  ];

  return (
    <ChartFrame
      summary={summary}
      legend={legend}
      caption={caption}
      live={active ? `${tipFor(active).title}: ${tipFor(active).value}. ${active.row.name}.` : undefined}
      table={() => <DataTable columns={columns} rows={flat} rowKey={(f) => `${f.row.id}:${f.o.label}`} caption={summary} />}
    >
      <div
        ref={ref}
        className="relative rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-focus"
        tabIndex={flat.length ? 0 : -1}
        role="group"
        aria-label={`${summary} Use the arrow keys to read the options one by one.`}
        onKeyDown={nav.onKeyDown}
        onBlur={() => {
          nav.onBlur();
          hide();
        }}
      >
        <svg width={width} height={height} role="img" aria-label={summary} className="block overflow-visible" onPointerLeave={hide}>
          <FoldAxis scale={fs} top={TOP} bottom={bottom} line={line} lineLabel={lineLabel} lower={lower} higher={higher} />
          {decisions.map((row, ri) => {
            const centre = TOP + ri * rowH + (narrow ? rowH - 18 : rowH / 2);
            const xs = row.options.map((o) => fs.x(o.log2));
            const n = row.options.filter((o) => o.changesCall).length;
            const sub = n ? `${n} of ${row.options.length} options change the call` : "";
            return (
              <g key={row.id}>
                {ri > 0 && <line x1={0} x2={width} y1={TOP + ri * rowH} y2={TOP + ri * rowH} stroke="var(--line)" strokeOpacity={0.6} />}
                {narrow ? (
                  <text x={2} y={TOP + ri * rowH + 15} fontSize={12} fill="var(--text)" fontWeight={n ? 600 : 400} stroke="var(--surface)" strokeWidth={4} paintOrder="stroke">
                    {row.name}
                    {sub && (
                      <tspan fill="var(--warn)" fontWeight={400}>
                        {" · "}
                        {sub}
                      </tspan>
                    )}
                  </text>
                ) : (
                  <>
                    <text x={0} y={centre + (sub ? -2 : 4)} fontSize={12} fill="var(--text)" fontWeight={n ? 600 : 400} stroke="var(--surface)" strokeWidth={4} paintOrder="stroke">
                      {row.name}
                    </text>
                    {sub && (
                      <text x={0} y={centre + 12} fontSize={11} fill="var(--warn)" stroke="var(--surface)" strokeWidth={4} paintOrder="stroke">
                        {sub}
                      </text>
                    )}
                  </>
                )}
                {xs.length > 1 && (
                  <line x1={Math.min(...xs)} x2={Math.max(...xs)} y1={centre} y2={centre} stroke="var(--line)" strokeWidth={8} strokeLinecap="round" />
                )}
              </g>
            );
          })}
          {flat
            .slice()
            .sort((a, b) => Number(a.o.planned) - Number(b.o.planned))
            .map((f) => {
              const on = active === f;
              const hollow = f.o.tier === "common_practice";
              return (
                <g key={`${f.row.id}:${f.o.label}`} onPointerEnter={() => show(f.x, f.y, tipFor(f))}>
                  <circle cx={f.x} cy={f.y} r={9} fill="transparent" />
                  {f.o.planned ? (
                    <GlyphMark mark={{ shape: "diamond", tone: "var(--accent)" }} x={f.x} y={f.y} r={on ? 7 : 6} />
                  ) : hollow ? (
                    <circle cx={f.x} cy={f.y} r={on ? r + 1 : r - 0.5} fill="var(--surface)" stroke={CALLS[f.o.call].tone} strokeWidth={1.8} />
                  ) : (
                    <GlyphMark mark={CALLS[f.o.call]} x={f.x} y={f.y} r={on ? r + 1 : r} />
                  )}
                  {f.o.changesCall && <circle cx={f.x} cy={f.y} r={r + 3} fill="none" stroke="var(--text)" strokeWidth={1.6} />}
                  {on && <circle cx={f.x} cy={f.y} r={r + 6} fill="none" stroke="var(--accent)" strokeWidth={1.5} />}
                </g>
              );
            })}
        </svg>
        <Tooltip tip={active ? { x: active.x, y: active.y, content: tipFor(active) } : tip} width={width} />
      </div>
    </ChartFrame>
  );
}
