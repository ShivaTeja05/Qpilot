/**
 * The dependency view: one gene's result at the top, flowing down to the two groups, to the
 * samples that move it most (circle area ∝ how much setting the sample aside moves the fold
 * change; colour: which way it pushes by being there; a double ring when it alone changes the
 * call; a warning mark when its wells show something unusual), to the selected sample's wells
 * (the gene's own well and each control-gene well) and the plates they sit on.
 *
 * Every position is layout; every number is the API's. Links draw in once (motion), and nothing
 * moves under `prefers-reduced-motion`. Samples and wells are buttons (Enter / Space); the
 * figure has a summary and a "View as table" alternative.
 */
import { linkVertical } from "d3-shape";
import { AnimatePresence, motion } from "motion/react";
import {
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { ChartFrame, LineSwatch } from "@/charts";
import { cn } from "@/lib/cn";
import { count, fixed } from "@/lib/format";
import { useReducedMotion } from "@/lib/hooks";
import { NumberCell, Table, TBody, TD, TH, THead, TR } from "@/ui";
import type { Sample, Trace, Well } from "./api";
import {
  CALL_WORD,
  SAMPLE_FLAG,
  WELL_FLAG,
  changeWords,
  effectPercent,
  push,
  radiusScale,
} from "./words";

const H = { result: 30, group: 128, sample: 232, more: 292, well: 368, plate: 464, height: 504 };
const MIN_WIDTH = 640;

type Point = [number, number];
const curve = linkVertical<{ source: Point; target: Point }, Point>()
  .source((d) => d.source)
  .target((d) => d.target);

function useWidth(fallback = 960) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setWidth(Math.max(MIN_WIDTH, Math.floor(el.clientWidth) || fallback));
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fallback]);
  return [ref, width] as const;
}

function short(text: string, n: number): string {
  return text.length > n ? `${text.slice(0, n - 1)}…` : text;
}

const unusualFlags = (s: Pick<Sample, "flags">) => s.flags.filter((f) => f !== "far_from_group");

const PAD = 56;
const GAP = 28;
const SPACING = 58; // between sample centres: the widest circle and its label never touch

/**
 * The samples drawn for one group: its most influential that fit the width, always with the
 * selected and the look-first sample (they replace the least influential shown).
 */
function pick(list: Sample[], cap: number, must: Set<string>): Sample[] {
  const top = list.slice(0, Math.max(1, cap));
  for (const s of list) {
    if (!must.has(s.unit) || top.includes(s)) continue;
    const drop = [...top].reverse().find((t) => !must.has(t.unit));
    if (drop) top.splice(top.indexOf(drop), 1);
    top.push(s);
  }
  return top.sort((x, y) => x.rank - y.rank);
}

/** How many samples of each group fit at this width, and which. */
export function drawnSamples(trace: Trace, selected: string | null, width: number): Sample[] {
  const half = (width - 2 * PAD - GAP) / 2;
  const cap = Math.max(2, Math.floor(half / SPACING) + 1);
  const must = new Set([selected, trace.look_first.unit].filter((u): u is string => Boolean(u)));
  const side = (x: "a" | "b") => trace.samples.filter((s) => s.side === x);
  return [...pick(side("a"), cap, must), ...pick(side("b"), cap, must)];
}

interface Layout {
  drawn: Sample[];
  samples: { s: Sample; x: number; r: number }[];
  groups: { side: "a" | "b"; x: number; label: string; n: number; others: number }[];
  wells: { w: Well; x: number }[];
  plates: { name: string; x: number; wells: number[] }[];
}

function layout(trace: Trace, selected: string | null, width: number): Layout {
  const drawn = drawnSamples(trace, selected, width);
  const chosen = trace.samples.find((s) => s.unit === selected) ?? null;
  const scale = radiusScale(trace.samples, 5, 17);
  const a = drawn.filter((s) => s.side === "a");
  const b = drawn.filter((s) => s.side === "b");
  const mid = width / 2;
  const place = (list: Sample[], lo: number, hi: number) => {
    // the most influential nearest the group's trunk, the rest alternating outwards
    const centre = (lo + hi) / 2;
    const step = list.length > 1 ? Math.min(64, (hi - lo) / (list.length - 1)) : 0;
    const offset = list.length % 2 ? 0 : step / 2;
    return list.map((s, i) => {
      const k = Math.ceil(i / 2) * (i % 2 ? -1 : 1);
      return { s, x: centre + k * step + offset, r: scale(s.d_log2fc) };
    });
  };
  const samples = [...place(a, PAD, mid - GAP / 2), ...place(b, mid + GAP / 2, width - PAD)];
  const n = (side: "a" | "b") => trace.samples.filter((s) => s.side === side).length;
  const groups = [
    {
      side: "a" as const,
      x: (PAD + mid - GAP / 2) / 2,
      label: trace.labels[0] ?? "",
      n: n("a"),
      others: n("a") - a.length,
    },
    {
      side: "b" as const,
      x: (mid + GAP / 2 + width - PAD) / 2,
      label: trace.labels[1] ?? "",
      n: n("b"),
      others: n("b") - b.length,
    },
  ];
  const ws = chosen?.wells ?? [];
  const wstep = ws.length > 1 ? Math.min(150, (width - 2 * PAD) / (ws.length - 1)) : 0;
  const w0 = mid - (wstep * (ws.length - 1)) / 2;
  const wells = ws.map((w, i) => ({ w, x: w0 + i * wstep }));
  const byPlate = new Map<string, number[]>();
  wells.forEach(({ w }, i) => byPlate.set(w.plate, [...(byPlate.get(w.plate) ?? []), i]));
  const plates = [...byPlate.entries()].map(([name, idx]) => ({
    name,
    wells: idx,
    x: idx.reduce((sum, i) => sum + wells[i]!.x, 0) / idx.length,
  }));
  return { drawn, samples, groups, wells, plates };
}

function pushTone(s: Pick<Sample, "d_log2fc">): string {
  const p = push(s);
  return p === "raises" ? "var(--up)" : p === "lowers" ? "var(--down)" : "var(--none)";
}

function sampleLabel(s: Sample, gene: string): string {
  const flags = unusualFlags(s).map((f) => SAMPLE_FLAG[f]?.word ?? f);
  return [
    `${s.unit} ${effectPercent(s.d_log2fc)}: sample ${s.unit}, ${s.group}.`,
    `Set aside, ${gene}'s fold change moves ${effectPercent(s.d_log2fc)}`,
    s.flips ? `and the call becomes ${CALL_WORD[s.call_without]}.` : "; the call stays.",
    flags.length ? `Unusual: ${flags.join(", ")}.` : "",
  ]
    .join(" ")
    .replace(" ;", ";");
}

/** What a well's chip shows: its gene and well, then its Cq. */
function wellLines(w: Well): [string, string] {
  const cq = w.cq != null ? `Cq ${fixed(w.cq, 1)}` : w.amplified ? "no Cq" : "no curve";
  return [`${short(w.gene, 8)} · ${w.well}`, `${cq}${w.role === "target" ? " · target" : ""}`];
}

function wellLabel(w: Well): string {
  const flags = w.flags.map((f) => WELL_FLAG[f]?.word ?? f);
  const [top, bottom] = wellLines(w);
  return [
    `${top} ${bottom}: the ${w.gene} well ${w.well} on plate ${w.plate}`,
    flags.length ? `flags: ${flags.join(", ")}` : "",
    "Open its curve and plate.",
  ]
    .filter(Boolean)
    .join(". ");
}

function onKeys(fn: () => void) {
  return (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fn();
    }
  };
}

export function Dependency({
  trace,
  selected,
  wellKey,
  onSample,
  onWell,
}: {
  trace: Trace;
  selected: string | null;
  wellKey: string | null;
  onSample: (unit: string) => void;
  onWell: (well: Well) => void;
}) {
  const reduced = useReducedMotion();
  const [ref, width] = useWidth();
  const [focus, setFocus] = useState<string | null>(null);
  const chosen = trace.samples.find((s) => s.unit === selected) ?? null;
  const L = useMemo(() => layout(trace, selected, width), [trace, selected, width]);
  const drawn = L.drawn;
  const gene = trace.gene;
  const call = trace.call;
  const top = Math.max(1e-12, ...trace.samples.map((s) => Math.abs(s.d_log2fc)));
  const draw = (delay: number) =>
    reduced
      ? { initial: false as const }
      : {
          initial: { pathLength: 0, opacity: 0 },
          animate: { pathLength: 1, opacity: 1 },
          transition: { duration: 0.45, delay, ease: "easeOut" as const },
        };
  const fade = (delay: number) =>
    reduced
      ? { initial: false as const }
      : { initial: { opacity: 0 }, animate: { opacity: 1 }, transition: { duration: 0.3, delay } };
  const appear = (delay: number) =>
    reduced
      ? { initial: false as const }
      : {
          initial: { opacity: 0, y: -6 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.18, delay, ease: "easeOut" as const },
        };
  const groupX = (side: string) => L.groups.find((g) => g.side === side)!.x;
  const chosenX = L.samples.find((p) => p.s.unit === selected)?.x ?? width / 2;
  const flips = trace.n_flip_single;
  const summary =
    `${gene}: ${CALL_WORD[call.conclusion]}, ${changeWords(call.log2fc)} in ${trace.labels[0]} than ${trace.labels[1]}. ` +
    `${count(trace.n_used)} samples; ${count(flips)} each change the call when set aside alone. ` +
    `The ones that move it most in each group are drawn (${count(drawn.length)})` +
    (chosen
      ? `; sample ${chosen.unit}'s ${count(chosen.wells.length)} wells are shown below it.`
      : ".");

  const legend = [
    { swatch: <Dot tone="var(--up)" />, label: "raises the fold change by being there" },
    { swatch: <Dot tone="var(--down)" />, label: "lowers it" },
    { swatch: <Dot tone="var(--none)" ring />, label: "alone changes the call" },
    { swatch: <WarnMark />, label: "something unusual in its wells" },
    {
      swatch: <LineSwatch tone="var(--line-strong)" />,
      label: "link width: how much it moves the result",
    },
  ];

  return (
    <ChartFrame
      summary={summary}
      legend={legend}
      table={() => <DependencyTable trace={trace} drawn={drawn} chosen={chosen} />}
      caption={
        <>
          Circle area: how much setting the sample aside alone moves {gene}&rsquo;s fold change
          (exact, from the engine). Click a sample to see its wells; click a well to open its curve
          and its plate.
        </>
      }
      live={focus ?? undefined}
    >
      <div ref={ref} className="overflow-x-auto">
        <svg
          width={width}
          height={H.height}
          viewBox={`0 0 ${width} ${H.height}`}
          className="block select-none"
          style={{ minWidth: MIN_WIDTH }}
        >
          {/* result → groups */}
          {L.groups.map((g) => (
            <motion.path
              key={`rg-${g.side}`}
              d={
                curve({ source: [width / 2, H.result + 52], target: [g.x, H.group - 18] }) ??
                undefined
              }
              fill="none"
              stroke="var(--line-strong)"
              strokeWidth={2}
              {...draw(0.05)}
            />
          ))}
          {/* groups → samples */}
          {L.samples.map(({ s, x, r }) => (
            <motion.path
              key={`gs-${s.unit}`}
              d={
                curve({ source: [groupX(s.side), H.group + 18], target: [x, H.sample - r] }) ??
                undefined
              }
              fill="none"
              stroke={pushTone(s)}
              strokeOpacity={selected === s.unit ? 0.9 : 0.45}
              strokeWidth={1 + 5 * (Math.abs(s.d_log2fc) / top)}
              {...draw(0.2)}
            />
          ))}
          {/* the selected sample → its wells → plates */}
          <AnimatePresence mode="wait">
            <motion.g
              key={selected ?? "none"}
              {...(reduced
                ? { initial: false }
                : {
                    initial: { opacity: 0 },
                    animate: { opacity: 1 },
                    exit: { opacity: 0 },
                    transition: { duration: 0.15 },
                  })}
            >
              {L.wells.map(({ w, x }) => {
                const off = w.flags.includes("reference_pull");
                return (
                  <motion.path
                    key={`sw-${w.key}`}
                    d={
                      curve({ source: [chosenX, H.sample + 24], target: [x, H.well - 20] }) ??
                      undefined
                    }
                    fill="none"
                    stroke={off ? "var(--warn)" : "var(--line-strong)"}
                    strokeWidth={off ? 2.5 : 1.25}
                    strokeDasharray={w.role === "target" ? undefined : "4 3"}
                    {...(w.role === "target" ? draw(0.35) : fade(0.35))}
                  />
                );
              })}
              {L.plates.map((p) =>
                p.wells.map((i) => (
                  <motion.path
                    key={`wp-${p.name}-${i}`}
                    d={
                      curve({
                        source: [L.wells[i]!.x, H.well + 20],
                        target: [p.x, H.plate - 12],
                      }) ?? undefined
                    }
                    fill="none"
                    stroke="var(--line)"
                    strokeWidth={1}
                    {...draw(0.5)}
                  />
                )),
              )}
              {L.wells.map(({ w, x }, i) => (
                <WellNode
                  key={w.key}
                  well={w}
                  x={x}
                  active={wellKey === w.key}
                  focused={focus === w.key}
                  delay={0.4 + 0.03 * i}
                  reduced={reduced}
                  onOpen={() => onWell(w)}
                  onFocus={() => setFocus(w.key)}
                  onBlur={() => setFocus(null)}
                />
              ))}
              {L.plates.map((p) => (
                <g key={`plate-${p.name}`} transform={`translate(${p.x},${H.plate})`}>
                  <title>{`Plate ${p.name}`}</title>
                  <rect
                    x={-58}
                    y={-12}
                    width={116}
                    height={24}
                    rx={6}
                    fill="var(--surface-sunken)"
                    stroke="var(--line)"
                  />
                  <text textAnchor="middle" dy="0.35em" fontSize={11} fill="var(--text-muted)">
                    {short(p.name, 18)}
                  </text>
                </g>
              ))}
              {chosen && !chosen.wells.length ? (
                <text
                  x={width / 2}
                  y={H.well}
                  textAnchor="middle"
                  fontSize={12}
                  fill="var(--text-muted)"
                >
                  Wells are listed for the most influential samples and for every unusual one.
                </text>
              ) : null}
            </motion.g>
          </AnimatePresence>

          {/* the result */}
          <g transform={`translate(${width / 2},${H.result})`}>
            <motion.g {...appear(0)}>
              <title>{`${gene}: ${CALL_WORD[call.conclusion]}, ${changeWords(call.log2fc)}`}</title>
              <rect
                x={-150}
                y={0}
                width={300}
                height={52}
                rx={12}
                fill="var(--surface)"
                stroke="var(--line-strong)"
                strokeWidth={1.5}
              />
              <text textAnchor="middle" y={21} fontSize={15} fontWeight={600} fill="var(--text)">
                {short(gene, 22)}
                <tspan
                  dx={8}
                  fill={
                    call.conclusion === "none" ? "var(--text-muted)" : `var(--${call.conclusion})`
                  }
                >
                  {call.conclusion === "up"
                    ? "▲ up"
                    : call.conclusion === "down"
                      ? "▼ down"
                      : "— no call"}
                </tspan>
              </text>
              <text textAnchor="middle" y={40} fontSize={12} fill="var(--text-muted)">
                {changeWords(call.log2fc)} · {count(call.n_a)} vs {count(call.n_b)} samples
              </text>
            </motion.g>
          </g>
          {/* the groups */}
          {L.groups.map((g, i) => (
            <g key={`group-${g.side}`} transform={`translate(${g.x},${H.group})`}>
              <motion.g {...appear(0.1 + 0.05 * i)}>
                <rect
                  x={-92}
                  y={-18}
                  width={184}
                  height={36}
                  rx={18}
                  fill="var(--surface-2)"
                  stroke="var(--line)"
                />
                <text
                  textAnchor="middle"
                  dy="0.35em"
                  fontSize={12.5}
                  fontWeight={600}
                  fill="var(--text)"
                >
                  {short(g.label, 16)}{" "}
                  <tspan fontWeight={400} fill="var(--text-muted)">
                    · {count(g.n)}
                  </tspan>
                </text>
              </motion.g>
            </g>
          ))}
          {/* how many more each group holds */}
          {L.groups.map((g) =>
            g.others > 0 ? (
              <g
                key={`more-${g.side}`}
                transform={`translate(${g.x},${H.more})`}
                aria-hidden="true"
              >
                <rect x={-104} y={-9} width={208} height={18} rx={9} fill="var(--surface)" />
                <text textAnchor="middle" dy="0.35em" fontSize={11} fill="var(--text-faint)">
                  {`+ ${count(g.others)} more, each moving it less`}
                </text>
              </g>
            ) : null,
          )}
          {/* the samples */}
          {L.samples.map(({ s, x, r }, i) => (
            <SampleNode
              key={s.unit}
              sample={s}
              gene={gene}
              x={x}
              r={r}
              active={selected === s.unit}
              focused={focus === s.unit}
              delay={0.25 + 0.02 * i}
              reduced={reduced}
              onOpen={() => onSample(s.unit)}
              onFocus={() => setFocus(s.unit)}
              onBlur={() => setFocus(null)}
            />
          ))}
        </svg>
      </div>
    </ChartFrame>
  );
}

function SampleNode({
  sample: s,
  gene,
  x,
  r,
  active,
  focused,
  delay,
  reduced,
  onOpen,
  onFocus,
  onBlur,
}: {
  sample: Sample;
  gene: string;
  x: number;
  r: number;
  active: boolean;
  focused: boolean;
  delay: number;
  reduced: boolean;
  onOpen: () => void;
  onFocus: () => void;
  onBlur: () => void;
}) {
  const tone = pushTone(s);
  const unusual = unusualFlags(s).length > 0;
  const label = sampleLabel(s, gene);
  return (
    <g
      transform={`translate(${x},${H.sample})`}
      role="button"
      tabIndex={0}
      aria-label={label}
      aria-pressed={active}
      onClick={onOpen}
      onKeyDown={onKeys(onOpen)}
      onFocus={onFocus}
      onBlur={onBlur}
      className="cursor-pointer outline-none"
    >
      <motion.g
        {...(reduced
          ? { initial: false }
          : {
              initial: { opacity: 0, scale: 0.6 },
              animate: { opacity: 1, scale: 1 },
              transition: { duration: 0.2, delay },
            })}
      >
        <title>{label}</title>
        {(active || focused) && (
          <circle r={r + 6} fill="none" stroke="var(--accent)" strokeWidth={2} />
        )}
        {s.flips && <circle r={r + 3} fill="none" stroke={tone} strokeWidth={1.25} />}
        <circle
          r={r}
          fill={tone}
          fillOpacity={active ? 0.5 : 0.22}
          stroke={tone}
          strokeWidth={1.5}
        />
        {unusual && (
          <g transform={`translate(${r * 0.75},${-r * 0.75})`}>
            <WarnShape />
          </g>
        )}
        <text
          aria-hidden="true"
          textAnchor="middle"
          y={r + 15}
          fontSize={11.5}
          fontWeight={active ? 600 : 500}
          fill="var(--text)"
        >
          {short(s.unit, 10)}{" "}
        </text>
        <text
          aria-hidden="true"
          textAnchor="middle"
          y={r + 28}
          fontSize={10.5}
          fill="var(--text-muted)"
          className="tabular"
        >
          {effectPercent(s.d_log2fc)}
        </text>
      </motion.g>
    </g>
  );
}

function WellNode({
  well: w,
  x,
  active,
  focused,
  delay,
  reduced,
  onOpen,
  onFocus,
  onBlur,
}: {
  well: Well;
  x: number;
  active: boolean;
  focused: boolean;
  delay: number;
  reduced: boolean;
  onOpen: () => void;
  onFocus: () => void;
  onBlur: () => void;
}) {
  const off = w.flags.includes("reference_pull");
  const odd = w.flags.length > 0;
  const label = wellLabel(w);
  return (
    <g
      transform={`translate(${x},${H.well})`}
      role="button"
      tabIndex={0}
      aria-label={label}
      aria-pressed={active}
      onClick={onOpen}
      onKeyDown={onKeys(onOpen)}
      onFocus={onFocus}
      onBlur={onBlur}
      className="cursor-pointer outline-none"
    >
      <motion.g
        {...(reduced
          ? { initial: false }
          : {
              initial: { opacity: 0, y: 6 },
              animate: { opacity: 1, y: 0 },
              transition: { duration: 0.18, delay },
            })}
      >
        <title>{label}</title>
        {(active || focused) && (
          <rect
            x={-58}
            y={-24}
            width={116}
            height={48}
            rx={10}
            fill="none"
            stroke="var(--accent)"
            strokeWidth={2}
          />
        )}
        <rect
          x={-52}
          y={-19}
          width={104}
          height={38}
          rx={7}
          fill={off ? "var(--warn-soft)" : "var(--surface)"}
          stroke={off ? "var(--warn)" : odd ? "var(--line-strong)" : "var(--line)"}
          strokeWidth={off ? 1.75 : 1}
        />
        <text
          aria-hidden="true"
          textAnchor="middle"
          y={-3}
          fontSize={11.5}
          fontWeight={600}
          fill="var(--text)"
        >
          {wellLines(w)[0]}{" "}
        </text>
        <text
          aria-hidden="true"
          textAnchor="middle"
          y={12}
          fontSize={10.5}
          fill="var(--text-muted)"
          className="tabular"
        >
          {wellLines(w)[1]}
        </text>
        {off && (
          <g transform="translate(46,-15)">
            <WarnShape />
          </g>
        )}
      </motion.g>
    </g>
  );
}

function WarnShape() {
  return (
    <g aria-hidden="true">
      <path d="M0,-6 L6,5 L-6,5 Z" fill="var(--warn)" stroke="var(--surface)" strokeWidth={1} />
      <path d="M0,-2.2 L0,1.4" stroke="var(--surface)" strokeWidth={1.4} strokeLinecap="round" />
      <circle cx={0} cy={3.2} r={0.75} fill="var(--surface)" />
    </g>
  );
}

function WarnMark() {
  return (
    <svg width="14" height="14" viewBox="-7 -7 14 14" aria-hidden="true">
      <WarnShape />
    </svg>
  );
}

function Dot({ tone, ring }: { tone: string; ring?: boolean }) {
  return (
    <svg width="14" height="14" viewBox="-7 -7 14 14" aria-hidden="true">
      {ring && <circle r={6} fill="none" stroke={tone} strokeWidth={1.25} />}
      <circle r={4} fill={tone} fillOpacity={0.3} stroke={tone} strokeWidth={1.5} />
    </svg>
  );
}

function DependencyTable({
  trace,
  drawn,
  chosen,
}: {
  trace: Trace;
  drawn: Sample[];
  chosen: Sample | null;
}): ReactNode {
  return (
    <div className="flex flex-col gap-4 p-3">
      <Table>
        <caption className="sr-only">The samples drawn, most influential first</caption>
        <THead>
          <TR>
            <TH>Sample</TH>
            <TH>Group</TH>
            <TH numeric>Set aside, fold change moves</TH>
            <TH>Call without it</TH>
            <TH>Unusual</TH>
          </TR>
        </THead>
        <TBody>
          {drawn.map((s) => (
            <TR key={s.unit}>
              <TD>{s.unit}</TD>
              <TD>{s.group}</TD>
              <TD numeric>
                <NumberCell>{effectPercent(s.d_log2fc)}</NumberCell>
              </TD>
              <TD className={cn(s.flips && "font-medium text-fg")}>
                {CALL_WORD[s.call_without]}
                {s.flips ? " (changes)" : ""}
              </TD>
              <TD>
                {unusualFlags(s)
                  .map((f) => SAMPLE_FLAG[f]?.word ?? f)
                  .join(", ") || "—"}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
      {chosen?.wells.length ? (
        <Table>
          <caption className="sr-only">{`Sample ${chosen.unit}'s wells behind ${trace.gene}`}</caption>
          <THead>
            <TR>
              <TH>Gene</TH>
              <TH>Plate</TH>
              <TH>Well</TH>
              <TH numeric>Cq</TH>
              <TH>Flags</TH>
            </TR>
          </THead>
          <TBody>
            {chosen.wells.map((w) => (
              <TR key={w.key}>
                <TD>{w.gene}</TD>
                <TD>{w.plate}</TD>
                <TD>{w.well}</TD>
                <TD numeric>
                  <NumberCell>{w.cq != null ? fixed(w.cq, 1) : "—"}</NumberCell>
                </TD>
                <TD>{w.flags.map((f) => WELL_FLAG[f]?.word ?? f).join(", ") || "—"}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      ) : null}
    </div>
  );
}
