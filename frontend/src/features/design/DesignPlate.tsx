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
import { PlateMap, plateWells } from "@/charts/plate";
import { count } from "@/lib/format";
import { ROLE_WORDS } from "@/lib/vocab";
import { Badge, Button, Card, CardBody, CardHeader, ErrorPanel, IconButton, LoadingBlock, Select } from "@/ui";
import { Quote, visibleText, type QuoteLookup } from "@/ui/proposal";

export type PlateWell = Schemas["PlateWell"];
type PlateView = Schemas["PlateView"];

export function usePlate(sid: string, run: string | null) {
  return useQuery({
    queryKey: ["w", sid, "plate", run ?? ""],
    queryFn: () => unwrap(api.GET("/api/sessions/{sid}/plate", { params: { path: { sid }, query: run ? { run } : {} } })),
    placeholderData: (prev) => prev,
  });
}

function WellDetail({
  well,
  quotes,
  onShowProposals,
  onClose,
}: {
  well: PlateWell;
  quotes: QuoteLookup;
  onShowProposals?: (w: PlateWell) => void;
  onClose: () => void;
}) {
  const sampleQuote = well.sample_text_id ? quotes(well.sample_text_id) : null;
  const targetQuote = well.target_text_id ? quotes(well.target_text_id) : null;
  return (
    <div className="flex flex-col gap-2.5 rounded-lg border border-line bg-surface-2 p-3 text-[13px]" aria-live="polite">
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
        <dd className="min-w-0">{sampleQuote ? <Quote entry={sampleQuote} /> : <span className="font-mono">{well.sample}</span>}</dd>
        <dt className="text-muted">Target</dt>
        <dd className="min-w-0">{targetQuote ? <Quote entry={targetQuote} /> : <span className="font-mono">{well.target}</span>}</dd>
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
        <Button size="sm" variant="secondary" onClick={() => onShowProposals(well)} className="self-start">
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
}: {
  sid: string;
  /** Every plate in the file (from the workspace summary), for the picker. */
  runs: Schemas["InspectRun"][];
  quotes: QuoteLookup;
  /** Which wells the proposal in focus is about (outlined). */
  highlight?: ((w: PlateWell) => boolean) | null;
  onShowProposals?: (w: PlateWell) => void;
}) {
  const [run, setRun] = useState<string | null>(null);
  const [clicked, setClicked] = useState<string | null>(null);
  const plate = usePlate(sid, run);
  const data: PlateView | undefined = plate.data;
  const apiWells = useMemo(() => data?.wells ?? [], [data]);
  const byLabel = useMemo(() => new Map(apiWells.map((w) => [w.well, w])), [apiWells]);
  const wells = useMemo(() => {
    if (!data) return [];
    const instructionLike = (id: string | null | undefined) => Boolean(id && quotes(id)?.flags.includes("instruction_like"));
    return plateWells(data, { flagged: (w) => instructionLike(w.sample_text_id) || instructionLike(w.target_text_id) });
  }, [data, quotes]);
  const lit = useMemo(() => (highlight ? apiWells.filter(highlight).map((w) => w.well) : []), [apiWells, highlight]);
  const chosen = clicked ? (byLabel.get(clicked) ?? null) : null;

  const options = runs.map((r) => ({
    value: r.run_id,
    label: r.run_id,
    hint: `${r.experiment_id} · ${count(r.n_wells)} wells · ${r.targets.join(", ")}`,
  }));
  const roleWords = apiWells.some((w) => w.role) ? "as the design assembled so far has them" : "as declared in the file";

  return (
    <Card as="section" aria-labelledby={`plate-${sid}`}>
      <CardHeader id={`plate-${sid}`} title="Plate map" hint={`Wells by sample type, ${roleWords}.`} />
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
        {plate.error ? <ErrorPanel error={plate.error} compact onRetry={() => void plate.refetch()} /> : null}
        {!data && plate.isPending ? <LoadingBlock label="Reading the plate" lines={5} /> : null}
        {data ? (
          <>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
              <span className="font-mono text-fg">{data.run.run_id}</span>
              <span aria-hidden>·</span>
              <span>{data.targets.join(", ")}</span>
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
              multiple={false}
              selected={clicked ? [clicked] : lit}
              onSelectedChange={(sel) => setClicked(sel[sel.length - 1] ?? null)}
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
                clicked
                  ? "The chosen well is outlined; Escape clears it."
                  : lit.length
                    ? `Outlined: the ${count(lit.length)} well${lit.length === 1 ? "" : "s"} the proposal in focus is about.`
                    : "Choose a well for its names (quoted from the file) and the proposals about it; Enter shows them."
              }
            />
            {chosen ? (
              <WellDetail well={chosen} quotes={quotes} onShowProposals={onShowProposals} onClose={() => setClicked(null)} />
            ) : null}
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}
