/**
 * The plate map of the Design stage: one plate's wells by sample type (as declared in the file,
 * or as the design assembled so far has them), the wells of the proposal in focus outlined,
 * each well's names as quoted text, names that read like instructions marked. Drawn by the
 * shared plate map (`@/charts/plate`: keyboard, table view and legend included). Never a group
 * label while the stages are blind (the server sends none and the map reads none).
 */
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useMemo, useState } from "react";
import { api, unwrap, type Schemas } from "@/api/client";
import { PlateMap, curveName, curvesByWell, plateWells } from "@/charts/plate";
import { count } from "@/lib/format";
import { ROLE_SHORT, ROLE_WORDS } from "@/lib/vocab";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ErrorPanel,
  IconButton,
  LoadingBlock,
  Select,
} from "@/ui";
import { Quote, Warming, isWarming, visibleText, type QuoteLookup } from "@/ui/proposal";

export type PlateWell = Schemas["PlateWell"];
/** The target picker's value for "no target chosen" on a multiplex plate. */
const EVERY_DYE = "__every__";
type PlateView = Schemas["PlateView"];

export function usePlate(sid: string, run: string | null) {
  return useQuery({
    queryKey: ["w", sid, "plate", run ?? ""],
    queryFn: () =>
      unwrap(
        api.GET("/api/sessions/{sid}/plate", {
          params: { path: { sid }, query: run ? { run } : {} },
        }),
      ),
    placeholderData: (prev) => prev,
  });
}

function WellDetail({
  well,
  curves = [],
  quotes,
  onShowProposals,
  onClose,
}: {
  well: PlateWell;
  /** Every curve of the well (one per dye on a multiplex plate). */
  curves?: readonly PlateWell[];
  quotes: QuoteLookup;
  onShowProposals?: (w: PlateWell) => void;
  onClose: () => void;
}) {
  const sampleQuote = well.sample_text_id ? quotes(well.sample_text_id) : null;
  const targetQuote = well.target_text_id ? quotes(well.target_text_id) : null;
  return (
    <div
      className="flex flex-col gap-2.5 rounded-lg border border-line bg-surface-2 p-3 text-[13px]"
      aria-live="polite"
    >
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium text-fg">
          Well <span className="font-mono">{well.well}</span>
        </p>
        <IconButton label="Close the well" size="sm" onClick={onClose}>
          <X />
        </IconButton>
      </div>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5">
        <dt className="text-muted">Sample</dt>
        <dd className="min-w-0">
          {sampleQuote ? (
            <Quote entry={sampleQuote} />
          ) : (
            <span className="font-mono">{well.sample}</span>
          )}
        </dd>
        <dt className="text-muted">Target</dt>
        <dd className="min-w-0">
          {targetQuote ? (
            <Quote entry={targetQuote} />
          ) : (
            <span className="font-mono">{well.target}</span>
          )}
          {well.dye ? <span className="text-muted"> · dye {well.dye}</span> : null}
        </dd>
        {curves.length > 1 ? (
          <>
            <dt className="text-muted">In this well</dt>
            <dd className="min-w-0">
              <ul aria-label="Curves in this well" className="m-0 list-none p-0">
                {curves.map((c) => (
                  <li key={c.target} className="font-mono">
                    {curveName(c)}
                    <span className="font-sans text-muted">
                      {" "}
                      · {ROLE_SHORT[c.role ?? c.declared_type] ?? c.role ?? c.declared_type}
                    </span>
                  </li>
                ))}
              </ul>
            </dd>
          </>
        ) : null}
        <dt className="text-muted">Declared</dt>
        <dd>{ROLE_WORDS[well.declared_type] ?? well.declared_type}</dd>
        {well.role && well.role !== well.declared_type ? (
          <>
            <dt className="text-muted">In the design</dt>
            <dd>{ROLE_WORDS[well.role] ?? well.role}</dd>
          </>
        ) : null}
        {well.excluded_by_person || well.excluded_note ? (
          <>
            <dt className="text-muted">Excluded</dt>
            <dd>{well.excluded_by_person ? "by a person's decision" : well.excluded_note}</dd>
          </>
        ) : null}
      </dl>
      {onShowProposals ? (
        <Button
          size="sm"
          variant="secondary"
          onClick={() => onShowProposals(well)}
          className="self-start"
        >
          Show proposals about this sample
        </Button>
      ) : null}
    </div>
  );
}

/** The plate map card: plate picker, the shared plate map, and the chosen well's names. */
export function DesignPlate({
  sid,
  runs,
  quotes,
  highlight,
  onShowProposals,
  selectedKeys,
  onSelectKeys,
}: {
  sid: string;
  /** Every plate in the file (from the workspace summary), for the picker. */
  runs: Schemas["InspectRun"][];
  quotes: QuoteLookup;
  /** Which wells the proposal in focus is about (outlined). */
  highlight?: ((w: PlateWell) => boolean) | null;
  onShowProposals?: (w: PlateWell) => void;
  /**
   * Selecting for the design editor: the wells (`run_id/well`) of the selected samples, and
   * what to do when the person selects wells on the map (several at once: Shift-click, a row,
   * a column). Without it the map shows one well's names.
   */
  selectedKeys?: ReadonlySet<string>;
  onSelectKeys?: (wells: PlateWell[]) => void;
}) {
  const [run, setRun] = useState<string | null>(null);
  const [clicked, setClicked] = useState<string | null>(null);
  const [pickedTarget, setPickedTarget] = useState<string>(EVERY_DYE);
  const plate = usePlate(sid, run);
  const data: PlateView | undefined = plate.data;
  const apiWells = useMemo(() => data?.wells ?? [], [data]);
  // A multiplex plate has one curve per dye in a well: the map shows one target at a time.
  const target =
    data?.multiplex && pickedTarget !== EVERY_DYE && data.targets.includes(pickedTarget)
      ? pickedTarget
      : null;
  const byKey = useMemo(() => curvesByWell(apiWells), [apiWells]);
  const byLabel = useMemo(() => {
    const m = new Map<string, PlateWell>();
    for (const w of apiWells) if (target ? w.target === target : !m.has(w.well)) m.set(w.well, w);
    return m;
  }, [apiWells, target]);
  const wells = useMemo(() => {
    if (!data) return [];
    const instructionLike = (id: string | null | undefined) =>
      Boolean(id && quotes(id)?.flags.includes("instruction_like"));
    return plateWells(data, {
      flagged: (w) => instructionLike(w.sample_text_id) || instructionLike(w.target_text_id),
      keep: target ? (w) => w.target === target : undefined,
    });
  }, [data, quotes, target]);
  const lit = useMemo(
    () => (highlight ? apiWells.filter(highlight).map((w) => w.well) : []),
    [apiWells, highlight],
  );
  const chosen = clicked && !onSelectKeys ? (byLabel.get(clicked) ?? null) : null;
  const picking = Boolean(onSelectKeys);
  const picked = useMemo(
    () => (selectedKeys ? apiWells.filter((w) => selectedKeys.has(w.key)).map((w) => w.well) : []),
    [apiWells, selectedKeys],
  );

  const options = runs.map((r) => ({
    value: r.run_id,
    label: r.run_id,
    hint: `${r.experiment_id} · ${count(r.n_wells)} wells · ${r.targets.join(", ")}`,
  }));
  const roleWords = apiWells.some((w) => w.role)
    ? "as the design assembled so far has them"
    : "as declared in the file";
  const dyeOf = useMemo(() => {
    const m = new Map<string, string>();
    for (const w of apiWells) if (w.dye && !m.has(w.target)) m.set(w.target, w.dye);
    return m;
  }, [apiWells]);

  return (
    <Card as="section" aria-labelledby={`plate-${sid}`}>
      <CardHeader
        id={`plate-${sid}`}
        title="Plate map"
        hint={`Wells by sample type, ${roleWords}.`}
      />
      <CardBody className="flex flex-col gap-3">
        {runs.length > 1 ? (
          <Select
            label="Plate"
            value={run ?? data?.run.run_id}
            onValueChange={(v) => {
              setRun(v);
              setClicked(null);
            }}
            options={options}
            size="sm"
          />
        ) : null}
        {data?.multiplex ? (
          <Select
            label="Target shown"
            value={target ?? EVERY_DYE}
            onValueChange={setPickedTarget}
            options={[
              { value: EVERY_DYE, label: "The first curve of each well" },
              ...data.targets.map((t) => ({
                value: t,
                label: t,
                hint: dyeOf.has(t) ? `dye ${dyeOf.get(t)}` : undefined,
              })),
            ]}
            size="sm"
          />
        ) : null}
        {isWarming(plate.error) ? (
          <Warming message="The plate appears when qPilot has read the file." />
        ) : plate.error ? (
          <ErrorPanel error={plate.error} compact onRetry={() => void plate.refetch()} />
        ) : null}
        {!data && plate.isPending ? <LoadingBlock label="Reading the plate" lines={5} /> : null}
        {data ? (
          <>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
              <span className="font-mono text-fg">{data.run.run_id}</span>
              <span aria-hidden>·</span>
              <span>{data.targets.join(", ")}</span>
              {data.multiplex ? <Badge>several dyes per well</Badge> : null}
              {data.runs.some((r) => r.in_design) ? (
                data.run.in_design ? (
                  <Badge tone="accent">in the analysed experiment</Badge>
                ) : (
                  <Badge>not in the analysed experiment</Badge>
                )
              ) : null}
            </div>
            <PlateMap
              wells={wells}
              layer="role"
              label={`Plate ${data.run.run_id}`}
              rows={data.n_rows}
              columns={data.n_cols}
              multiple={picking}
              selected={picking ? picked : clicked ? [clicked] : lit}
              onSelectedChange={(sel) => {
                if (picking) {
                  const labels = new Set(sel);
                  onSelectKeys?.(apiWells.filter((w) => labels.has(w.well)));
                } else setClicked(sel[sel.length - 1] ?? null);
              }}
              onActivate={(label) => {
                const w = byLabel.get(label);
                if (w && onShowProposals) onShowProposals(w);
              }}
              renderDetails={(w) => {
                const id = byLabel.get(w.well)?.sample_text_id;
                const q = id ? quotes(id) : null;
                return q ? `Name in the file: “${visibleText(q.value).slice(0, 80)}”` : null;
              }}
              caption={
                picking
                  ? picked.length
                    ? `${count(picked.length)} well${picked.length === 1 ? "" : "s"} of the selected samples. Shift-click selects a rectangle, ⌘/Ctrl-click adds a well, a row letter or column number the whole row or column; Escape clears.`
                    : "Select wells to select their samples in the editor: click, Shift-click for a rectangle, ⌘/Ctrl-click to add, a row letter or column number for the whole row or column."
                  : clicked
                    ? "The chosen well is outlined; Escape clears it."
                    : lit.length
                      ? `Outlined: the ${count(lit.length)} well${lit.length === 1 ? "" : "s"} the proposal in focus is about.`
                      : "Choose a well for its names (quoted from the file) and the proposals about it; Enter shows them."
              }
            />
            {chosen ? (
              <WellDetail
                well={chosen}
                curves={byKey.get(chosen.key)}
                quotes={quotes}
                onShowProposals={onShowProposals}
                onClose={() => setClicked(null)}
              />
            ) : null}
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}
