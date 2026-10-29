/**
 * The curve viewer of the Curves stage: the chosen wells' raw fluorescence by cycle, with each
 * well's Cq and baseline, the other wells of the same sample faint, and the well's call under
 * every rule (LinRegPCR, the Cq cut-offs, the Curve Judge). Facts about curves, never a group.
 */
import { Activity, X } from "lucide-react";
import { useMemo, useState } from "react";
import { CurveViewer, curvesOf, type CurveScale } from "@/charts/curves";
import { count, fixed } from "@/lib/format";
import { ruleLabel, ruleWords } from "@/lib/vocab";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorPanel,
  IconButton,
  LoadingBlock,
  NumberCell,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/ui";
import { useCurveCalls, useCurves, type CurveCallsView, type CurveView } from "./api";

/** At most this many wells are drawn together (each is one request). */
export const MAX_CURVES = 12;

export function CurvePanel({
  sid,
  run,
  wells,
  onClear,
  waitingProposal,
  onShowProposal,
  gene = null,
}: {
  sid: string;
  run: string | null;
  wells: readonly string[];
  onClear: () => void;
  /** The gene picked on the plate: in a multiplex well, its curve is the one shown. */
  gene?: string | null;
  /** Whether a proposal about this well (`run_id/well`) waits in the inbox. */
  waitingProposal?: (key: string) => boolean;
  /** Show that proposal in the inbox. */
  onShowProposal?: (key: string) => void;
}) {
  const [scale, setScale] = useState<CurveScale>("linear");
  const joined = wells.slice(0, MAX_CURVES).join(",");
  const keys = useMemo(
    () => (run && joined ? joined.split(",").map((w) => `${run}/${w}`) : []),
    [run, joined],
  );
  const curves = useCurves(sid, keys, gene);
  const views = curves.data;
  const series = useMemo(() => curvesOf(views), [views]);
  const one = views.length === 1 ? views[0]! : null;
  const target = one?.target ?? null;
  const calls = useCurveCalls(sid, target);

  const title = !wells.length
    ? "The curve"
    : wells.length === 1
      ? `Well ${wells[0]}`
      : `${count(Math.min(wells.length, MAX_CURVES))} wells`;
  const hint = one
    ? `Sample ${one.sample} · ${one.target} · plate ${one.run_id}`
    : wells.length
      ? `Plate ${run}${wells.length > MAX_CURVES ? ` · the first ${MAX_CURVES} of ${count(wells.length)} chosen wells` : ""}`
      : "Raw fluorescence by cycle for the wells you pick on the plate.";

  return (
    <Card as="section" aria-labelledby="curves-curve-title">
      <CardHeader
        id="curves-curve-title"
        title={title}
        hint={hint}
        actions={
          wells.length ? (
            <IconButton label="Clear the chosen wells" size="sm" onClick={onClear}>
              <X />
            </IconButton>
          ) : null
        }
      />
      <CardBody>
        {!wells.length ? (
          <EmptyState compact icon={<Activity />} title="Pick a well on the plate">
            Its raw curve shows here with its Cq and baseline, next to the other wells of the same
            sample. ⌘/Ctrl-click or Shift-click to compare several wells.
          </EmptyState>
        ) : curves.error && !views.length ? (
          <ErrorPanel error={curves.error} onRetry={curves.refetch} compact />
        ) : curves.pending && !views.length ? (
          <LoadingBlock
            label="Reading the curves from the file (the first one can take a few seconds)"
            lines={7}
          />
        ) : (
          <div className="flex flex-col gap-4">
            <CurveViewer
              series={series}
              yLabel="Fluorescence (raw)"
              label={
                one
                  ? `Well ${one.well} of plate ${one.run_id}`
                  : `${views.length} wells of plate ${run}`
              }
              scale={scale}
              onScaleChange={setScale}
              caption={views[0]?.note}
            />
            {one ? (
              <OneWell
                view={one}
                calls={calls.data}
                onShowProposal={
                  onShowProposal && waitingProposal?.(one.key)
                    ? () => onShowProposal(one.key)
                    : undefined
                }
              />
            ) : (
              <ManyWells views={views} />
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function yesNo(v: boolean | null | undefined): string {
  return v === true ? "amplified" : v === false ? "not amplified" : "no call";
}

function OneWell({
  view,
  calls,
  onShowProposal,
}: {
  view: CurveView;
  calls: CurveCallsView | undefined;
  onShowProposal?: () => void;
}) {
  const row = calls?.wells.find((w) => w.run_id === view.run_id && w.well === view.well);
  const facts: [string, string][] = [
    ["Cq", fixed(view.cq, 2)],
    ["Efficiency", fixed(view.efficiency, 2)],
    ["R²", fixed(view.r2, 4)],
    // LinRegPCR's baseline is in the file's own fluorescence units (RFU on most instruments)
    [
      "Baseline",
      view.baseline == null ? fixed(view.baseline, 3) : `${fixed(view.baseline, 3)} RFU`,
    ],
  ];
  return (
    <div className="flex flex-col gap-3">
      {!view.numbers_shown ? (
        <p className="text-[13px] text-muted">
          Cq, baseline and the calls are shown once the design is confirmed.
        </p>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-[13px] sm:grid-cols-4">
            {facts.map(([k, v]) => (
              <div key={k} className="flex flex-col">
                <dt className="text-[12px] text-muted">{k}</dt>
                <dd className="m-0 font-mono text-fg tabular">{v}</dd>
              </div>
            ))}
          </dl>
          <div>
            <h3 className="mb-1.5 text-[13px] font-medium text-fg">
              This well under each amplification rule
            </h3>
            {row && calls ? (
              <ul className="flex flex-wrap gap-1.5">
                {calls.rules.map((r) => {
                  const v = row.calls[r];
                  const short = ruleLabel(r);
                  const long =
                    calls.rule_labels[r] && calls.rule_labels[r] !== r
                      ? calls.rule_labels[r]
                      : ruleWords(r);
                  return (
                    <li key={r}>
                      <Badge
                        tone={v === true ? "ok" : v === false ? "danger" : "neutral"}
                        title={long}
                      >
                        <span aria-hidden>{v === true ? "●" : v === false ? "✕" : "–"}</span>
                        {short}
                        <span className="sr-only">: {yesNo(v)}</span>
                      </Badge>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="text-[12px] text-muted">
                LinRegPCR: {yesNo(view.amplified)} ·{" "}
                {view.judge == null
                  ? "Curve Judge has not looked at this well yet"
                  : `Curve Judge: ${yesNo(view.judge)}`}
              </p>
            )}
            {view.judge != null && view.amplified != null && view.judge !== view.amplified ? (
              <p className="mt-2 text-[13px] text-fg">
                The Curve Judge reads this curve as {yesNo(view.judge)}; LinRegPCR’s call in use
                says {yesNo(view.amplified)}.
              </p>
            ) : null}
          </div>
        </>
      )}
      {onShowProposal ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-warn/30 bg-warn-soft/60 px-3 py-2 text-[13px] text-fg">
          <span>A proposal about this well’s call is waiting for you.</span>
          <Button size="sm" variant="secondary" className="ml-auto" onClick={onShowProposal}>
            Show its proposal
          </Button>
        </div>
      ) : null}
      {view.replicates.length === 0 ? (
        <p className="text-[12px] text-muted">
          This sample has no other well for {view.target} on this plate.
        </p>
      ) : null}
    </div>
  );
}

function ManyWells({ views }: { views: CurveView[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <Table caption="The chosen wells">
        <THead>
          <TR>
            <TH>Well</TH>
            <TH>Sample</TH>
            <TH>Target</TH>
            <TH>LinRegPCR</TH>
            <TH>Curve Judge</TH>
            <TH numeric>Cq</TH>
            <TH numeric>Efficiency</TH>
            <TH numeric>R²</TH>
          </TR>
        </THead>
        <TBody>
          {views.map((v) => (
            <TR key={v.key}>
              <TD className="font-mono">{v.well}</TD>
              <TD>{v.sample}</TD>
              <TD>{v.target}</TD>
              <TD>{v.numbers_shown ? yesNo(v.amplified) : "—"}</TD>
              <TD>{v.numbers_shown ? (v.judge == null ? "—" : yesNo(v.judge)) : "—"}</TD>
              <TD numeric>
                <NumberCell>{fixed(v.cq, 2)}</NumberCell>
              </TD>
              <TD numeric>
                <NumberCell>{fixed(v.efficiency, 2)}</NumberCell>
              </TD>
              <TD numeric>
                <NumberCell>{fixed(v.r2, 4)}</NumberCell>
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}
