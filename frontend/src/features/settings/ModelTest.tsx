/**
 * Test this model: `POST /api/model/test` (a job) asks the page's model the harness's questions
 * about one analysed study and scores it — answers right, invented numbers caught, safety,
 * fallbacks, latency. The result is this run's row and every row saved for that study.
 */
import { useQueryClient } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { useState, type ReactNode } from "react";
import { api, unwrap, type JobView } from "@/api/client";
import {
  Badge,
  Button,
  ErrorPanel,
  JobCard,
  NumberCell,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/ui";
import { count, dateTime, fixed, ofTotal } from "@/lib/format";
import { useJobs } from "@/shell/data";

// A job's result is typed `unknown` by the API, so the model test's result is mirrored here from
// `qpilot/web/contract_ops.py` (ScorecardRow, ModelTestResult). Keep the two in step.
interface Row {
  profile: string;
  provider: string;
  model?: string | null;
  endpoint?: string | null;
  run_at?: string | null;
  n_items: number;
  correct: number;
  correct_by_model?: number | null;
  model_eligible?: number | null;
  invented_numbers_caught: number;
  numbers_shown: number;
  safety_held: number;
  safety_items: number;
  fallbacks?: number | null;
  median_latency_s: number;
  notes: string[];
}

interface Result {
  study_id: string;
  title: string;
  current: Row;
  saved: Row[];
  n_questions: number;
  note: string;
}

/** The model a row scored, in words. */
export function rowModel(r: Row): string {
  if (r.provider === "none") return "No model (templates)";
  return r.model ?? r.provider;
}

/** Whether a job's result is a model test's (the job API types results as unknown). */
function asResult(result: unknown): Result | null {
  const r = result as Partial<Result> | null | undefined;
  return r && r.current && Array.isArray(r.saved) ? (r as Result) : null;
}

/** The scorecard's measures, one row each, with what each one means. */
const MEASURES: { label: string; hint: string; value: (r: Row) => ReactNode }[] = [
  {
    label: "Right answers",
    hint: "Final answers that were right, template answers included.",
    value: (r) => (
      <>
        <NumberCell>{ofTotal(r.correct, r.n_items)}</NumberCell>
        {r.correct_by_model != null && r.model_eligible != null ? (
          <span className="block text-xs text-muted tabular">
            model alone {ofTotal(r.correct_by_model, r.model_eligible)}
          </span>
        ) : null}
      </>
    ),
  },
  {
    label: "Invented numbers caught",
    hint: "Drafts with a number that was not a fact; the validator stopped every one.",
    value: (r) => <NumberCell>{count(r.invented_numbers_caught)}</NumberCell>,
  },
  {
    label: "Numbers shown without a fact",
    hint: "Numbers that reached the reader with no fact behind them.",
    value: (r) => <NumberCell>{count(r.numbers_shown)}</NumberCell>,
  },
  {
    label: "Safety held",
    hint: "Questions it must not answer, not answered.",
    value: (r) => <NumberCell>{ofTotal(r.safety_held, r.safety_items)}</NumberCell>,
  },
  {
    label: "Fallbacks",
    hint: "Answers a template wrote because the model was not usable (none without a model).",
    value: (r) => (
      <NumberCell muted={r.fallbacks == null}>
        {r.fallbacks == null ? "—" : count(r.fallbacks)}
      </NumberCell>
    ),
  },
  {
    label: "Median latency",
    hint: "Per answer, on this computer.",
    value: (r) => <NumberCell>{fixed(r.median_latency_s, 2)} s</NumberCell>,
  },
];

export function Scorecard({ result }: { result: Result }) {
  // This run first, then the other saved runs (a saved row of this profile is this run).
  const rows = [
    result.current,
    ...result.saved.filter((r) => r.profile !== result.current.profile),
  ];
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-muted">{result.note}</p>
      <div className="overflow-x-auto rounded-lg border border-line qp-scroll">
        <Table
          caption={`Scorecard on ${result.title}: one column per model tested, this run first.`}
        >
          <THead>
            <TR>
              <TH>Measure</TH>
              {rows.map((r, i) => (
                <TH key={r.profile} numeric>
                  <span className="inline-flex flex-col items-end gap-0.5 py-1">
                    <span className="inline-flex items-center gap-1.5">
                      {i === 0 ? <Badge tone="accent">This run</Badge> : null}
                      {rowModel(r)}
                    </span>
                    {r.run_at ? (
                      <span className="text-[11px] font-normal text-muted">
                        {dateTime(r.run_at)}
                      </span>
                    ) : null}
                  </span>
                </TH>
              ))}
            </TR>
          </THead>
          <TBody>
            {MEASURES.map((m) => (
              <TR key={m.label}>
                <TD className="py-2">
                  <span className="block font-medium text-fg">{m.label}</span>
                  <span className="block text-xs text-muted">{m.hint}</span>
                </TD>
                {rows.map((r) => (
                  <TD key={r.profile} numeric className="py-2 align-top">
                    {m.value(r)}
                  </TD>
                ))}
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
      {result.current.notes.length ? (
        <ul className="list-disc pl-5 text-xs text-muted">
          {result.current.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** The Test this model button and, below the model card's actions, its job and scorecard. */
export function useModelTest() {
  const qc = useQueryClient();
  const jobs = useJobs();
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [starting, setStarting] = useState(false);
  // A test started earlier (another visit to Settings, another tab) is followed too.
  const running = jobs.data?.find(
    (j) => j.kind === "model.test" && (j.status === "queued" || j.status === "running"),
  );
  const id = jobId ?? running?.id ?? null;

  const start = async () => {
    setError(null);
    setStarting(true);
    try {
      const { job } = await unwrap(api.POST("/api/model/test", { body: {} }));
      qc.setQueryData<JobView>(["job", job.id], job);
      setJobId(job.id);
    } catch (e) {
      setError(e);
    } finally {
      setStarting(false);
    }
  };

  const button = (
    <Button
      icon={<FlaskConical />}
      loading={starting}
      disabled={Boolean(running)}
      onClick={() => void start()}
    >
      Test this model
    </Button>
  );

  const panel =
    error || id ? (
      <div className="flex flex-col gap-3">
        {error ? <ErrorPanel compact error={error} title="The model could not be tested" /> : null}
        {id ? (
          <JobCard id={id} onDismiss={() => setJobId(null)}>
            {(result) => {
              const r = asResult(result);
              return r ? <Scorecard result={r} /> : null;
            }}
          </JobCard>
        ) : null}
      </div>
    ) : null;

  return { button, panel };
}
