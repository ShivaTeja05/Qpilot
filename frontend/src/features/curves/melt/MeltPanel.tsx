/**
 * Melt curves in the page: the chosen wells' −dF/dT with their peaks and the assay's expected
 * melting temperature (the Run Gate's rule G-MELT), each well's call in words, and the plate's
 * assays. `MeltPanel` is the Curves stage's card (the wells picked on the plate); `MeltCurves`
 * shows some wells' melt curves anywhere (a G-MELT check in Controls). A melt peak is a
 * product's class, never a group: nothing here names a group.
 */
import { Thermometer } from "lucide-react";
import { useMemo } from "react";
import { cn } from "@/lib/cn";
import { count, fixed, percent, plural } from "@/lib/format";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorPanel,
  LoadingBlock,
  NumberCell,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/ui";
import {
  MAX_MELT_WELLS,
  useMelt,
  type MeltAssay,
  type MeltCall,
  type MeltSource,
  type MeltView,
  type MeltWell,
} from "./api";
import { MeltChart, type MeltBand, type MeltSeries } from "./MeltChart";
import { STATUS_TONE, STATUS_WORD, assaySentence, celsius, delta } from "./words";

const GLYPH = { ok: "●", warn: "▲", danger: "✕", neutral: "–" } as const;

/** The wells' curves as chart series (the route's numbers as they are). */
export function meltSeries(wells: readonly MeltWell[]): MeltSeries[] {
  return wells.map((w) => ({
    id: w.key,
    label: `${w.well} · ${w.sample}`,
    temperature: w.temperature,
    derivative: w.derivative,
    peaks: (w.peaks ?? []).map((p) => ({ tm: p.tm, height: p.height, role: p.role })),
  }));
}

/** The expected-Tm band when every well shown is of one assay that has one. */
export function bandOf(view: MeltView, wells: readonly MeltWell[]): MeltBand | null {
  const targets = new Set(wells.map((w) => w.target));
  if (targets.size !== 1) return null;
  const [target] = [...targets];
  const assay = view.assays.find((a) => a.target === target);
  if (!assay || assay.expected_tm == null) return null;
  return {
    center: assay.expected_tm,
    tolerance: view.params.tm_tolerance_c,
    label: assay.expected_source === "file" ? "Declared product Tm" : "This assay's product",
  };
}

export function CallChip({ call }: { call: Pick<MeltCall, "status" | "status_text"> }) {
  const tone = STATUS_TONE[call.status];
  return (
    <Badge tone={tone === "danger" ? "danger" : tone} title={call.status_text}>
      <span aria-hidden>{GLYPH[tone]}</span>
      {STATUS_WORD[call.status]}
    </Badge>
  );
}

function extraText(w: MeltWell): string {
  const extra = (w.peaks ?? []).filter((p) => p.role === "extra");
  if (!extra.length) return "—";
  return extra.map((p) => `${celsius(p.tm)} (${percent(p.share)})`).join(", ");
}

/** One row per well: its call, its product, how far from the expected Tm, its extra peaks. */
export function MeltWellsTable({
  wells,
  caption,
}: {
  wells: readonly MeltWell[];
  caption: string;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <Table caption={caption}>
        <THead>
          <TR>
            <TH>Well</TH>
            <TH>Sample</TH>
            <TH>Call</TH>
            <TH numeric>Main peak</TH>
            <TH numeric>From expected</TH>
            <TH numeric>Extra peaks (share)</TH>
          </TR>
        </THead>
        <TBody>
          {wells.map((w) => (
            <TR key={`${w.key}|${w.target}`}>
              <TD className="font-mono">{w.well}</TD>
              <TD>
                {w.sample}
                <span className="ml-1 text-[12px] text-muted">({w.sample_type})</span>
              </TD>
              <TD>
                <CallChip call={w} />
              </TD>
              <TD numeric>
                <NumberCell>{celsius(w.main_tm)}</NumberCell>
              </TD>
              <TD numeric>
                <NumberCell>{delta(w.offset_c)}</NumberCell>
              </TD>
              <TD numeric>
                <NumberCell>{extraText(w)}</NumberCell>
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

function AssayLines({ view }: { view: MeltView }) {
  if (!view.assays.length) return null;
  return (
    <ul className="flex flex-col gap-1.5 text-[13px]" aria-label="Assays on this plate">
      {view.assays.map((a: MeltAssay) => (
        <li key={a.target} className="leading-relaxed">
          <span className="font-medium text-fg">{a.target}</span>{" "}
          <span className="text-muted">
            ({plural(a.n_wells, "well")} with a melt curve
            {a.flagged.length ? `, ${count(a.flagged.length)} flagged` : ""}):
          </span>{" "}
          <span className="text-fg">{assaySentence(a, view.params.tm_tolerance_c)}</span>
        </li>
      ))}
    </ul>
  );
}

/** The wells G-MELT points at on the plate, as buttons that show their melt curves. */
function FlaggedWells({
  calls,
  onPick,
  chosen,
}: {
  calls: readonly MeltCall[];
  onPick?: (wells: string[]) => void;
  chosen: readonly string[];
}) {
  const flagged = calls.filter((c) => c.flagged);
  if (!flagged.length) {
    return (
      <p className="text-[13px] text-muted">
        G-MELT points at no well on this plate: every judged well melts as expected.
      </p>
    );
  }
  const wells = [...new Set(flagged.map((c) => c.well))];
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        <span className="text-fg">
          G-MELT points at {plural(wells.length, "well")} on this plate.
        </span>
        {onPick ? (
          <button
            type="button"
            onClick={() => onPick(wells.slice(0, MAX_MELT_WELLS))}
            className="font-medium text-accent hover:underline"
          >
            Show {wells.length > MAX_MELT_WELLS ? `the first ${MAX_MELT_WELLS}` : "them"}
          </button>
        ) : null}
      </div>
      <ul className="flex flex-wrap gap-1" aria-label="Wells G-MELT points at">
        {flagged.map((c) => (
          <li key={`${c.key}|${c.target}`}>
            {onPick ? (
              <button
                type="button"
                aria-pressed={chosen.includes(c.well)}
                onClick={() => onPick([c.well])}
                title={c.status_text}
                className={cn(
                  "rounded border border-line bg-surface px-1.5 font-mono text-[11px] text-fg hover:border-line-strong",
                  chosen.includes(c.well) && "ring-2 ring-accent",
                )}
              >
                {c.well} · {STATUS_WORD[c.status]}
              </button>
            ) : (
              <span className="rounded border border-line bg-surface px-1.5 font-mono text-[11px] text-fg">
                {c.well} · {STATUS_WORD[c.status]}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Some wells' melt curves with their calls (no card): the chart, then a row per well. */
export function MeltCurves({
  view,
  label,
  height,
}: {
  view: MeltView;
  label: string;
  height?: number;
}) {
  const series = useMemo(() => meltSeries(view.wells), [view.wells]);
  const band = useMemo(() => bandOf(view, view.wells), [view]);
  if (!view.wells.length) return null;
  return (
    <div className="flex flex-col gap-3">
      <MeltChart
        series={series}
        band={band}
        label={label}
        height={height}
        caption={`${view.caveat} Thresholds: pack ${view.pack}, rule G-MELT (product within ±${fixed(view.params.tm_tolerance_c, 1)} °C; an extra peak counts from ${percent(view.params.extra_peak_share)} of a well's peaks).`}
      />
      <MeltWellsTable wells={view.wells} caption={`Melt calls: ${label}`} />
    </div>
  );
}

/**
 * The Curves stage's melt card: the plate's assays and the wells G-MELT points at; the wells
 * picked on the plate shown as melt curves.
 */
export function MeltPanel({
  sid,
  run,
  wells,
  onPickWells,
}: {
  sid: string;
  run: string | null;
  wells: readonly string[];
  /** Pick these wells of the plate (the plate map and the curve viewer follow). */
  onPickWells?: (wells: string[]) => void;
}) {
  const source = useMemo<MeltSource>(() => ({ kind: "session", sid }), [sid]);
  const q = useMelt(source, run, wells);
  const view = q.data;
  const title = "Melt curve";
  if (q.error && !view) {
    return (
      <Card as="section" aria-labelledby="curves-melt-title">
        <CardHeader id="curves-melt-title" title={title} />
        <CardBody>
          <ErrorPanel error={q.error} onRetry={() => void q.refetch()} compact />
        </CardBody>
      </Card>
    );
  }
  if (!view) {
    return (
      <Card as="section" aria-labelledby="curves-melt-title">
        <CardHeader id="curves-melt-title" title={title} />
        <CardBody>
          <LoadingBlock label="Reading the melt curves from the file" lines={4} />
        </CardBody>
      </Card>
    );
  }
  if (!view.has_melt) {
    return (
      <Card as="section" aria-labelledby="curves-melt-title">
        <CardHeader id="curves-melt-title" title={title} />
        <CardBody>
          <EmptyState compact icon={<Thermometer />} title="No melt curves in this file">
            {view.message}
          </EmptyState>
        </CardBody>
      </Card>
    );
  }
  const hint = wells.length
    ? `−dF/dT of ${wells.length === 1 ? `well ${wells[0]}` : plural(Math.min(wells.length, MAX_MELT_WELLS), "well")} on plate ${view.run ?? ""}`
    : `Plate ${view.run ?? ""}: where each assay's product melts, and the wells G-MELT points at.`;
  return (
    <Card as="section" aria-labelledby="curves-melt-title">
      <CardHeader id="curves-melt-title" title={title} hint={hint} />
      <CardBody className="flex flex-col gap-4">
        {view.message ? <p className="text-[13px] text-muted">{view.message}</p> : null}
        {wells.length && view.wells.length ? (
          <MeltCurves
            view={view}
            label={
              wells.length === 1
                ? `Well ${wells[0]} of plate ${view.run}`
                : `${count(view.wells.length)} wells of plate ${view.run}`
            }
          />
        ) : wells.length && !q.isFetching ? (
          <p className="text-[13px] text-muted">
            {wells.length === 1 ? "This well has" : "These wells have"} no melt curve.
          </p>
        ) : null}
        <AssayLines view={view} />
        <FlaggedWells calls={view.calls} onPick={onPickWells} chosen={wells} />
      </CardBody>
    </Card>
  );
}
