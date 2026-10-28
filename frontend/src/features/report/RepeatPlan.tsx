/**
 * What to repeat and why (`GET …/review/repeat`, `qpilot/qpcr/repeat.py`): per sample × gene,
 * every reason the checks give in words (the Run Gate, the wells a person left out, samples in no
 * comparison, no amplification where the gene amplified nearly everywhere else, Trace's places
 * to look), whether it changes a call, most consequential first; the repeat plate (every repeated
 * sample with its reference genes, and per assay the inter-run calibrator, the no-RT and the
 * no-template controls) to download as the planner's CSV; and the Run Gate's lines per plate.
 * Read-only: re-running is the person's call. A first read waits for the Run Gate and Trace
 * (409 `loading`, their job shown).
 *
 * {@link RepeatOffer} is the same plan in one card, for Controls.
 */
import { ArrowRight, Download, ListChecks, TriangleAlert } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { Link } from "wouter";
import { count, plural } from "@/lib/format";
import { sectionPath, type SectionProps } from "@/shell/sections";
import { Badge, Button, ErrorPanel, JobCard, LoadingBlock } from "@/ui";
import {
  loadingJob,
  useRepeat,
  type GatePlateLine,
  type RepeatInclude,
  type RepeatItem,
  type RepeatPlan,
  type RepeatView,
} from "./api";

/** Items shown before "Show all". */
const FIRST = 8;

const CONSEQUENCE: Record<
  RepeatItem["consequence"],
  { label: string; tone: "danger" | "warn" | "info" | "neutral" }
> = {
  changes_call: { label: "Changes a call", tone: "danger" },
  beyond_ci: { label: "Moves a fold change", tone: "warn" },
  no_value: { label: "No value there", tone: "info" },
  unknown: { label: "Not known", tone: "neutral" },
  changes_nothing: { label: "Changes no call", tone: "neutral" },
};

const SOURCE: Record<string, string> = {
  run_gate: "Run Gate",
  set_aside: "Left out by a person",
  no_comparison: "In no comparison",
  no_amplification: "No amplification",
  trace: "Trace",
};

/** "Sample 2016 × HMBS" (a whole sample: "Sample 2016, every gene"). */
export function itemWords(item: Pick<RepeatItem, "sample" | "target">): string {
  return item.target
    ? `Sample ${item.sample} × ${item.target}`
    : `Sample ${item.sample}, every gene`;
}

/** The plan in one sentence (counts from the engine). */
export function summaryWords(plan: RepeatPlan): string {
  const n = plan.items.length;
  if (n === 0) return "Nothing points at a reaction to re-run.";
  const parts = [
    `${plural(n, "sample × gene item")} to look at`,
    `${count(plan.counts.changes_call ?? 0)} change a call`,
  ];
  if (plan.counts.no_value) parts.push(`${count(plan.counts.no_value)} have no value there`);
  return `${parts.join("; ")}.`;
}

export function plateWords(plan: RepeatPlan): string {
  if (!plan.n_wells) return "No reaction is on the repeat plate.";
  return (
    `The repeat plate: ${plural(plan.n_samples, "sample")}, ${plural(plan.n_wells, "well")} on ` +
    `${plural(plan.n_plates, "plate")} of ${plan.plate_size}, every sample in ` +
    `${plural(plan.replicates, "replicate")} per assay` +
    (plan.calibrator ? `; inter-run calibrator: sample ${plan.calibrator}.` : ".")
  );
}

function Waiting({ error, onRetry, what }: { error: unknown; onRetry: () => void; what: string }) {
  const job = loadingJob(error);
  if (job)
    return (
      <div className="flex flex-col gap-2" role="status">
        <p className="text-[13px] text-muted">
          Reading the Run Gate and Trace for this study first ({what} follows from them).
        </p>
        <JobCard id={job.id} job={null} />
      </div>
    );
  return <ErrorPanel compact error={error} title={`${what} could not be read`} onRetry={onRetry} />;
}

function Block({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="rounded-xl border border-line bg-surface p-4">
      <h3 id={id} className="text-[14px] font-semibold text-fg">
        {title}
      </h3>
      {hint ? <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted">{hint}</p> : null}
      <div className="mt-3">{children}</div>
    </section>
  );
}

function ItemRow({ item }: { item: RepeatItem }) {
  const c = CONSEQUENCE[item.consequence];
  return (
    <li
      className="rounded-lg border border-line bg-bg px-3 py-2.5 text-[13px]"
      data-rank={item.rank}
    >
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="tabular grid size-6 shrink-0 place-items-center rounded-full bg-surface-2 text-xs font-semibold text-fg">
          {item.rank}
        </span>
        <span className="font-medium break-words text-fg">{itemWords(item)}</span>
        {item.group ? <span className="text-muted">({item.group})</span> : null}
        <Badge tone={c.tone}>{c.label}</Badge>
        <span className="text-[12px] text-muted">
          {item.on_plate
            ? "on the repeat plate"
            : item.repeat.length
              ? "listed, not on the plate"
              : "check the tube first"}
        </span>
      </p>
      {item.changed_calls.length ? (
        <p className="mt-1 text-[12.5px] text-fg">
          {item.changed_calls.length === 1 ? "The call it changes: " : "The calls it changes: "}
          <span className="font-medium">{item.changed_calls.join(", ")}</span>
        </p>
      ) : null}
      <ul className="mt-1.5 flex flex-col gap-1">
        {item.reasons.map((r) => (
          <li key={`${r.source}:${r.code}:${r.words}`} className="leading-relaxed">
            <span className="font-medium text-muted">{SOURCE[r.source] ?? r.source}: </span>
            <span className="text-fg [overflow-wrap:anywhere]">{r.words}</span>
            {r.what_to_check ? (
              <span className="text-muted"> What to check: {r.what_to_check}.</span>
            ) : null}
          </li>
        ))}
      </ul>
    </li>
  );
}

export function RepeatPlanBody({
  view,
  include,
  onInclude,
}: {
  view: RepeatView;
  include: RepeatInclude;
  onInclude: (include: RepeatInclude) => void;
}) {
  const plan = view.plan;
  const [all, setAll] = useState(false);
  const shown = all ? plan.items : plan.items.slice(0, FIRST);
  const uid = useId();
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13.5px] leading-relaxed text-fg">{summaryWords(plan)}</p>
      <div className="flex flex-col gap-2 rounded-lg border border-line bg-sunken/60 p-3">
        <p className="text-[13px] leading-relaxed text-fg">{plateWords(plan)}</p>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {plan.n_wells ? (
            <Button asChild size="sm" variant="secondary" icon={<Download />}>
              <a href={view.csv_url} download={view.csv_name}>
                Download the repeat plate (CSV)
              </a>
            </Button>
          ) : null}
          <label
            htmlFor={`${uid}-all`}
            className="flex items-center gap-2 text-[12.5px] text-muted"
          >
            <input
              id={`${uid}-all`}
              type="checkbox"
              checked={include === "all"}
              onChange={(e) => onInclude(e.target.checked ? "all" : "consequential")}
              className="accent-[var(--accent)]"
            />
            Put every item on the plate, also those that change no call
          </label>
        </div>
        <p className="text-[12px] text-muted">
          The CSV is the planner&rsquo;s plate format (plate, well, sample, group, target, type)
          that a plate-setup program or a pipetting robot imports.
        </p>
      </div>
      {plan.items.length ? (
        <ol className="flex flex-col gap-2" aria-label="What to repeat, most consequential first">
          {shown.map((item) => (
            <ItemRow key={`${item.sample}:${item.target ?? ""}`} item={item} />
          ))}
        </ol>
      ) : null}
      {plan.items.length > FIRST ? (
        <Button
          size="sm"
          variant="ghost"
          className="-ml-2 self-start"
          aria-expanded={all}
          onClick={() => setAll((v) => !v)}
        >
          {all ? `Show the first ${FIRST}` : `Show all ${count(plan.items.length)} items`}
        </Button>
      ) : null}
      {plan.warnings.length ? (
        <ul className="flex flex-col gap-1">
          {plan.warnings.map((w) => (
            <li key={w} className="flex gap-2 text-[12.5px] text-fg">
              <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warn" aria-hidden />
              {w}
            </li>
          ))}
        </ul>
      ) : null}
      <details className="rounded-lg bg-sunken/60 px-3 py-2 text-[12.5px]">
        <summary className="cursor-pointer font-medium text-muted select-none hover:text-fg">
          How the plate is laid out, and what needs no repeat
        </summary>
        <ul className="mt-1.5 flex list-disc flex-col gap-1 pl-4 leading-relaxed text-muted">
          {plan.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
        {plan.not_repeated.length ? (
          <>
            <p className="mt-2 font-medium text-muted">
              Looked at, nothing to repeat ({count(plan.not_repeated.length)})
            </p>
            <ul className="mt-1 flex list-disc flex-col gap-1 pl-4 leading-relaxed text-muted">
              {plan.not_repeated.map((r) => (
                <li key={`${r.code}:${r.words}`}>{r.words}</li>
              ))}
            </ul>
          </>
        ) : null}
      </details>
    </div>
  );
}

function GateLineRow({ line }: { line: GatePlateLine }) {
  return (
    <li className="py-2 text-[13px]">
      <p className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-fg">Plate {line.plate}</span>
        <Badge tone={line.worst === "fail" ? "danger" : "warn"}>
          {line.worst === "fail" ? "A rule fails" : "A rule warns"}
        </Badge>
        <span className="text-[12px] text-muted">
          {count(line.counts.fail ?? 0)} failing, {count(line.counts.warn ?? 0)} warning,{" "}
          {count(line.counts.pass ?? 0)} passing
        </span>
      </p>
      <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-4 text-[12.5px] leading-relaxed text-muted">
        {line.findings.map((f) => (
          <li key={`${f.code}:${f.words}`}>{f.words}</li>
        ))}
      </ul>
    </li>
  );
}

export function GateLinesBody({
  plan,
  workspace,
}: {
  plan: RepeatPlan;
  workspace: SectionProps["workspace"];
}) {
  const flagged = plan.gate_lines.filter((l) => l.worst === "fail" || l.worst === "warn");
  const quiet = plan.gate_lines.length - flagged.length;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[13.5px] text-fg">
        {flagged.length
          ? `${plural(flagged.length, "plate")} of ${count(plan.gate_lines.length)} with a rule that warns or fails; ${count(quiet)} with none.`
          : `No rule warns or fails on any of the ${plural(plan.gate_lines.length, "plate")}.`}
      </p>
      {flagged.length ? (
        <ul
          className="flex flex-col divide-y divide-line"
          aria-label="Plates with a rule that warns or fails"
        >
          {flagged.map((line) => (
            <GateLineRow key={line.plate} line={line} />
          ))}
        </ul>
      ) : null}
      {workspace ? (
        <Button asChild size="sm" variant="ghost" className="-ml-2 self-start">
          <Link href={sectionPath(workspace, "gate")}>
            Open Controls (every rule, every plate, and the Decision Cards)
            <ArrowRight aria-hidden />
          </Link>
        </Button>
      ) : null}
    </div>
  );
}

/** The two Run Review blocks: what to repeat and why, and the Run Gate per plate. */
export function RepeatBlocks({
  workspace,
  workspaceKey,
  studyId,
}: {
  workspace: SectionProps["workspace"];
  workspaceKey: string;
  studyId: string;
}) {
  const [include, setInclude] = useState<RepeatInclude>("consequential");
  const q = useRepeat(workspaceKey, studyId, include);
  const waiting = q.error ?? (loadingJob(q.failureReason) ? q.failureReason : null);
  if (!q.data)
    return (
      <Block title="What to repeat and why">
        {waiting ? (
          <Waiting error={waiting} onRetry={() => void q.refetch()} what="What to repeat" />
        ) : (
          <LoadingBlock label="Reading what to repeat" lines={4} />
        )}
      </Block>
    );
  return (
    <>
      <Block title="What to repeat and why" hint={q.data.note}>
        <RepeatPlanBody view={q.data} include={include} onInclude={setInclude} />
      </Block>
      <Block
        title="Run Gate lines per plate"
        hint="What each plate's controls say, from Controls (the Run Gate)."
      >
        <GateLinesBody plan={q.data.plan} workspace={workspace} />
      </Block>
    </>
  );
}

/** The repeat plan in one card, for Controls: the counts, the CSV, and where the list is. */
export function RepeatOffer({
  workspace,
  studyId,
}: {
  workspace: NonNullable<SectionProps["workspace"]>;
  studyId: string;
}) {
  const q = useRepeat(workspace.key, studyId);
  const plan = q.data?.plan;
  return (
    <section
      aria-labelledby="gate-repeat-title"
      className="flex flex-col gap-2 rounded-xl border border-line bg-surface p-4"
    >
      <h2
        id="gate-repeat-title"
        className="flex items-center gap-2 text-base font-semibold tracking-tight text-fg"
      >
        <ListChecks className="size-4 text-muted" aria-hidden />
        What to repeat
      </h2>
      {!plan ? (
        <p className="text-[13px] text-muted" role="status">
          {q.error && !loadingJob(q.error)
            ? "The repeat plan could not be read here; the Run Review shows it."
            : "Reading what the checks point at…"}
        </p>
      ) : (
        <>
          <p className="text-[13px] text-fg">{summaryWords(plan)}</p>
          <p className="text-[12.5px] text-muted">{plateWords(plan)}</p>
          <div className="flex flex-wrap items-center gap-2">
            {plan.n_wells && q.data ? (
              <Button asChild size="sm" variant="secondary" icon={<Download />}>
                <a href={q.data.csv_url} download={q.data.csv_name}>
                  Download the repeat plate (CSV)
                </a>
              </Button>
            ) : null}
            <Button asChild size="sm" variant="ghost">
              <Link href={sectionPath(workspace, "report", "run-review")}>
                See what to repeat and why in the Run Review
                <ArrowRight aria-hidden />
              </Link>
            </Button>
          </div>
        </>
      )}
    </section>
  );
}
