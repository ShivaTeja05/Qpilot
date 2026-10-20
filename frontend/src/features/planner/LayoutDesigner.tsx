/**
 * The layout designer: every plate of the next experiment, from the server's seeded layout
 * (`qpilot.qpcr.layout`). Balance badges, an overview of every plate, one plate at a time coloured
 * by group, gene or sample type, a new random order on demand and the CSV to import.
 */
import { AlertTriangle, CheckCircle2, Download, Shuffle, X } from "lucide-react";
import { useMemo, useState } from "react";
import { PlateMap, type PlateWell } from "@/charts/plate";
import { cn } from "@/lib/cn";
import { count, fixed, percent } from "@/lib/format";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ErrorPanel,
  LoadingBlock,
  SegmentedControl,
  Select,
  Switch,
  Tooltip,
} from "@/ui";
import {
  useLayout,
  type PlanLayoutBody,
  type PlanLayoutPlate,
  type PlanLayoutView,
  type PlannerScope,
} from "./api";
import { CategoryPlate } from "./CategoryPlate";
import { NumberField } from "./NumberField";
import { useDebounced } from "./hooks";
import { GROUP_TONES, TYPE_WORDS } from "./words";

export interface PlateSettings {
  wells_per_plate: 96 | 384;
  replicates: number;
  ntc: number;
  nrt: number;
  standards: number;
  calibrator: boolean;
  refs: string[];
}

type Colour = "group" | "target" | "type";

function association(v: number): string {
  if (v < 0.005) return "none";
  if (v < 0.1) return "negligible";
  if (v < 0.3) return "small";
  return "large";
}

function Check({ ok, children, hint }: { ok: boolean; children: React.ReactNode; hint?: string }) {
  const badge = (
    <Badge
      tone={ok ? "ok" : "warn"}
      icon={ok ? <CheckCircle2 aria-hidden /> : <AlertTriangle aria-hidden />}
      className="h-6 px-2 text-[12px]"
      tabIndex={hint ? 0 : undefined}
    >
      {children}
    </Badge>
  );
  return hint ? <Tooltip content={hint}>{badge}</Tooltip> : badge;
}

export function LayoutDesigner({
  scope,
  genes,
  nPlan,
  settings,
  onSettings,
  refChoices,
}: {
  scope: PlannerScope;
  genes: string[];
  nPlan: number;
  settings: PlateSettings;
  onSettings: (next: Partial<PlateSettings>) => void;
  /** Genes the reference set may use (the study's control genes and candidates). */
  refChoices: string[];
}) {
  const [nOwn, setNOwn] = useState<number | null>(null);
  const [seed, setSeed] = useState(1);
  const [colour, setColour] = useState<Colour>("group");
  const [picked, setPicked] = useState(1);
  const n = nOwn ?? nPlan;

  const body = useMemo<PlanLayoutBody | null>(
    () =>
      genes.length
        ? {
            n_per_group: n,
            genes,
            refs: settings.refs,
            replicates: settings.replicates,
            wells_per_plate: settings.wells_per_plate,
            ntc: settings.ntc,
            nrt: settings.nrt,
            standards: settings.standards,
            calibrator: settings.calibrator,
            seed,
          }
        : null,
    [genes, n, settings, seed],
  );
  const settled = useDebounced(body, 300);
  const layout = useLayout(scope, settled);
  const data = layout.data;
  const plate = data?.plates.find((p) => p.number === picked) ?? data?.plates[0] ?? null;

  return (
    <Card as="section" aria-labelledby="planner-layout">
      <CardHeader
        id="planner-layout"
        title="Plates for the next experiment"
        hint="Groups dealt evenly to every plate and shuffled within it, reference genes and controls on every plate. The same inputs and seed always give the same plates."
        actions={
          data ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                icon={<Shuffle aria-hidden />}
                onClick={() => setSeed((s) => s + 1)}
              >
                New random order
              </Button>
              <Button asChild size="sm" icon={<Download aria-hidden />}>
                <a href={data.csv_url} download={data.csv_name}>
                  Download CSV
                </a>
              </Button>
            </div>
          ) : null
        }
      />
      <CardBody className="space-y-5">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3 text-[13px]">
          <label className="flex flex-col gap-1">
            <span className="font-medium text-fg">Samples per group</span>
            <span className="flex items-center gap-2">
              <NumberField value={n} min={2} max={1000} onCommit={(v) => v != null && setNOwn(v)} />
              {nOwn != null && nOwn !== nPlan ? (
                <Button variant="link" size="sm" onClick={() => setNOwn(null)}>
                  Use the plan’s {count(nPlan)}
                </Button>
              ) : (
                <span className="text-[12px] text-muted">the plan’s size</span>
              )}
            </span>
          </label>
          <PlateSettingsControls
            settings={settings}
            onSettings={onSettings}
            refChoices={refChoices}
          />
          <div className="text-[12px] text-muted">
            Seed <span className="font-mono tabular text-fg">{seed}</span>
          </div>
        </div>

        {!genes.length ? (
          <p className="text-[13px] text-muted">
            Choose at least one gene above to lay out plates.
          </p>
        ) : layout.error ? (
          <ErrorPanel error={layout.error} title="These plates cannot be laid out" compact />
        ) : !data ? (
          <LoadingBlock label="Laying out the plates" lines={4} />
        ) : (
          <div className={cn("space-y-5", layout.isFetching && "opacity-70 transition-opacity")}>
            <Balance data={data} />
            {data.warnings.length || data.rules.length ? (
              <ul className="space-y-1 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-[13px] text-fg">
                {[...data.warnings, ...data.rules].map((w) => (
                  <li key={w} className="flex gap-2">
                    <AlertTriangle size={14} className="mt-0.5 shrink-0 text-warn" aria-hidden />
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            <Overview data={data} picked={plate?.number ?? 1} onPick={setPicked} />
            {plate ? (
              <div>
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-[14px] font-semibold text-fg">
                    {plate.name}
                    <span className="ml-2 font-normal text-muted">
                      {plate.genes.join(", ")} · samples{" "}
                      {Object.entries(plate.samples)
                        .map(([g, k]) => `${g} ${count(k)}`)
                        .join(" · ")}
                    </span>
                  </h3>
                  <SegmentedControl
                    label="Colour wells by"
                    size="sm"
                    value={colour}
                    onValueChange={setColour}
                    options={[
                      { value: "group", label: "Group" },
                      { value: "target", label: "Gene" },
                      { value: "type", label: "Sample type" },
                    ]}
                  />
                </div>
                {colour === "type" ? (
                  <PlateMap
                    wells={typeWells(plate)}
                    layer="role"
                    label={`${plate.name} by sample type`}
                    rows={settings.wells_per_plate === 384 ? 16 : 8}
                    columns={settings.wells_per_plate === 384 ? 24 : 12}
                    renderDetails={(w) =>
                      (w.notes ?? []).map((line) => <div key={line}>{line}</div>)
                    }
                  />
                ) : (
                  <CategoryPlate
                    plate={plate}
                    layer={colour}
                    groups={data.groups.map((g) => g.label)}
                  />
                )}
              </div>
            ) : null}
            <ul className="space-y-1 text-[12px] leading-relaxed text-muted">
              {data.notes.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function typeWells(plate: PlanLayoutPlate): PlateWell[] {
  return plate.wells.map((w) => ({
    well: w.well,
    sample: w.sample,
    target: w.target,
    role: w.type,
    notes: [
      w.group ? `group ${w.group}` : (TYPE_WORDS[w.type] ?? w.type),
      `replicate ${w.replicate}`,
    ],
  }));
}

function Balance({ data }: { data: PlanLayoutView }) {
  const b = data.balance;
  const v = b.group_plate_association;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Check
          ok={b.every_plate_every_group}
          hint="Plate is never group: every plate holds samples of every group, so a plate effect cannot pass for a group difference."
        >
          {b.every_plate_every_group
            ? "Every group on every plate"
            : `${count(b.plates_with_one_group.length)} plate(s) hold one group`}
        </Check>
        <Check
          ok={b.refs_on_every_plate}
          hint="Each sample is normalised by reference genes run on its own plate."
        >
          Reference genes on every plate
        </Check>
        <Check
          ok={b.controls_on_every_plate}
          hint="The chosen NTC / NRT wells, per assay, on every plate."
        >
          Controls on every plate
        </Check>
        <Check
          ok={b.each_reaction_once}
          hint="Every planned reaction is on exactly one plate (a reference gene once per gene panel)."
        >
          Every reaction placed once
        </Check>
        {data.batches === 1 ? (
          <Check
            ok
            hint="Each gene's samples share one plate (sample maximisation): no inter-run calibrator needed."
          >
            Each gene on one plate
          </Check>
        ) : (
          <Check
            ok={data.calibrated}
            hint="A gene's samples span plates: the same inter-run calibrator on every plate links the runs."
          >
            {data.calibrated ? "Calibrator on every plate" : "No calibrator across plates"}
          </Check>
        )}
        <Check
          ok={v < 0.3}
          hint="Cramér's V of plate × group over samples: 0 means knowing the plate says nothing about the group."
        >
          Plate vs group: V {fixed(v, 2)} ({association(v)})
        </Check>
      </div>
      <p className="text-[12px] text-muted">
        <span className="font-mono tabular">{count(data.plates.length)}</span> plate
        {data.plates.length === 1 ? "" : "s"} ·{" "}
        <span className="font-mono tabular">{count(b.wells_samples)}</span> sample wells ·{" "}
        <span className="font-mono tabular">{count(b.wells_controls)}</span> control wells ·{" "}
        <span className="font-mono tabular">{count(b.wells_free)}</span> free (
        {percent(b.wells_free / Math.max(1, b.wells_total))}) · largest gap between a group’s share
        on a plate and overall: {percent(b.max_share_gap)}
      </p>
    </div>
  );
}

function Overview({
  data,
  picked,
  onPick,
}: {
  data: PlanLayoutView;
  picked: number;
  onPick: (n: number) => void;
}) {
  const groups = data.groups.map((g) => g.label);
  return (
    <div
      role="list"
      aria-label="Every plate"
      className="grid grid-cols-[repeat(auto-fill,minmax(8.5rem,1fr))] gap-2"
    >
      {data.plates.map((p) => {
        const total = Object.values(p.samples).reduce((a, b) => a + b, 0) || 1;
        const on = p.number === picked;
        return (
          <button
            key={p.number}
            type="button"
            role="listitem"
            aria-pressed={on}
            aria-label={`${p.name}: ${p.genes.join(", ")}; ${groups
              .map((g) => `${count(p.samples[g] ?? 0)} ${g}`)
              .join(", ")}; ${count(p.wells_free)} wells free`}
            onClick={() => onPick(p.number)}
            className={cn(
              "rounded-lg border px-2.5 py-2 text-left transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-focus",
              on
                ? "border-accent bg-accent-soft"
                : "border-line bg-surface hover:border-line-strong",
            )}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[12px] font-semibold text-fg">{p.name}</span>
              <span className="font-mono text-[11px] text-muted tabular">
                {count(p.wells_free)} free
              </span>
            </div>
            <div className="mt-1.5 flex h-2 overflow-hidden rounded-full bg-sunken" aria-hidden>
              {groups.map((g, i) => (
                <span
                  key={g}
                  style={{
                    width: `${(100 * (p.samples[g] ?? 0)) / total}%`,
                    background: GROUP_TONES[i % GROUP_TONES.length],
                  }}
                />
              ))}
            </div>
            <div className="mt-1 truncate text-[11px] text-muted">
              {groups.map((g) => count(p.samples[g] ?? 0)).join(" · ")} · {p.genes.length} gene
              {p.genes.length === 1 ? "" : "s"}
            </div>
          </button>
        );
      })}
    </div>
  );
}

const SMALL = (top: number) =>
  Array.from({ length: top + 1 }, (_, i) => ({ value: String(i), label: String(i) }));

function PlateSettingsControls({
  settings,
  onSettings,
  refChoices,
}: {
  settings: PlateSettings;
  onSettings: (next: Partial<PlateSettings>) => void;
  refChoices: string[];
}) {
  const addable = refChoices.filter((g) => !settings.refs.includes(g));
  return (
    <>
      <div className="flex flex-col gap-1">
        <span className="text-[13px] font-medium text-fg">Plate</span>
        <SegmentedControl
          label="Plate size"
          size="sm"
          value={String(settings.wells_per_plate) as "96" | "384"}
          onValueChange={(v) => onSettings({ wells_per_plate: v === "384" ? 384 : 96 })}
          options={[
            { value: "96", label: "96 wells" },
            { value: "384", label: "384 wells" },
          ]}
        />
      </div>
      <SmallSelect
        label="Replicates"
        value={settings.replicates}
        options={SMALL(6).slice(1)}
        onChange={(v) => onSettings({ replicates: v })}
      />
      <SmallSelect
        label="NTC per gene"
        value={settings.ntc}
        options={SMALL(4)}
        onChange={(v) => onSettings({ ntc: v })}
      />
      <SmallSelect
        label="NRT per gene"
        value={settings.nrt}
        options={SMALL(4)}
        onChange={(v) => onSettings({ nrt: v })}
      />
      <SmallSelect
        label="Standard points"
        value={settings.standards}
        options={SMALL(8)}
        onChange={(v) => onSettings({ standards: v })}
      />
      <Switch
        checked={settings.calibrator}
        onCheckedChange={(on) => onSettings({ calibrator: on })}
        label="Inter-run calibrator"
        hint="On every plate when a gene's samples span plates."
      />
      <div className="flex min-w-[16rem] flex-col gap-1">
        <span className="text-[13px] font-medium text-fg">Reference genes (every plate)</span>
        <div className="flex flex-wrap items-center gap-1.5">
          {settings.refs.map((g) => (
            <span
              key={g}
              className="inline-flex h-7 items-center gap-1 rounded-full border border-line bg-surface pl-2.5 pr-1 text-[12px] text-fg"
            >
              {g}
              <button
                type="button"
                aria-label={`Remove the reference gene ${g}`}
                disabled={settings.refs.length <= 1}
                onClick={() => onSettings({ refs: settings.refs.filter((r) => r !== g) })}
                className="inline-flex size-5 items-center justify-center rounded-full text-muted hover:bg-bg-subtle hover:text-fg disabled:opacity-40"
              >
                <X size={12} aria-hidden />
              </button>
            </span>
          ))}
          {addable.length ? (
            <Select
              size="sm"
              label="Add a reference gene"
              placeholder="Add…"
              value={undefined}
              onValueChange={(g) => onSettings({ refs: [...settings.refs, g] })}
              options={addable.map((g) => ({ value: g, label: g }))}
              className="w-32"
            />
          ) : null}
        </div>
      </div>
    </>
  );
}

function SmallSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: number;
  options: { value: string; label: string }[];
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[13px] font-medium text-fg">{label}</span>
      <Select
        size="sm"
        label={label}
        value={String(value)}
        onValueChange={(v) => onChange(Number(v))}
        options={options}
        className="w-20"
      />
    </div>
  );
}
