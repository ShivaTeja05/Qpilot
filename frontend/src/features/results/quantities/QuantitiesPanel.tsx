/**
 * Quantities (absolute quantification): shown on Results when the study has standards of known
 * quantity. Per assay: the standard curve (slope, efficiency with its 95 % CI, R², LOD, LOQ, the
 * chart) and every biological unit's quantity per reaction with its 95 % prediction interval and
 * flags in words. A person can record what one reaction held, for quantities per µL and per ng.
 * Every number is the API's (qpilot/qpcr/absolute.py); the page only formats it.
 */
import { ChevronDown, ChevronRight, FlaskRound, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { fixed } from "@/lib/format";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ErrorPanel,
  Input,
  KeyValues,
  LoadingBlock,
  SegmentedControl,
  Select,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Textarea,
} from "@/ui";
import {
  useAssay,
  useQuantities,
  useRecordReaction,
  type CurveSummary,
  type Limit,
  type QuantitiesView,
  type UnitQuantity,
} from "./api";
import {
  fmtEfficiency,
  fmtQuantity,
  fmtQuantityRange,
  fmtStandard,
  fmtWells,
  unitWords,
} from "./format";
import { StandardCurveChart } from "./StandardCurveChart";
import { UnitWells } from "./UnitWells";

const SHOWN_ROWS = 200;

function limitText(limit: Limit): string {
  if (limit.quantity == null) return "not determined";
  return `${limit.at_most ? "≤ " : ""}${limit.method === "logistic" ? fmtQuantity(limit.quantity) : fmtStandard(limit.quantity)}`;
}

function CurveNumbers({ curve, unit }: { curve: CurveSummary; unit: string }) {
  if (!curve.fitted) {
    return (
      <p className="text-[13px] text-muted" role="status">
        No standard curve: {curve.problem}
      </p>
    );
  }
  const ci =
    curve.efficiency_low != null && curve.efficiency_high != null
      ? ` (95 % CI ${fmtEfficiency(curve.efficiency_low)}–${fmtEfficiency(curve.efficiency_high)})`
      : "";
  const rows: [string, string][] = [
    ["Slope", `${fixed(curve.slope, 3)} cycles per ten-fold`],
    ["Efficiency", `${fmtEfficiency(curve.efficiency)}${ci}`],
    ["R²", fixed(curve.r2, 4)],
    [
      "Standards",
      `${curve.n_levels} levels, ${curve.n_wells} wells, ${fmtStandard(curve.lowest)} to ${fmtStandard(curve.top)} ${unitWords(unit)}`,
    ],
    ["Limit of detection", limitText(curve.lod)],
    ...(curve.lod_model
      ? [["Modelled LOD (logistic)", limitText(curve.lod_model)] as [string, string]]
      : []),
    ["Limit of quantification", limitText(curve.loq)],
    ["Quantities from", SOURCE_WORDS[curve.quantity_source] ?? curve.quantity_source],
  ];
  return (
    <div className="space-y-2">
      <KeyValues rows={rows} />
      <p className="text-[12px] leading-relaxed text-muted">
        LOD: {curve.lod.words}. LOQ: {curve.loq.words}.
        {curve.lod_model ? ` Modelled LOD: ${curve.lod_model.words}.` : ""}
      </p>
      {curve.warnings.length > 0 && (
        <ul className="space-y-1 text-[12.5px] text-fg">
          {curve.warnings.map((w) => (
            <li key={w} className="flex items-start gap-1.5">
              <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warn" aria-hidden />
              <span>{w}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const SOURCE_WORDS: Record<string, string> = {
  design: "the Design page (a person)",
  file: "the input file",
  name: "the standards' names",
};

function UnitsTable({
  units,
  unit,
  groups,
  reaction,
  quantify = false,
  sid = null,
}: {
  units: UnitQuantity[];
  unit: string;
  groups: boolean;
  reaction: { perUl: boolean; perNg: boolean };
  /** A study that quantifies samples: what is reported for each, and its wells on a click. */
  quantify?: boolean;
  sid?: string | null;
}) {
  const [which, setWhich] = useState<"all" | "flagged">("all");
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const flagged = units.filter((u) => u.flags.length);
  const rows = which === "flagged" ? flagged : units;
  const columns =
    7 + (groups ? 1 : 0) + (quantify ? 1 : 0) + (reaction.perUl ? 1 : 0) + (reaction.perNg ? 1 : 0);
  const toggle = (name: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] font-medium text-fg">
          Each biological unit, per reaction ({unitWords(unit)})
        </p>
        <SegmentedControl
          label="Which units"
          size="sm"
          value={which}
          onValueChange={setWhich}
          options={[
            { value: "all", label: `All ${units.length}` },
            { value: "flagged", label: `Flagged ${flagged.length}` },
          ]}
        />
      </div>
      <div
        className="max-h-[420px] overflow-auto rounded-lg border border-line"
        tabIndex={0}
        role="region"
        aria-label={`Each biological unit, per reaction (${unitWords(unit)})`}
      >
        <Table>
          <THead>
            <TR>
              <TH>Unit</TH>
              {groups && <TH>Group</TH>}
              {quantify && <TH>Reported as</TH>}
              <TH numeric>Wells detected</TH>
              <TH numeric>Mean Cq</TH>
              <TH numeric>Quantity</TH>
              <TH numeric>95 % prediction interval</TH>
              {reaction.perUl && <TH numeric>Per µL of template</TH>}
              {reaction.perNg && <TH numeric>Per ng of input</TH>}
              <TH>Notes</TH>
            </TR>
          </THead>
          <TBody>
            {rows.slice(0, SHOWN_ROWS).map((u) => [
              <TR key={u.unit}>
                <TD className="font-medium">
                  {quantify ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 text-left hover:underline"
                      aria-expanded={open.has(u.unit)}
                      aria-label={`${u.unit}: its wells`}
                      onClick={() => toggle(u.unit)}
                    >
                      {open.has(u.unit) ? (
                        <ChevronDown className="size-3.5 text-muted" aria-hidden />
                      ) : (
                        <ChevronRight className="size-3.5 text-muted" aria-hidden />
                      )}
                      {u.unit}
                    </button>
                  ) : (
                    u.unit
                  )}
                </TD>
                {groups && <TD>{u.group ?? "—"}</TD>}
                {quantify && (
                  <TD className="text-[12.5px]" data-class={u.reported}>
                    {u.reported_words}
                  </TD>
                )}
                <TD numeric>{fmtWells(u.n_detected, u.n_wells)}</TD>
                <TD numeric>{fixed(u.mean_cq, 2)}</TD>
                <TD numeric>{fmtQuantity(u.quantity)}</TD>
                <TD numeric>{fmtQuantityRange(u.low, u.high)}</TD>
                {reaction.perUl && <TD numeric>{fmtQuantity(u.per_ul)}</TD>}
                {reaction.perNg && <TD numeric>{fmtQuantity(u.per_ng)}</TD>}
                <TD className="text-[12px] text-muted">{u.flags.map((f) => f.words).join("; ")}</TD>
              </TR>,
              quantify && open.has(u.unit) ? (
                <TR key={`${u.unit}:wells`} className="bg-sunken/50">
                  <TD colSpan={columns}>
                    <UnitWells unit={u} sid={sid} />
                  </TD>
                </TR>
              ) : null,
            ])}
          </TBody>
        </Table>
      </div>
      {rows.length > SHOWN_ROWS && (
        <p className="text-[12px] text-muted">
          The first {SHOWN_ROWS} of {rows.length} are listed; every unit is in the Quantities table
          of the exports (Report).
        </p>
      )}
    </div>
  );
}

function ReactionForm({
  workspaceKey,
  studyId,
  view,
}: {
  workspaceKey: string;
  studyId: string;
  view: QuantitiesView;
}) {
  const [open, setOpen] = useState(false);
  const [ul, setUl] = useState(view.reaction?.template_ul ? String(view.reaction.template_ul) : "");
  const [ng, setNg] = useState(view.reaction?.input_ng ? String(view.reaction.input_ng) : "");
  const [unitName, setUnitName] = useState(view.reaction?.unit ?? (view.unit ? "" : "copies"));
  const [reason, setReason] = useState("");
  const write = useRecordReaction(workspaceKey, studyId);
  const num = (s: string) => (s.trim() === "" ? null : Number(s));
  const okNumber = (v: number | null) => v == null || (Number.isFinite(v) && v > 0);
  const head = view.inbox_head ?? null;
  const valid = okNumber(num(ul)) && okNumber(num(ng)) && reason.trim().length > 0 && head !== null;
  if (!view.can_set_reaction) return null;
  const now = view.reaction;
  return (
    <div className="rounded-lg border border-line bg-surface-2 px-3 py-2.5 text-[13px]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-muted">
          {now && (now.template_ul || now.input_ng)
            ? `Each reaction held ${[
                now.template_ul ? `${now.template_ul} µL of template` : null,
                now.input_ng ? `${now.input_ng} ng of input` : null,
              ]
                .filter(Boolean)
                .join(" and ")}: the quantities per ${[
                now.template_ul ? "µL" : null,
                now.input_ng ? "ng" : null,
              ]
                .filter(Boolean)
                .join(" and ")} are shown.`
            : "Per µL of template or per ng of input: give what one reaction held."}
        </span>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          {open ? "Close" : "Set the reaction input…"}
        </Button>
      </div>
      {open && (
        <form
          className="mt-3 grid gap-2 sm:grid-cols-[auto_auto_auto_1fr_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            if (!valid || head === null) return;
            write.mutate(
              {
                template_ul: num(ul),
                input_ng: num(ng),
                unit: unitName.trim() || null,
                reason: reason.trim(),
                expected_head: head,
              },
              { onSuccess: () => setOpen(false) },
            );
          }}
        >
          <label className="flex flex-col gap-1 text-[12px] text-muted">
            µL of template per reaction
            <Input
              inputMode="decimal"
              className="h-8 w-28"
              value={ul}
              onChange={(e) => setUl(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-[12px] text-muted">
            ng of input per reaction
            <Input
              inputMode="decimal"
              className="h-8 w-28"
              value={ng}
              onChange={(e) => setNg(e.target.value)}
            />
          </label>
          {!view.unit && (
            <label className="flex flex-col gap-1 text-[12px] text-muted">
              The standards count
              <Input
                className="h-8 w-28"
                value={unitName}
                maxLength={40}
                onChange={(e) => setUnitName(e.target.value)}
              />
            </label>
          )}
          <label className="flex flex-col gap-1 text-[12px] text-muted">
            Why (kept in the decision record)
            <Textarea
              rows={1}
              value={reason}
              maxLength={2000}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <Button
            type="submit"
            size="sm"
            variant="primary"
            disabled={!valid}
            loading={write.isPending}
          >
            Record
          </Button>
          <p className="text-[12px] text-muted sm:col-span-5">
            Recording analyses the study again with it; no fold change, call or card changes.
          </p>
        </form>
      )}
    </div>
  );
}

/** The Quantities card on Results; nothing when the study has no standards at all. */
export function QuantitiesPanel({
  workspaceKey,
  studyId,
  quantify = false,
  sid = null,
}: {
  workspaceKey: string;
  studyId: string;
  /** The study quantifies samples: its main result (classes, wells on a click). */
  quantify?: boolean;
  /** The Studio session (curves of wells), when there is one. */
  sid?: string | null;
}) {
  const view = useQuantities(workspaceKey, studyId);
  const assays = useMemo(() => view.data?.assays ?? [], [view.data]);
  const [picked, setPicked] = useState<string | null>(null);
  const target =
    picked && assays.some((a) => a.target === picked) ? picked : (assays[0]?.target ?? null);
  const assay = useAssay(workspaceKey, studyId, target);
  const [curveId, setCurveId] = useState<string | null>(null);

  if (view.error) {
    return <ErrorPanel error={view.error} title="The quantities could not be read" compact />;
  }
  const data = view.data;
  if (!data) return null;
  if (!data.available && !data.not_quantified.length) return null;

  const detail = assay.data && assay.data.target === target ? assay.data : null;
  const curves = detail?.curves ?? [];
  const curve = curves.find((c) => c.id === curveId) ?? curves.find((c) => c.fitted) ?? curves[0];
  const summary = assays.find((a) => a.target === target);
  const reaction = {
    perUl: Boolean(data.reaction?.template_ul),
    perNg: Boolean(data.reaction?.input_ng),
  };

  return (
    <Card as="section" aria-labelledby="quantities-title">
      <CardHeader
        id="quantities-title"
        title={
          <span className="inline-flex items-center gap-2">
            <FlaskRound className="size-4 text-muted" aria-hidden /> Quantities
          </span>
        }
        hint="How much was in each reaction, read from the standards on the plate: never a fold change."
        actions={
          assays.length > 1 ? (
            <Select
              label="Assay"
              size="sm"
              value={target ?? undefined}
              onValueChange={(v) => {
                setPicked(v);
                setCurveId(null);
              }}
              options={assays.map((a) => ({ value: a.target, label: a.target }))}
            />
          ) : null
        }
      />
      <CardBody className="space-y-4">
        {data.not_quantified.length > 0 && (
          <ul className="space-y-1 text-[13px]">
            {data.not_quantified.map((n) => (
              <li key={n.target}>
                <span className="font-medium text-fg">{n.target}</span>:{" "}
                <span className="text-muted">{n.reason}</span>
              </li>
            ))}
          </ul>
        )}
        {data.notes.map((n) => (
          <p key={n} className="text-[12.5px] text-muted">
            {n}
          </p>
        ))}
        {target && (
          <>
            {curves.length > 1 && (
              <SegmentedControl
                label="Which curve"
                size="sm"
                value={curve?.id ?? ""}
                onValueChange={setCurveId}
                options={curves.map((c) => ({
                  value: c.id,
                  label:
                    c.scope === "pooled" ? `Pooled (${c.runs.length} plates)` : c.runs.join(", "),
                }))}
              />
            )}
            {assay.error ? (
              <ErrorPanel error={assay.error} title="This assay could not be read" compact />
            ) : !detail || !curve ? (
              <LoadingBlock label="Reading the standard curve" lines={4} />
            ) : (
              <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
                <div className="min-w-0">
                  {curve.fitted ? (
                    <StandardCurveChart curve={curve} unknowns={detail.units} unit={detail.unit} />
                  ) : null}
                </div>
                <div className="min-w-0 space-y-2">
                  {curve.scope === "pooled" && (
                    <Badge tone="info">Pooled over {curve.runs.join(", ")}</Badge>
                  )}
                  <CurveNumbers curve={curve} unit={detail.unit} />
                  {summary && (
                    <p className="text-[12px] text-muted">
                      {summary.n_quantified} of {summary.n_units} units quantified,{" "}
                      {summary.n_flagged} with a note.
                    </p>
                  )}
                </div>
              </div>
            )}
            {detail && (
              <UnitsTable
                units={detail.units}
                unit={detail.unit}
                groups={data.groups_shown}
                reaction={reaction}
                quantify={quantify}
                sid={sid}
              />
            )}
          </>
        )}
        <ReactionForm workspaceKey={workspaceKey} studyId={studyId} view={data} />
        <p className="text-[12px] text-muted">
          Method: {data.method_card} — LOD at least {Math.round(data.settings.lod_rate * 100)} % of
          wells detected, LOQ a read-back CV of at most {Math.round(data.settings.loq_cv * 100)} %
          (Forootan et al. 2017).
        </p>
      </CardBody>
    </Card>
  );
}
