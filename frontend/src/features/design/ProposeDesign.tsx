/**
 * "Propose the design": the rules (always) and the model (when one answers) read the file's
 * names and propose; nothing is decided. A job, with its report in words when done.
 */
import { useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useRef, useState } from "react";
import { api, unwrap, type JobView } from "@/api/client";
import { count } from "@/lib/format";
import { useFocusTarget } from "@/shell/actions";
import { refreshWorkspace, reportWriteError } from "@/shell/writes";
import { Button, Dialog, Field, JobCard, Textarea } from "@/ui";

const MAX_SENTENCE = 500;
export const PROPOSE_LABEL = "Propose the design";

interface Report {
  message?: string;
  proposed?: string[];
  refused?: { subject?: string | null; reason?: string | null }[];
  notes?: string[];
  fallback?: boolean | null;
  model_error?: string | null;
}

/** The report of a finished propose job, in words. */
export function ProposeReportView({ result }: { result: unknown }) {
  const r = (result ?? {}) as Report;
  return (
    <div className="flex flex-col gap-1.5 text-[13px]">
      {r.message ? <p className="text-fg">{r.message}</p> : null}
      {r.notes?.length ? (
        <ul className="list-disc pl-5 text-muted">
          {r.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}
      {r.refused?.length ? (
        <details className="text-muted">
          <summary className="cursor-pointer">
            {count(r.refused.length)} proposal{r.refused.length === 1 ? " was" : "s were"} refused before it reached the inbox
          </summary>
          <ul className="mt-1 list-disc pl-5">
            {r.refused.map((x, i) => (
              <li key={i}>
                {x.subject ? <span className="font-mono text-xs text-fg">{x.subject}</span> : null}
                {x.subject ? ": " : ""}
                {x.reason}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

/** Start the propose job (with the optional sentence); returns the started job. */
function useProposeDesign(sid: string) {
  const qc = useQueryClient();
  const [job, setJob] = useState<JobView | null>(null);
  const [busy, setBusy] = useState(false);
  const start = async (sentence: string) => {
    setBusy(true);
    try {
      const body = sentence.trim() ? { sentence: sentence.trim() } : {};
      const started = await unwrap(api.POST("/api/sessions/{sid}/propose/design", { params: { path: { sid } }, body }));
      setJob(started.job);
      void refreshWorkspace(qc, sid);
    } catch (err) {
      reportWriteError(qc, err, sid);
    } finally {
      setBusy(false);
    }
  };
  return { job, setJob, busy, start };
}

/** The empty inbox: what proposing does, the optional sentence, and the button. */
export function ProposeDesignPanel({ sid, running }: { sid: string; running?: JobView | null }) {
  const [sentence, setSentence] = useState("");
  const { job, setJob, busy, start } = useProposeDesign(sid);
  const button = useRef<HTMLButtonElement>(null);
  useFocusTarget(PROPOSE_LABEL, button);
  const shown = job ?? running ?? null;
  return (
    <section
      aria-labelledby="propose-design"
      className="flex flex-col gap-4 rounded-xl border border-dashed border-line-strong bg-surface px-5 py-6 sm:px-8 sm:py-8"
    >
      <div className="flex items-start gap-3">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent-strong" aria-hidden>
          <Sparkles className="size-5" />
        </div>
        <div className="min-w-0">
          <h2 id="propose-design" className="text-base font-semibold text-fg">
            Ask for proposals on the design
          </h2>
          <p className="mt-1 max-w-prose text-[13px] text-muted">
            qPilot's rules read the names in the file (and the model reads them too, when one answers): what each sample
            is, the groups, the biological units, the reference genes, the gene symbols. Each becomes a proposal the
            engine checks; nothing is decided until you accept it. No result is shown until you confirm the design and
            the curves.
          </p>
        </div>
      </div>
      {shown ? (
        <JobCard id={shown.id} onDismiss={job ? () => setJob(null) : undefined}>
          {(result) => <ProposeReportView result={result} />}
        </JobCard>
      ) : (
        <>
          <Field
            label="One sentence about the experiment"
            optional
            htmlFor={`sentence-${sid}`}
            hint="E.g. what was compared. It is kept as quoted text: the model reads it as data, never as an instruction. Leave it empty to use the one given when the file was opened."
          >
            <Textarea
              id={`sentence-${sid}`}
              value={sentence}
              onChange={(e) => setSentence(e.target.value)}
              maxLength={MAX_SENTENCE}
              showCount
              rows={2}
            />
          </Field>
          <div>
            <Button ref={button} variant="primary" size="lg" icon={<Sparkles />} loading={busy} onClick={() => void start(sentence)} data-action={PROPOSE_LABEL}>
              {PROPOSE_LABEL}
            </Button>
          </div>
        </>
      )}
    </section>
  );
}

/** "Propose again…" once proposals exist: same job, in a dialog. */
export function ProposeAgain({ sid, disabled }: { sid: string; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const [sentence, setSentence] = useState("");
  const { job, setJob, busy, start } = useProposeDesign(sid);
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) setJob(null);
      }}
      trigger={
        <Button variant="ghost" icon={<Sparkles />} disabled={disabled}>
          Propose again…
        </Button>
      }
      title="Propose the design again"
      description="The rules and the model read the file again. New proposals join the inbox; what you already decided stays decided, and a repeat of a decided proposal is refused."
      footer={
        job ? (
          <Button variant="secondary" onClick={() => setOpen(false)}>
            Close
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" loading={busy} onClick={() => void start(sentence)}>
              {PROPOSE_LABEL}
            </Button>
          </>
        )
      }
    >
      {job ? (
        <JobCard id={job.id}>{(result) => <ProposeReportView result={result} />}</JobCard>
      ) : (
        <Field label="One sentence about the experiment" optional htmlFor={`again-${sid}`}>
          <Textarea id={`again-${sid}`} value={sentence} onChange={(e) => setSentence(e.target.value)} maxLength={MAX_SENTENCE} showCount rows={2} />
        </Field>
      )}
    </Dialog>
  );
}
