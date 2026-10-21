/**
 * The lookback: pick an analysed study, an instrument and the first and last day, and qPilot
 * analyses the study again without the runs in that window (a job) and says which conclusions
 * change: "changes k of N conclusions", the genes (before → after), the runs and wells in the
 * window, and, when no run-to-instrument map was recorded, that every run counted as on that
 * instrument. Nothing is saved.
 */
import { History, Info } from "lucide-react";
import { useState, type FormEvent } from "react";
import { plural } from "@/lib/format";
import { useWorkspaces } from "@/shell/data";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  ConclusionTag,
  ErrorPanel,
  Field,
  Input,
  JobCard,
  LoadingBlock,
  Select,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/ui";
import { FactSource, FactText } from "@/features/results/FactText";
import { useStartLookback, type InstrumentSummary, type LookbackView } from "./api";
import { day, lookbackHeadline } from "./words";

function isLookback(result: unknown): result is LookbackView {
  const r = result as Partial<LookbackView> | null | undefined;
  return Boolean(r && typeof r.status === "string" && r.text && Array.isArray(r.changed));
}

/** The caveat when no run-to-instrument map was recorded for the study. */
export function AssumedCaveat({ instrument }: { instrument: string }) {
  return (
    <p
      role="note"
      className="flex gap-2 rounded-lg border border-info/30 bg-info-soft/50 p-3 text-[13px] text-fg"
    >
      <Info className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
      <span>
        No record says which instrument ran each of this study&rsquo;s plates, so every run was
        counted as run on {instrument}. Only the runs dated inside the window were left out.
      </span>
    </p>
  );
}

/** What the lookback found (a job's result). */
export function LookbackResult({
  view,
  instrumentName,
}: {
  view: LookbackView;
  instrumentName?: string;
}) {
  const name = instrumentName ?? view.instrument_id;
  return (
    <div className="flex flex-col gap-3">
      <div>
        <p className="text-base font-semibold text-fg tabular">{lookbackHeadline(view)}</p>
        <p className="text-[13px] text-muted">
          {name}, {day(view.start)}
          {view.end !== view.start ? ` to ${day(view.end)}` : ""}: leaving out the study&rsquo;s
          runs in the window.
        </p>
      </div>
      {view.assumed_all_runs ? <AssumedCaveat instrument={name} /> : null}
      <div className="text-[13px] whitespace-pre-line text-fg">
        <FactText text={view.text} />
      </div>
      <FactSource text={view.text} />
      {view.changed.length ? (
        <div className="overflow-x-auto rounded-lg border border-line">
          <Table caption="Conclusions that change when the window's runs are left out">
            <THead>
              <TR>
                <TH>Gene</TH>
                <TH>With every run</TH>
                <TH>Without the window&rsquo;s runs</TH>
              </TR>
            </THead>
            <TBody>
              {view.changed.map((c) => (
                <TR key={c.gene}>
                  <TD className="font-medium">{c.gene}</TD>
                  <TD>
                    <ConclusionTag conclusion={c.before} long />
                  </TD>
                  <TD>
                    <span className="sr-only">changes to </span>
                    <ConclusionTag conclusion={c.after} long />
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
      ) : null}
      <div className="text-[13px]">
        <p className="text-fg">
          <span className="tabular">{plural(view.runs_in_window.length, "run")}</span> and{" "}
          <span className="tabular">{plural(view.n_wells_in_window, "well")}</span> in the window
          {view.runs_in_window.length ? ":" : "."}
        </p>
        {view.runs_in_window.length ? (
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {view.runs_in_window.map((r) => (
              <li
                key={r}
                className="rounded-md border border-line bg-surface-2 px-1.5 font-mono text-xs text-fg"
              >
                {r}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <p className="text-xs text-muted">
        Nothing was saved: the study, its decisions and the logbook are as they were.
      </p>
    </div>
  );
}

/** The lookback card: choose, run (a job), read. `instrumentId` fixes the instrument. */
export function LookbackCard({
  instruments,
  instrumentId: fixedInstrument,
}: {
  instruments: readonly InstrumentSummary[];
  instrumentId?: string;
}) {
  const workspaces = useWorkspaces();
  const start = useStartLookback();
  const studies = (workspaces.data ?? []).filter((w) => w.results_visible && w.study_id);
  const unique = studies.filter(
    (w, i) => studies.findIndex((o) => o.study_id === w.study_id) === i,
  );
  const [study, setStudy] = useState<string | undefined>(undefined);
  const [instrument, setInstrument] = useState<string | undefined>(fixedInstrument);
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [tried, setTried] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);

  const chosenStudy = study ?? (unique.length === 1 ? unique[0]!.study_id! : undefined);
  const chosenInstrument = fixedInstrument ?? instrument;
  const name =
    instruments.find((i) => i.instrument_id === chosenInstrument)?.display_name ??
    chosenInstrument ??
    "";

  const errors = {
    study: tried && !chosenStudy ? "Choose an analysed study." : null,
    instrument: tried && !chosenInstrument ? "Choose an instrument." : null,
    first: tried && !first ? "Give the first day." : null,
    last:
      tried && !last
        ? "Give the last day."
        : tried && first && last && last < first
          ? "The last day is on or after the first."
          : null,
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (!chosenStudy || !chosenInstrument || !first || !last || last < first) return;
    setJobId(null);
    start.mutate(
      { studyId: chosenStudy, instrumentId: chosenInstrument, start: first, end: last },
      { onSuccess: (started) => setJobId(started.job.id) },
    );
  };

  return (
    <Card as="section" aria-labelledby={fixedInstrument ? "instr-lookback-one" : "instr-lookback"}>
      <CardHeader
        id={fixedInstrument ? "instr-lookback-one" : "instr-lookback"}
        title="Lookback"
        hint="Which of a study's conclusions used this instrument in a period, and whether leaving those runs out changes them. Nothing is saved."
      />
      <CardBody>
        <form onSubmit={submit} noValidate className="flex flex-col gap-4">
          <Field
            label="Study"
            error={errors.study}
            hint={
              !workspaces.isLoading && !unique.length
                ? "No study has results to look back over yet: open one and confirm its design and curves."
                : undefined
            }
          >
            <Select
              value={chosenStudy}
              onValueChange={setStudy}
              placeholder="Choose an analysed study"
              options={unique.map((w) => ({
                value: w.study_id!,
                label: w.title,
                hint: w.n_genes ? plural(w.n_genes, "gene") : undefined,
              }))}
              disabled={!unique.length}
            />
          </Field>
          {fixedInstrument ? null : (
            <Field
              label="Instrument"
              error={errors.instrument}
              hint={!instruments.length ? "Register an instrument first." : undefined}
            >
              <Select
                value={instrument}
                onValueChange={setInstrument}
                placeholder="Choose an instrument"
                options={instruments.map((i) => ({
                  value: i.instrument_id,
                  label: i.display_name,
                  hint: i.make_model || undefined,
                }))}
                disabled={!instruments.length}
              />
            </Field>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="First day" error={errors.first}>
              <Input
                type="date"
                value={first}
                onChange={(e) => setFirst(e.target.value)}
                required
              />
            </Field>
            <Field label="Last day" hint="Included." error={errors.last}>
              <Input type="date" value={last} onChange={(e) => setLast(e.target.value)} required />
            </Field>
          </div>
          <div>
            <Button type="submit" icon={<History />} loading={start.isPending}>
              Look back
            </Button>
          </div>
        </form>
        {start.error ? (
          <ErrorPanel
            error={start.error}
            title="The lookback could not start"
            compact
            className="mt-4"
          />
        ) : null}
        {jobId ? (
          <JobCard id={jobId} className="mt-4" onDismiss={() => setJobId(null)}>
            {(result) =>
              // The live "done" event can arrive a moment before the result is read.
              isLookback(result) ? (
                <LookbackResult view={result} instrumentName={name || undefined} />
              ) : (
                <LoadingBlock label="Reading the lookback's answer" lines={3} />
              )
            }
          </JobCard>
        ) : null}
        {!jobId && !start.isPending && !start.error ? (
          <p className="mt-3 text-xs text-muted">
            Run dates come from the study&rsquo;s own files: the instrument&rsquo;s clock, or the
            date in a run&rsquo;s name.
          </p>
        ) : null}
      </CardBody>
    </Card>
  );
}
