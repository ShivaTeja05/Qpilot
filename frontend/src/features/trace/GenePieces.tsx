/**
 * The pieces of one gene's trace: the call and the well to look at first, the selected sample
 * (with the "what if I drop it?" switch and the engine's recomputed call), the places to look,
 * the fewest samples that change the call, each control gene's share, every sample, and what
 * was checked. Pure: data in, events out (the page wires the queries).
 */
import { ArrowRight, ChevronDown, FlaskConical, RotateCcw, Route } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "wouter";
import type { Schemas } from "@/api/client";
import { sectionPath } from "@/shell/sections";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ConclusionTag,
  DataTable,
  ErrorPanel,
  LoadingBlock,
  Switch,
  type ColumnDef,
} from "@/ui";
import { cn } from "@/lib/cn";
import { ci, count, fixed, pValue } from "@/lib/format";
import { asConclusion } from "@/lib/vocab";
import type {
  CallChange,
  CallView,
  Option,
  Place,
  Reference,
  Sample,
  Texts,
  Trace,
  Well,
  WithoutView,
} from "./api";
import { FactText } from "./FactText";
import {
  CALL_WORD,
  CONSEQUENCE,
  PLACE_KIND,
  SAMPLE_FLAG,
  address,
  changeWords,
  effectPercent,
  push,
} from "./words";

type Workspace = Pick<Schemas["WorkspaceView"], "key" | "kind">;

// ---- the header ---------------------------------------------------------------------------------

export function CallFacts({ call, labels }: { call: CallView; labels: readonly string[] }) {
  const [lo, hi] = call.ci ?? [];
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
      <Fact label="Call">
        <ConclusionTag conclusion={asConclusion(call.conclusion)} long />
      </Fact>
      <Fact label={`${labels[0] ?? "group A"} vs ${labels[1] ?? "group B"}`}>
        <span className="tabular">{changeWords(call.log2fc)}</span>
      </Fact>
      <Fact label="95 % CI">
        <span className="tabular">{ci(lo, hi)}</span>
      </Fact>
      {call.p_adjusted != null && call.correction ? (
        <Fact label={`Corrected p (${call.correction}) · samples`}>
          <span className="tabular">
            {pValue(call.p_adjusted)} · {count(call.n_a)} vs {count(call.n_b)}
          </span>
          <span className="tabular mt-0.5 block text-[12px] text-muted">
            {call.q != null ? `q ${pValue(call.q)} · ` : ""}p before correction {pValue(call.p)}
          </span>
        </Fact>
      ) : (
        <Fact label="p · samples">
          <span className="tabular">
            {pValue(call.p)} · {count(call.n_a)} vs {count(call.n_b)}
          </span>
        </Fact>
      )}
    </dl>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-xs font-medium text-muted">{label}</dt>
      <dd className="mt-1 text-[15px] text-fg">{children}</dd>
    </div>
  );
}

/** "Look here first": the engine's sentence and the well it names. */
export function LookFirst({
  trace,
  texts,
  onWell,
  onSample,
}: {
  trace: Trace;
  texts: Texts;
  onWell: (well: Well) => void;
  onSample: (unit: string) => void;
}) {
  const look = trace.look_first;
  const place = look.place != null ? trace.places.find((p) => p.rank === look.place) : undefined;
  const tone = place ? CONSEQUENCE[place.consequence].tone : "neutral";
  return (
    <section
      aria-labelledby="trace-first"
      className={cn(
        "rounded-xl border p-4",
        tone === "danger" ? "border-warn bg-warn-soft" : "border-line bg-surface",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="trace-first" className="text-[15px] font-semibold text-fg">
          {look.kind === "place"
            ? "The well to look at first"
            : look.kind === "influential"
              ? "Nothing to look at"
              : "Nothing to trace"}
        </h2>
        {place ? (
          <Badge tone={tone === "danger" ? "danger" : "neutral"}>
            {CONSEQUENCE[place.consequence].word}
          </Badge>
        ) : null}
      </div>
      <p className="mt-2 text-[14px] leading-relaxed text-fg">
        <FactText text={texts[look.text]} />
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {look.well ? (
          <Button
            size="sm"
            variant="primary"
            icon={<FlaskConical />}
            onClick={() => onWell(look.well!)}
          >
            Open {address(look.well)}
          </Button>
        ) : null}
        {look.unit ? (
          <Button size="sm" variant="secondary" onClick={() => onSample(look.unit!)}>
            Show sample {look.unit}
          </Button>
        ) : null}
      </div>
    </section>
  );
}

// ---- the selected sample and the what-if ---------------------------------------------------------

export function SamplePanel({
  trace,
  sample,
  aside,
  onAside,
  onWell,
  wellKey,
}: {
  trace: Trace;
  sample: Sample;
  aside: boolean;
  onAside: (on: boolean) => void;
  onWell: (well: Well) => void;
  wellKey: string | null;
}) {
  const gene = trace.gene;
  const pushes = push(sample);
  const flags = sample.flags;
  return (
    <Card as="section" aria-labelledby="trace-sample">
      <CardHeader
        id="trace-sample"
        level={3}
        title={`Sample ${sample.unit}`}
        hint={`${sample.group} · ranked ${count(sample.rank)} of ${count(trace.samples.length)} by influence`}
      />
      <CardBody className="flex flex-col gap-3">
        <p className="text-[13px] leading-relaxed text-fg">
          By being there it {pushes === "none" ? "does not move" : pushes} {gene}&rsquo;s fold
          change. Set aside alone, the fold change moves{" "}
          <span className="tabular font-medium">{effectPercent(sample.d_log2fc)}</span> (
          {changeWords(trace.call.log2fc)} becomes {changeWords(sample.log2fc_without)})
          {sample.flips ? (
            <>
              {" "}
              and{" "}
              <span className="font-medium">the call becomes {CALL_WORD[sample.call_without]}</span>
              .
            </>
          ) : (
            <>; the call stays {CALL_WORD[trace.call.conclusion]}.</>
          )}
        </p>
        {flags.length ? (
          <ul className="flex flex-col gap-1.5" aria-label="What stands out">
            {flags.map((f) => (
              <li key={f} className="flex items-start gap-2 text-[13px]">
                <Badge tone={f === "far_from_group" ? "neutral" : "warn"} className="shrink-0">
                  {SAMPLE_FLAG[f]?.word ?? f}
                </Badge>
                <span className="text-muted">{SAMPLE_FLAG[f]?.detail}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-muted">
            Nothing unusual in its wells: its value is what its wells say.
          </p>
        )}
        <Switch
          checked={aside}
          onCheckedChange={onAside}
          label="What if I set this sample aside?"
          hint="The engine recomputes the call without it. Nothing in your analysis changes."
        />
        {sample.wells.length ? (
          <div>
            <h4 className="mb-1.5 text-xs font-medium text-muted">Its wells behind {gene}</h4>
            <ul className="flex flex-col gap-1">
              {sample.wells.map((w) => (
                <li key={w.key}>
                  <button
                    type="button"
                    onClick={() => onWell(w)}
                    aria-pressed={wellKey === w.key}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-left text-[13px] hover:border-line-strong",
                      wellKey === w.key ? "border-accent bg-accent-soft" : "border-line bg-surface",
                    )}
                  >
                    <span className="w-24 shrink-0 truncate font-medium text-fg">{w.gene}</span>
                    <span className="min-w-0 flex-1 truncate text-muted">{address(w)}</span>
                    <span className="tabular text-muted">
                      {w.cq != null ? `Cq ${fixed(w.cq, 1)}` : "no Cq"}
                    </span>
                    {w.flags.includes("reference_pull") ? <Badge tone="warn">off</Badge> : null}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-[12px] text-muted">
            Wells are listed for the most influential samples and for every unusual one; this one is
            neither.
          </p>
        )}
      </CardBody>
    </Card>
  );
}

/** The engine's call with the samples set aside (a what-if). */
export function WithoutResult({
  workspace,
  gene,
  aside,
  query,
  onClear,
}: {
  workspace: Workspace;
  gene: string;
  aside: readonly string[];
  query: { data?: WithoutView; error: unknown; isFetching: boolean; refetch: () => unknown };
  onClear: () => void;
}) {
  if (!aside.length) return null;
  const r = query.data?.result;
  const current = r && [...r.units].sort().join("|") === [...aside].sort().join("|");
  return (
    <Card
      as="section"
      aria-labelledby="trace-whatif"
      aria-busy={query.isFetching}
      className="border-accent"
    >
      <CardHeader
        id="trace-whatif"
        level={3}
        title="What if"
        hint={`${count(aside.length)} ${aside.length === 1 ? "sample" : "samples"} set aside: ${aside.join(", ")}`}
        actions={
          <Button size="sm" variant="ghost" icon={<RotateCcw />} onClick={onClear}>
            Put back
          </Button>
        }
      />
      <CardBody className="flex flex-col gap-3">
        {query.error && !current ? (
          <ErrorPanel compact error={query.error} onRetry={() => void query.refetch()} />
        ) : !r ? (
          <LoadingBlock lines={2} label="The engine is recomputing the call" />
        ) : (
          <div className={cn("flex flex-col gap-3 transition-opacity", !current && "opacity-60")}>
            <div className="flex flex-wrap items-center gap-2 text-[14px]">
              <ConclusionTag conclusion={asConclusion(r.before.conclusion)} />
              <span className="tabular text-muted">{changeWords(r.before.log2fc)}</span>
              <ArrowRight className="size-4 text-muted" aria-label="becomes" />
              <ConclusionTag conclusion={asConclusion(r.after.conclusion)} />
              <span className="tabular text-fg">{changeWords(r.after.log2fc)}</span>
              <span className="tabular text-muted">p {pValue(r.after.p)}</span>
            </div>
            <p className="text-[13px] text-fg">
              {r.changes_call ? (
                <span className="font-medium">The call changes.</span>
              ) : (
                <>The call stays {CALL_WORD[r.before.conclusion]}.</>
              )}{" "}
              {r.other_changes.length ? (
                <>
                  {count(r.other_changes.length)} other{" "}
                  {r.other_changes.length === 1 ? "call changes" : "calls change"} too:{" "}
                  <ChangeLinks workspace={workspace} changes={r.other_changes} />.
                </>
              ) : (
                <>No other call changes.</>
              )}
            </p>
            <p className="text-[12px] text-muted">
              Recomputed by the engine with {count(r.after.n_a)} vs {count(r.after.n_b)} samples;
              everyone else keeps their group. Nothing in {gene}&rsquo;s analysis is changed:
              setting a sample aside for real is a person&rsquo;s decision in Studio.
            </p>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function ChangeLinks({
  workspace,
  changes,
}: {
  workspace: Workspace;
  changes: readonly CallChange[];
}) {
  return (
    <>
      {changes.map((c, i) => (
        <span key={c.gene}>
          {i ? ", " : ""}
          <Link
            href={sectionPath(workspace, "trace", c.gene)}
            className="font-medium text-accent underline-offset-4 hover:underline"
          >
            {c.gene}
          </Link>{" "}
          ({CALL_WORD[c.call_before]} → {CALL_WORD[c.call_after]})
        </span>
      ))}
    </>
  );
}

// ---- places ---------------------------------------------------------------------------------------

export function Places({
  workspace,
  trace,
  texts,
  onWell,
  onSample,
}: {
  workspace: Workspace;
  trace: Trace;
  texts: Texts;
  onWell: (well: Well) => void;
  onSample: (unit: string) => void;
}) {
  const [all, setAll] = useState(false);
  const matter = trace.places.filter((p) => p.consequence !== "changes_nothing");
  const open = all ? trace.places : trace.places.slice(0, Math.max(3, matter.length));
  const rest = trace.places.length - open.length;
  return (
    <Card as="section" aria-labelledby="trace-places">
      <CardHeader
        id="trace-places"
        title="Places to look"
        hint={
          trace.places.length
            ? `${count(trace.places.length)} unusual ${trace.places.length === 1 ? "place" : "places"} behind ${trace.gene}, the ones that change it first.`
            : `Nothing unusual behind ${trace.gene}.`
        }
      />
      <CardBody className="flex flex-col gap-3">
        {trace.places.length ? (
          <ol className="flex flex-col gap-3">
            {open.map((p) => (
              <PlaceItem
                key={p.rank}
                workspace={workspace}
                place={p}
                texts={texts}
                onWell={onWell}
                onSample={onSample}
              />
            ))}
          </ol>
        ) : (
          <p className="text-[13px] text-muted">
            No control-gene well disagrees, no sample is late on every gene or amplifies poorly, and
            no study well sits near an amplifying no-template control.
          </p>
        )}
        {rest > 0 ? (
          <Button
            size="sm"
            variant="secondary"
            icon={<ChevronDown />}
            onClick={() => setAll(true)}
            className="self-start"
          >
            Show {count(rest)} more {rest === 1 ? "place that changes" : "places that change"}{" "}
            nothing here
          </Button>
        ) : null}
      </CardBody>
    </Card>
  );
}

function PlaceItem({
  workspace,
  place,
  texts,
  onWell,
  onSample,
}: {
  workspace: Workspace;
  place: Place;
  texts: Texts;
  onWell: (well: Well) => void;
  onSample: (unit: string) => void;
}) {
  const c = CONSEQUENCE[place.consequence];
  const flagged = place.wells.filter((w) => w.flags.length);
  const shown = (flagged.length ? flagged : place.wells).slice(0, 4);
  return (
    <li className="rounded-lg border border-line bg-surface p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="grid size-6 place-items-center rounded-full bg-surface-2 text-xs font-semibold text-fg tabular">
          {place.rank}
        </span>
        <span className="text-[13px] font-medium text-fg">{PLACE_KIND[place.kind]}</span>
        <button
          type="button"
          onClick={() => onSample(place.unit)}
          className="text-[13px] text-accent underline-offset-4 hover:underline"
        >
          sample {place.unit}
        </button>
        <Badge tone={c.tone === "danger" ? "danger" : c.tone === "warn" ? "warn" : "neutral"}>
          {c.word}
        </Badge>
      </div>
      <p className="mt-2 text-[13px] leading-relaxed text-fg">
        <FactText text={texts[place.text]} />
      </p>
      {shown.length ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {shown.map((w) => (
            <Button key={w.key} size="sm" variant="secondary" onClick={() => onWell(w)}>
              {w.gene} · {address(w)}
            </Button>
          ))}
        </div>
      ) : null}
      <OptionsLine workspace={workspace} options={place.options} />
    </li>
  );
}

function OptionsLine({ workspace, options }: { workspace: Workspace; options: readonly Option[] }) {
  const lines = options.filter((o) => o.changes.length);
  if (!lines.length) return null;
  return (
    <ul className="mt-2 flex flex-col gap-1 border-t border-line pt-2 text-[12px] text-muted">
      {lines.map((o) => (
        <li key={o.id}>
          <span className="text-fg">{o.label[0]!.toUpperCase() + o.label.slice(1)}:</span>{" "}
          <ChangeLinks workspace={workspace} changes={o.changes} />
          {o.regrouped ? <> (the groups change: {o.regrouped})</> : null}
        </li>
      ))}
    </ul>
  );
}

// ---- the fewest samples ---------------------------------------------------------------------------

export function FlipSet({
  trace,
  texts,
  onAside,
  onSample,
}: {
  trace: Trace;
  texts: Texts;
  onAside: (units: string[]) => void;
  onSample: (unit: string) => void;
}) {
  const flip = trace.flip;
  return (
    <Card as="section" aria-labelledby="trace-flip">
      <CardHeader
        id="trace-flip"
        title={
          flip.k == null
            ? `No small set of samples changes ${trace.gene}`
            : `${flip.exact ? "" : "At most "}${count(flip.k)} ${flip.k === 1 ? "sample changes" : "samples change"} this call`
        }
        hint={`${count(trace.n_flip_single)} of ${count(trace.n_used)} samples each change it when set aside alone.`}
      />
      <CardBody className="flex flex-col gap-3">
        <p className="text-[13px] leading-relaxed text-fg">
          <FactText text={texts.flip} />
        </p>
        {flip.units.length ? (
          <div className="flex flex-wrap items-center gap-1.5">
            {flip.units.map((u) => (
              <Button key={u} size="sm" variant="secondary" onClick={() => onSample(u)}>
                {u}
              </Button>
            ))}
            <Button
              size="sm"
              variant="primary"
              icon={<Route />}
              onClick={() => onAside(flip.units)}
            >
              Set {flip.units.length === 1 ? "it" : `these ${count(flip.units.length)}`} aside (what
              if)
            </Button>
          </div>
        ) : null}
        {trace.influential_normal.length ? (
          <p className="text-[12px] text-muted">
            Influential with nothing unusual in their wells (keep them: their values are what their
            wells say): {trace.influential_normal.slice(0, 12).join(", ")}
            {trace.influential_normal.length > 12
              ? ` and ${count(trace.influential_normal.length - 12)} more`
              : ""}
            .
          </p>
        ) : null}
      </CardBody>
    </Card>
  );
}

// ---- control genes ----------------------------------------------------------------------------------

export function References({ trace, onWell }: { trace: Trace; onWell: (well: Well) => void }) {
  const refs = trace.references;
  const top = Math.max(1e-12, ...refs.map((r) => Math.abs(r.share_log2)));
  const k = refs.length;
  return (
    <Card as="section" aria-labelledby="trace-refs">
      <CardHeader
        id="trace-refs"
        title="What the control genes do"
        hint={`${trace.gene} is divided by the mean of ${count(k)} control ${k === 1 ? "gene" : "genes"}; each one's share of the fold change is exact.`}
      />
      <CardBody>
        <ul className="flex flex-col gap-3">
          {refs.map((r) => (
            <RefRow key={r.gene} r={r} top={top} gene={trace.gene} onWell={onWell} />
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}

function RefRow({
  r,
  top,
  gene,
  onWell,
}: {
  r: Reference;
  top: number;
  gene: string;
  onWell: (well: Well) => void;
}) {
  const width = Math.abs(r.share_log2) / top;
  const raises = r.share_log2 > 0;
  const factor = 2 ** Math.abs(r.share_log2);
  return (
    <li className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span className="text-[13px] font-medium text-fg">{r.gene}</span>
        <span className="text-[12px] text-muted tabular">
          {fixed(factor, 2) === "1.00"
            ? "barely moves it"
            : `${raises ? "raises" : "lowers"} it ${fixed(factor, 2)}×`}
        </span>
      </div>
      <div className="relative h-2 rounded-full bg-sunken" aria-hidden="true">
        <span className="absolute inset-y-0 left-1/2 w-px bg-line-strong" />
        <span
          className="absolute inset-y-0 rounded-full"
          style={{
            background: raises ? "var(--up)" : "var(--down)",
            left: raises ? "50%" : `${50 - 50 * width}%`,
            width: `${50 * width}%`,
          }}
        />
      </div>
      <p className="text-[12px] text-muted">
        {r.call_without != null && r.log2fc_without != null ? (
          <>
            Without it, {gene} is {CALL_WORD[r.call_without]} ({changeWords(r.log2fc_without)})
            {r.without ? <span className="font-medium text-fg"> — the call changes</span> : null}.
          </>
        ) : (
          <>The only control gene: there is nothing to normalise to without it.</>
        )}{" "}
        {r.flagged.length ? (
          <>
            {count(r.flagged.length)} of its wells disagree with their sample&rsquo;s other control
            genes:{" "}
            {r.flagged.slice(0, 3).map((w, i) => (
              <span key={w.key}>
                {i ? ", " : ""}
                <button
                  type="button"
                  className="text-accent underline-offset-4 hover:underline"
                  onClick={() => onWell(w)}
                >
                  {w.unit} ({w.well})
                </button>
              </span>
            ))}
            {r.flagged.length > 3 ? ` and ${count(r.flagged.length - 3)} more` : ""}.
          </>
        ) : null}
      </p>
    </li>
  );
}

// ---- every sample ---------------------------------------------------------------------------------

export function SamplesTable({
  trace,
  selected,
  onSample,
}: {
  trace: Trace;
  selected: string | null;
  onSample: (unit: string) => void;
}) {
  const columns = useMemo<ColumnDef<Sample, unknown>[]>(
    () => [
      { id: "rank", header: "#", accessorKey: "rank", meta: { numeric: true, width: "3.5rem" } },
      { id: "unit", header: "Sample", accessorKey: "unit", meta: { width: "7rem" } },
      { id: "group", header: "Group", accessorKey: "group", meta: { width: "8rem" } },
      {
        id: "effect",
        header: "Set aside, moves",
        accessorFn: (s) => s.d_log2fc,
        meta: { numeric: true, width: "8rem" },
        cell: ({ row }) => effectPercent(row.original.d_log2fc),
      },
      {
        id: "call",
        header: "Call without it",
        accessorFn: (s) => (s.flips ? 0 : 1),
        meta: { width: "9rem" },
        cell: ({ row }) => (
          <span className={cn(row.original.flips && "font-medium text-fg")}>
            {CALL_WORD[row.original.call_without]}
            {row.original.flips ? " (changes)" : ""}
          </span>
        ),
      },
      {
        id: "flags",
        header: "Stands out",
        accessorFn: (s) => s.flags.join(" "),
        enableSorting: false,
        meta: { width: "14rem" },
        cell: ({ row }) => (
          <span className="block truncate text-[12px] text-muted">
            {row.original.flags.map((f) => SAMPLE_FLAG[f]?.word ?? f).join(", ") || "—"}
          </span>
        ),
      },
      {
        id: "wells",
        header: "Wells to look at",
        accessorFn: (s) => s.wells.filter((w) => w.flags.length).length,
        enableSorting: false,
        meta: { width: "16rem" },
        cell: ({ row }) => {
          const odd = row.original.wells.filter(
            (w) => w.flags.includes("reference_pull") || w.flags.includes("ntc_window"),
          );
          const text = odd.length
            ? odd.map((w) => `${w.gene} ${address(w)}`).join("; ")
            : `none (${count(row.original.plates.length)} plates)`;
          return (
            <span
              className="block truncate text-[12px] text-muted"
              title={row.original.plates.join(", ")}
            >
              {text}
            </span>
          );
        },
      },
    ],
    [],
  );
  return (
    <Card as="section" aria-labelledby="trace-samples">
      <CardHeader
        id="trace-samples"
        title="Every sample in the comparison"
        hint={`${count(trace.samples.length)} samples, the one that moves ${trace.gene} most first. Click one to trace it.`}
      />
      <CardBody>
        <DataTable
          data={trace.samples}
          columns={columns}
          getRowId={(s) => s.unit}
          label={`Samples behind ${trace.gene}`}
          height={360}
          onRowClick={(s) => onSample(s.unit)}
          selectedId={selected}
          empty="No sample is in this comparison."
        />
      </CardBody>
    </Card>
  );
}

// ---- what was checked -------------------------------------------------------------------------------

export function Checked({ trace }: { trace: Trace }) {
  return (
    <Card as="section" aria-labelledby="trace-checked">
      <CardHeader id="trace-checked" title="Checked, and what the data cannot show" level={3} />
      <CardBody className="grid gap-4 md:grid-cols-2">
        <div>
          <h4 className="mb-1.5 text-xs font-medium text-muted">Checked, nothing found</h4>
          <ul className="flex list-disc flex-col gap-1 pl-4 text-[13px] text-fg">
            {trace.checked.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="mb-1.5 text-xs font-medium text-muted">The data cannot show</h4>
          <ul className="flex list-disc flex-col gap-1 pl-4 text-[13px] text-fg">
            {trace.cannot_show.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
        {trace.missing.length || trace.n_no_comparison ? (
          <div className="md:col-span-2">
            <h4 className="mb-1.5 text-xs font-medium text-muted">Samples with no value here</h4>
            <p className="text-[13px] text-fg">
              {trace.missing.length ? (
                <>
                  {count(trace.missing.length)} {trace.missing.length === 1 ? "sample" : "samples"}{" "}
                  of the groups have no {trace.gene} value:{" "}
                  {trace.missing
                    .slice(0, 8)
                    .map(
                      (m) =>
                        `${m.unit} (${m.wells.map((w) => address(w)).join(", ") || "no well"})`,
                    )
                    .join("; ")}
                  {trace.missing.length > 8 ? `; and ${count(trace.missing.length - 8)} more` : ""}
                  .{" "}
                </>
              ) : null}
              {trace.n_no_comparison ? (
                <>
                  {count(trace.n_no_comparison)} samples of the study are in no comparison at all;
                  the overview says why.
                </>
              ) : null}
            </p>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}
