/**
 * The Curves stage of a file of Cq values only (docs/cq-tables.md): there is no curve to fit or
 * judge, so the stage confirms the Cq table instead. Each sample's wells on each plate with the
 * Cq the file gives them, the wells without a Cq, the replicate sets wider than the Run Gate's
 * rule G-REP expects (its own numbers) and each assay's efficiency (its dilution series, else
 * assumed 2.0), with the curve-based checks that do not apply said in plain words. Blind like
 * the rest of the stage: the server never sends a group, a fold change or a p-value here.
 */
import { CheckCircle2, TableProperties } from "lucide-react";
import { useMemo, useState } from "react";
import { count, fixed, plural } from "@/lib/format";
import { ROLE_SHORT } from "@/lib/vocab";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorPanel,
  LoadingBlock,
  SegmentedControl,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/ui";
import { useCqTable, type CqSetView, type CqTableView } from "./api";

type Show = "look" | "all";

/** The replicate sets to look at first: a flag or a spread wider than expected. */
export function setsToLook(sets: readonly CqSetView[]): CqSetView[] {
  return sets.filter((s) => s.spread === "outside" || s.flags.length > 0);
}

/** One line on what the table holds and what to look at (every number the server's). */
export function cqTableSummary(view: CqTableView): string {
  const c = view.counts;
  if (!c) return view.message;
  const parts = [
    `${plural(c.n_wells, "well")} on the analysed plates, ${count(c.n_with_cq)} with a Cq`,
    `${plural(c.n_study_without_cq, "study well")} without a Cq`,
    `${plural(c.n_outside, "replicate set")} wider than expected`,
  ];
  if (c.n_late) parts.push(`${plural(c.n_late, "well")} with a Cq above 35`);
  if (c.n_controls_with_cq)
    parts.push(`${plural(c.n_controls_with_cq, "negative-control well")} with a Cq`);
  return `${parts.join(" · ")}.`;
}

function CqCell({ set }: { set: CqSetView }) {
  return (
    <span className="flex flex-wrap gap-1">
      {set.wells.map((w) => (
        <span
          key={w.key}
          title={`${w.key}${w.file_excluded ? ` · excluded in the file: ${w.file_excluded}` : ""}`}
          className={
            "rounded border border-line px-1 font-mono text-[12px] tabular " +
            (w.left_out ? "text-faint line-through" : w.cq == null ? "text-warn" : "text-fg")
          }
        >
          <span className="sr-only">{`well ${w.well}: `}</span>
          {w.cq == null ? "no Cq" : fixed(w.cq, 2)}
          {w.left_out ? <span className="sr-only"> (left out by a person)</span> : null}
        </span>
      ))}
    </span>
  );
}

function SpreadCell({ set }: { set: CqSetView }) {
  if (set.spread === "not_evaluated")
    return <span className="text-[12.5px] text-muted">{set.spread_words}</span>;
  return (
    <span className="flex flex-col gap-0.5">
      <span className="flex items-center gap-2">
        <span className="font-mono text-[12.5px] tabular">
          {set.range_cq == null ? "—" : `${fixed(set.range_cq, 2)} cycles`}
        </span>
        <Badge tone={set.spread === "outside" ? "warn" : "ok"}>
          {set.spread === "outside" ? "wider than expected" : "within"}
        </Badge>
      </span>
      <span className="text-[12px] text-muted">{set.spread_words}</span>
    </span>
  );
}

/** The Cq table to confirm in the curves stage of a Cq-only file. */
export function CqTablePanel({ sid }: { sid: string }) {
  const table = useCqTable(sid);
  const [show, setShow] = useState<Show>("look");
  const view = table.data;
  const look = useMemo(() => setsToLook(view?.sets ?? []), [view?.sets]);
  if (table.isPending) return <LoadingBlock label="Reading the Cq table" lines={5} />;
  if (table.error)
    return (
      <ErrorPanel error={table.error} title="The Cq table" onRetry={() => void table.refetch()} />
    );
  if (!view?.cq_only) return null;
  const rows = show === "look" ? look : view.sets;
  return (
    <Card as="section" aria-labelledby="cq-table-title">
      <CardHeader
        id="cq-table-title"
        title="Your Cq table"
        hint="No curve to judge: the Cq of every well, as the file gives it. Blind: no group, fold change or p-value."
        actions={
          view.shown ? (
            <SegmentedControl
              label="Which replicate sets to show"
              size="sm"
              value={show}
              onValueChange={(v) => setShow(v as Show)}
              options={[
                { value: "look", label: `To look at (${count(look.length)})` },
                { value: "all", label: `All (${count(view.sets.length)})` },
              ]}
            />
          ) : null
        }
      />
      <CardBody className="flex flex-col gap-4">
        <p className="text-[13px] text-fg">{view.message}</p>
        {view.counts ? <p className="text-[13px] text-muted">{cqTableSummary(view)}</p> : null}
        {view.efficiencies.length ? (
          <div className="text-[13px]">
            <p className="font-medium text-fg">Efficiency of each assay</p>
            <ul className="mt-1 list-disc pl-5 text-muted" aria-label="Efficiency of each assay">
              {view.efficiencies.map((e) => (
                <li key={e.target}>
                  {e.words}{" "}
                  <Badge tone={e.source === "assumed" ? "warn" : "info"}>
                    {e.source === "assumed" ? "assumed" : "dilution series"}
                  </Badge>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {view.not_applicable.length ? (
          <div className="text-[13px]">
            <p className="font-medium text-fg">What needs curves, and so does not apply here</p>
            <ul className="mt-1 list-disc pl-5 text-muted" aria-label="Checks that do not apply">
              {view.not_applicable.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {!view.shown ? null : rows.length ? (
          <div className="overflow-x-auto">
            <Table caption="The Cq table: each sample's wells on each plate">
              <THead>
                <TR>
                  <TH>Plate</TH>
                  <TH>Sample</TH>
                  <TH>Target</TH>
                  <TH>Type</TH>
                  <TH>Cq per well</TH>
                  <TH numeric>Mean Cq</TH>
                  <TH>Replicate spread (G-REP)</TH>
                  <TH>To look at</TH>
                </TR>
              </THead>
              <TBody>
                {rows.map((s) => (
                  <TR key={`${s.run_id}|${s.target}|${s.sample}`}>
                    <TD className="font-mono text-[12.5px]">{s.run_id}</TD>
                    <TD>{s.sample}</TD>
                    <TD>{s.target}</TD>
                    <TD>{ROLE_SHORT[s.role] ?? s.role}</TD>
                    <TD>
                      <CqCell set={s} />
                    </TD>
                    <TD numeric>{s.mean_cq == null ? "—" : fixed(s.mean_cq, 2)}</TD>
                    <TD>
                      <SpreadCell set={s} />
                    </TD>
                    <TD className="text-[12.5px] text-muted">
                      {s.flags.length ? s.flags.join("; ") : "—"}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
        ) : (
          <EmptyState compact icon={<CheckCircle2 />} title="Nothing to look at">
            Every replicate set is within its expected spread, and every study well has a Cq. Show
            all to read the whole table.
          </EmptyState>
        )}
        {view.shown && view.rule ? (
          <p className="flex gap-2 text-[12px] text-faint">
            <TableProperties className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            <span>G-REP: {view.rule}</span>
          </p>
        ) : null}
      </CardBody>
    </Card>
  );
}
