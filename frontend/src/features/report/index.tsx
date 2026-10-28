/**
 * Report: the study written up from its own numbers — a summary, what a careful reviewer would
 * flag, the Run Review (the Evidence Ledger and a person's sign-off), a Methods section to paste
 * into a paper, the MIQE 2.0 checklist, the limitations, and a study passport (one offline HTML
 * file bound to an Analysis Record). Every number is a fact of the study; hover one to see where
 * it comes from.
 */
import { ArrowRight, BookMarked, FileText } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "wouter";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/cn";
import { count } from "@/lib/format";
import { SECTION, sectionPath, type SectionProps } from "@/shell/sections";
import {
  Button,
  Card,
  CardBody,
  EmptyState,
  ErrorPanel,
  Hash,
  LoadingBlock,
  PageHeader,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  SetsNote,
} from "@/ui";
import { asExported, useReport, useReportExports, type ReportFormat, type ReportView } from "./api";
import { Cited } from "./Cited";
import { ExportPanel, formatOf } from "./ExportPanel";
import { MethodsPanel } from "./MethodsPanel";
import { MiqePanel } from "./MiqePanel";
import { PassportPreview } from "./PassportPreview";
import { ReviewPanel } from "./ReviewPanel";
import { RunReview } from "./RunReview";

const PARTS = [
  { id: "summary", label: "Summary" },
  { id: "review", label: "Reviewer's report" },
  { id: "run-review", label: "Run Review" },
  { id: "methods", label: "Methods" },
  { id: "miqe", label: "MIQE 2.0 checklist" },
  { id: "limitations", label: "Limitations" },
  { id: "passport", label: "Study passport" },
  { id: "facts", label: "Every number" },
] as const;
type PartId = (typeof PARTS)[number]["id"];

const anchor = (id: PartId) => `report-${id}`;

function scrollTo(id: PartId) {
  const el = document.getElementById(anchor(id));
  if (!el) return;
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  el.focus({ preventScroll: true });
}

export default function ReportSection({ workspace, rest }: SectionProps) {
  const key = workspace?.key ?? "";
  const studyId = workspace?.study_id ?? null;
  const readable = studyId && workspace?.results_visible !== false ? studyId : null;
  const report = useReport(key, readable);
  const exports = useReportExports(key, readable);
  const [jobs, setJobs] = useState<Partial<Record<ReportFormat, string>>>({});
  const blind = report.error instanceof ApiError && report.error.code === "blind";

  // A job started in another tab (or before a reload) still shows its card here.
  const active = workspace?.active_jobs;
  const shownJobs = useMemo(() => {
    const out: Partial<Record<ReportFormat, string>> = {};
    for (const j of active ?? []) if (j.kind === "report.export") out[formatOf(j.title)] = j.id;
    return { ...out, ...jobs };
  }, [active, jobs]);

  const files = exports.data?.exports ?? [];
  const passport = files.find((f) => f.format === "passport" && f.record) ?? null;

  // A deep link to one part (`report/run-review`, from Controls' "What to repeat") lands on it.
  const part = PARTS.find((x) => x.id === rest?.[0])?.id ?? null;
  const loaded = Boolean(report.data);
  useEffect(() => {
    if (part && loaded) requestAnimationFrame(() => scrollTo(part));
  }, [part, loaded]);

  const header = (
    <PageHeader
      eyebrow="Report"
      title="Report"
      hint="Your study written up from its own numbers: what a reviewer would flag, the Run Review to sign off, a Methods section to paste, the MIQE 2.0 checklist and a study passport to share."
      actions={
        report.data ? (
          <Button variant="primary" icon={<BookMarked />} onClick={() => scrollTo("passport")}>
            Study passport
          </Button>
        ) : null
      }
    />
  );

  if (!readable || blind) {
    const next = workspace?.next_step;
    return (
      <div className="mx-auto w-full max-w-[1180px]">
        {header}
        <EmptyState
          icon={<FileText />}
          title="The report is written from the analysed study"
          action={
            next && next.section !== "report" && next.section in SECTION ? (
              <Button asChild variant="primary">
                <Link href={sectionPath(workspace, next.section as keyof typeof SECTION)}>
                  {next.title}
                  <ArrowRight aria-hidden />
                </Link>
              </Button>
            ) : null
          }
        >
          {workspace?.kind === "session"
            ? "Confirm the design and the curves first: until then the results stay hidden, and so does the report."
            : "This study has not been analysed yet."}
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-[1180px]">
      {header}
      {report.isPending ? (
        <Card>
          <CardBody className="pt-4">
            <LoadingBlock
              label="Writing the report from the study's numbers (the first time takes a few seconds)"
              lines={8}
            />
          </CardBody>
        </Card>
      ) : report.error ? (
        <ErrorPanel
          error={report.error}
          title="The report could not be written"
          onRetry={() => void report.refetch()}
        />
      ) : (
        <Document
          view={report.data}
          workspace={workspace}
          runReview={<RunReview workspace={workspace} workspaceKey={key} studyId={readable} />}
          exportPanel={
            <ExportPanel
              workspaceKey={key}
              studyId={readable}
              head={report.data.header.chain_head}
              jobs={shownJobs}
              onJob={(f, id) =>
                setJobs((old) => {
                  const next = { ...old };
                  if (id) next[f] = id;
                  else delete next[f];
                  return next;
                })
              }
              exports={files}
            />
          }
          passport={passport && asExported(passport)}
        />
      )}
    </div>
  );
}

function Document({
  view,
  workspace,
  runReview,
  exportPanel,
  passport,
}: {
  view: ReportView;
  workspace: SectionProps["workspace"];
  runReview: ReactNode;
  exportPanel: ReactNode;
  passport: ReturnType<typeof asExported>;
}) {
  const active = useActivePart();
  const h = view.header;
  return (
    <div className="grid items-start gap-8 xl:grid-cols-[176px_minmax(0,1fr)]">
      <nav aria-label="Contents" className="sticky top-4 hidden self-start xl:block">
        <p className="mb-2 text-[11.5px] font-semibold tracking-wider text-muted uppercase">
          Contents
        </p>
        <ol className="flex flex-col gap-0.5 border-l border-line">
          {PARTS.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                onClick={() => scrollTo(p.id)}
                aria-current={active === p.id ? "location" : undefined}
                className={cn(
                  "-ml-px block w-full border-l-2 py-1 pr-2 pl-3 text-left text-[13px] transition-colors duration-150",
                  active === p.id
                    ? "border-accent font-medium text-fg"
                    : "border-transparent text-muted hover:border-line-strong hover:text-fg",
                )}
              >
                {p.label}
              </button>
            </li>
          ))}
        </ol>
      </nav>

      <div className="flex min-w-0 max-w-[860px] flex-col gap-10">
        <nav
          aria-label="Jump to"
          className="relative -mt-4 flex gap-1.5 overflow-x-auto pb-1 qp-scroll xl:hidden"
        >
          {PARTS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => scrollTo(p.id)}
              className="h-7 shrink-0 rounded-full border border-line bg-surface px-3 text-[12.5px] text-muted hover:border-line-strong hover:text-fg"
            >
              {p.label}
            </button>
          ))}
        </nav>
        <Part id="summary" title="Summary" hint={h.research_use}>
          <div className="flex flex-col gap-4">
            <p className="text-[15px] leading-relaxed text-muted [text-wrap:pretty]">
              <Cited text={view.summary} facts={view.facts} />
            </p>
            <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3" aria-label="Key numbers">
              {view.key_numbers.map((k) => {
                const f = view.facts[k.fact];
                return f ? (
                  <li
                    key={k.label}
                    className="rounded-xl border border-line bg-surface px-3.5 py-2.5"
                    title={`${f.id}: ${f.path}`}
                  >
                    <p className="tabular text-[20px] font-semibold text-fg">{f.text}</p>
                    <p className="text-[12px] text-muted">{k.label}</p>
                  </li>
                ) : null;
              })}
            </ul>
            <SetsNote
              grid={gridCount(view)}
              reasonable={view.audit.reasonable}
              full={view.audit.analyses}
            />
            <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
              <span>
                Input <Hash value={h.input_sha256} length={12} />
              </span>
              <span>
                Decision log <Hash value={h.chain_head} length={12} />
              </span>
              <span>
                {count(h.n_decisions)} {h.n_decisions === 1 ? "decision" : "decisions"} in the log
              </span>
            </p>
          </div>
        </Part>

        <Part
          id="review"
          title="Reviewer's report"
          hint="What a careful reviewer would flag, most severe first. Each finding is read from this study's numbers."
        >
          <ReviewPanel review={view.review} facts={view.facts} workspace={workspace} />
        </Part>

        <Part
          id="run-review"
          title="Run Review"
          hint="For whoever reviews this run: the headline genes, what the data cannot show, and a sign-off kept in the decision log."
        >
          {runReview}
        </Part>

        <Part
          id="methods"
          title="Methods"
          hint="Ready to paste into a paper; edit the wording, keep the numbers. Every number is a fact of this study."
        >
          <MethodsPanel methods={view.methods} facts={view.facts} />
        </Part>

        <Part
          id="miqe"
          title="MIQE 2.0 checklist"
          hint="Each item met, not met, not applicable, or not something the data can tell — with the evidence. A count, never a score."
        >
          <MiqePanel miqe={view.miqe} facts={view.facts} />
        </Part>

        <Part
          id="limitations"
          title="Limitations"
          hint="In plain words, for the discussion section."
        >
          <ul className="flex flex-col gap-2 rounded-xl border border-line bg-surface px-5 py-4">
            {view.limitations.map((l) => (
              <li key={l.id} className="flex gap-2.5 text-[14px] leading-relaxed text-muted">
                <span aria-hidden className="mt-2 size-1.5 shrink-0 rounded-full bg-faint" />
                <Cited text={l.text} facts={view.facts} />
              </li>
            ))}
          </ul>
        </Part>

        <Part
          id="passport"
          title="Study passport"
          hint="One file a reviewer opens offline with a double-click. Below: a preview of what it holds, then write it."
        >
          <div className="flex flex-col gap-5">
            <PassportPreview view={view} passport={passport} workspace={workspace} />
            {exportPanel}
          </div>
        </Part>

        <Part
          id="facts"
          title="Every number, and where it comes from"
          hint="Every number this report cites, its value and where it comes from: the engine's own results, or a value the report read from the study's files (the path says which file and where in it)."
        >
          <FactsTable view={view} />
        </Part>
      </div>
    </div>
  );
}

function Part({
  id,
  title,
  hint,
  children,
}: {
  id: PartId;
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section
      id={anchor(id)}
      tabIndex={-1}
      aria-labelledby={`${anchor(id)}-title`}
      className="scroll-mt-4 outline-none"
    >
      <h2 id={`${anchor(id)}-title`} className="text-[18px] font-semibold tracking-tight text-fg">
        {title}
      </h2>
      {hint ? (
        <p className="mt-0.5 mb-4 text-[13px] text-muted">{hint}</p>
      ) : (
        <div className="mb-4" />
      )}
      {children}
    </section>
  );
}

/** qPilot's choice grid, as the report cites it (`f_n_cells`), when the study has one. */
function gridCount(view: ReportView): number | null {
  const n = Number(view.facts.f_n_cells?.value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function FactsTable({ view }: { view: ReportView }) {
  const [open, setOpen] = useState(false);
  const facts = useMemo(() => Object.values(view.facts), [view.facts]);
  return (
    <div className="flex flex-col gap-2">
      <Button
        size="sm"
        variant="secondary"
        className="self-start"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "Hide" : "Show"} the {count(facts.length)} facts this report cites
      </Button>
      {open ? (
        <div
          className="relative max-h-[480px] overflow-auto rounded-lg border border-line qp-scroll"
          tabIndex={0}
          role="region"
          aria-label="Facts the report cites (scrolls)"
        >
          <Table caption="Every fact the report cites, its value and where it comes from">
            <THead>
              <TR>
                <TH title="The number's name in the Analysis Record: f_… is the engine's own; f_rpt_… one the report read from the study's files.">
                  Name
                </TH>
                <TH numeric>Value</TH>
                <TH>From</TH>
              </TR>
            </THead>
            <TBody>
              {facts.map((f) => (
                <TR key={f.id}>
                  <TD className="font-mono text-[12px]">{f.id}</TD>
                  <TD numeric>{f.text}</TD>
                  <TD className="font-mono text-[11.5px] break-all text-muted">{f.path}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
      ) : null}
    </div>
  );
}

/** The part of the document in view (for the table of contents). */
function useActivePart(): PartId {
  const [active, setActive] = useState<PartId>("summary");
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const els = PARTS.map((p) => document.getElementById(anchor(p.id))).filter(
      (e): e is HTMLElement => Boolean(e),
    );
    const seen = new Map<string, boolean>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) seen.set(e.target.id, e.isIntersecting);
        const first = PARTS.find((p) => seen.get(anchor(p.id)));
        if (first) setActive(first.id);
      },
      { rootMargin: "0px 0px -65% 0px" },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
  return active;
}
