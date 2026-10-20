/**
 * The top of the Gene section: where you are (Results › gene, n of N, previous / next with
 * `[` `]`, a gene picker) and the gene's result: call, fold [95 % CI], p, n per group, the
 * confidence level with its reasons, and the audit's verdict when the study is audited.
 */
import { ArrowLeft, ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "wouter";
import type { Schemas } from "@/api/client";
import { sectionPath } from "@/shell/sections";
import { TraceLink } from "@/features/trace/TraceLink";
import { Badge, Button, ConclusionTag, CopyButton, Kbd, LevelTag, Select, Tooltip, VerdictTag } from "@/ui";
import { cn } from "@/lib/cn";
import { ci, count, fold, pValue } from "@/lib/format";
import { asConclusion, asLevel } from "@/lib/vocab";
import type { AuditGeneCard, GeneView } from "./api";
import type { GeneNeighbours } from "./nav";
import { callSentence, checkName, directionWords } from "./words";

type Workspace = Pick<Schemas["WorkspaceView"], "key" | "kind">;

/** Results › gene · n of N · ‹ prev · next › · jump to a gene. */
export function GeneNav({
  workspace,
  gene,
  order,
  near,
  onGo,
}: {
  workspace: Workspace;
  gene: string | null;
  order: readonly string[];
  near: GeneNeighbours;
  onGo: (gene: string) => void;
}) {
  return (
    <nav aria-label="Genes" className="mb-5 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <Link
        href={sectionPath(workspace, "results")}
        className="inline-flex items-center gap-1.5 rounded-md text-[13px] text-muted hover:text-fg"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        All genes
      </Link>
      <div className="flex flex-wrap items-center gap-2">
        {gene ? <TraceLink gene={gene} className="mr-2" /> : null}
        {near.total ? (
          <span className="text-xs text-muted tabular" aria-live="polite">
            {near.position ? `${count(near.position)} of ${count(near.total)}` : `${count(near.total)} genes`}
          </span>
        ) : null}
        <Tooltip content={near.prev ? <>Previous gene <Kbd className="ml-1">[</Kbd></> : null}>
          <Button
            size="sm"
            variant="secondary"
            icon={<ChevronLeft />}
            disabled={!near.prev}
            onClick={() => near.prev && onGo(near.prev)}
            aria-label={near.prev ? `Previous gene: ${near.prev}` : "No previous gene"}
            aria-keyshortcuts="["
          >
            <span className="max-w-[9rem] truncate">{near.prev ?? "Previous"}</span>
          </Button>
        </Tooltip>
        <Tooltip content={near.next ? <>Next gene <Kbd className="ml-1">]</Kbd></> : null}>
          <Button
            size="sm"
            variant="secondary"
            disabled={!near.next}
            onClick={() => near.next && onGo(near.next)}
            aria-label={near.next ? `Next gene: ${near.next}` : "No next gene"}
            aria-keyshortcuts="]"
          >
            <span className="max-w-[9rem] truncate">{near.next ?? "Next"}</span>
            <ChevronRight aria-hidden />
          </Button>
        </Tooltip>
        {order.length ? (
          <Select
            size="sm"
            label="Go to a gene"
            placeholder="Go to a gene"
            value={gene ?? undefined}
            onValueChange={onGo}
            options={order.map((g) => ({ value: g, label: g }))}
            className="w-40"
          />
        ) : null}
      </div>
    </nav>
  );
}

function Fact({ label, children, hint, className }: { label: string; children: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0", className)}>
      <dt className="text-xs font-medium text-muted">{label}</dt>
      <dd className="mt-1 text-fg">{children}</dd>
      {hint ? <dd className="mt-0.5 text-xs text-muted">{hint}</dd> : null}
    </div>
  );
}

/** The gene's result in one band. */
export function GeneHeader({
  view,
  labels,
  audit,
  auditPending,
  alpha,
  minLog2fc,
  ruleText,
  summary,
  auditOutdated = 0,
}: {
  view: Pick<GeneView, "row" | "confidence" | "confidence_text" | "audit_verdict">;
  labels: { hi: string; lo: string };
  /** The audit's card for this gene (null: not audited or not loaded). */
  audit: AuditGeneCard | null;
  /** The audit exists but its card is still loading. */
  auditPending?: boolean;
  alpha?: number | null;
  minLog2fc?: number | null;
  /** The conclusion rule in the server's words (preferred over the one built here). */
  ruleText?: string | null;
  /** The gene in plain text, for "Copy summary". */
  summary?: string;
  /** Decisions made on the study since it was audited (0: the audit is current). */
  auditOutdated?: number;
}) {
  const gene = view.row;
  const checks = view.confidence?.checks ?? [];
  const conclusion = asConclusion(gene.conclusion);
  const [lo, hi] = gene.ci ?? [];
  const level = asLevel(gene.level ?? view.confidence?.level);
  const reasons = gene.reasons?.length ? gene.reasons : (view.confidence?.reasons ?? []);
  const verdict = audit?.verdict ?? view.audit_verdict ?? gene.verdict ?? null;
  const yours = gene.at_your_choices;
  const yoursMoved = yours && (yours.differs || Math.abs(yours.log2fc - (gene.log2fc ?? Math.log2(gene.fc))) > 1e-9);
  const ruleWords =
    ruleText ??
    (alpha != null && minLog2fc != null ? `A call needs p below ${alpha} and at least ${fold(2 ** minLog2fc)}.` : undefined);
  return (
    <header className="mb-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-[32px] leading-tight font-semibold tracking-tight text-fg">{gene.gene}</h1>
        <ConclusionTag conclusion={conclusion} long className="text-lg" />
        {gene.headline ? (
          <Tooltip content="One of the study's headline genes: its Decision Cards show what each option does to it.">
            <span tabIndex={0} className="rounded-md">
              <Badge tone="accent">Headline gene</Badge>
            </span>
          </Tooltip>
        ) : null}
        {summary ? <CopyButton text={summary} label="Copy summary" showLabel className="ml-auto" /> : null}
      </div>
      <p className="mt-1 text-sm text-muted">
        {callSentence(gene)}
        {gene.fc > 0 ? <>: {directionWords(gene, labels)}.</> : "."}
      </p>
      {yours && yoursMoved ? (
        <p className={cn("mt-1 text-[13px]", yours.differs ? "text-warn" : "text-muted")}>
          With the options chosen on the Decision Cards: <span className="tabular">{fold(yours.fc)}</span>, p{" "}
          <span className="tabular">{pValue(yours.p)}</span>, <ConclusionTag conclusion={yours.conclusion} long />
          {yours.differs ? " — a different call from the planned analysis." : "."}
        </p>
      ) : null}

      <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-5 rounded-xl border border-line bg-surface p-4 sm:grid-cols-4 xl:grid-cols-[repeat(4,minmax(0,auto))_minmax(0,1.6fr)]">
        <Fact label="Fold change" hint={<>95&nbsp;% CI <span className="tabular">{ci(lo, hi)}</span></>}>
          <span className="font-mono text-2xl font-semibold tabular">{fold(gene.fc)}</span>
        </Fact>
        <Fact label="p-value">
          <span className="font-mono text-2xl font-semibold tabular">{pValue(gene.p)}</span>
        </Fact>
        <Fact
          label="Samples"
          hint={
            <>
              {labels.hi} · {labels.lo}
            </>
          }
        >
          <span className="font-mono text-2xl font-semibold tabular">
            {count(gene.n_hi)}
            <span className="px-1 text-base font-normal text-faint">vs</span>
            {count(gene.n_lo)}
          </span>
        </Fact>
        <Fact label="Confidence">
          {level ? <LevelTag level={level} className="text-base" /> : <span className="text-faint">Not graded</span>}
        </Fact>
        <Fact label="Audit verdict" className="col-span-2 sm:col-span-4 xl:col-span-1">
          {verdict ? (
            <>
              <VerdictTag verdict={verdict} className="text-base" />
              {audit?.result.verdict_sentence ? (
                <p className="mt-1 text-[13px] text-muted">{audit.result.verdict_sentence}</p>
              ) : null}
              {auditOutdated > 0 ? (
                <p className="mt-1 text-xs text-warn">
                  Audited before the last {auditOutdated === 1 ? "decision" : `${count(auditOutdated)} decisions`}: run it
                  again in Audit to bring this verdict up to date.
                </p>
              ) : null}
            </>
          ) : auditPending ? (
            <span className="text-[13px] text-muted">Reading the audit…</span>
          ) : (
            <span className="text-[13px] text-muted">Not audited yet</span>
          )}
        </Fact>
      </dl>

      {ruleWords ? <p className="mt-2 text-xs text-muted">The rule: {ruleWords}</p> : null}
      {reasons.length ? (
        <div className="mt-3 text-[13px]">
          <p className="font-medium text-fg">
            {level ? `${level} confidence` : "Confidence"}, because:
          </p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted">
            {reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {view.confidence_text?.plain ? <p className="mt-2 text-[13px] text-muted">{view.confidence_text.plain}</p> : null}
      {checks.length ? (
        <details className="group mt-2 text-[13px]">
          <summary className="cursor-pointer text-muted hover:text-fg">
            All {checks.length} confidence checks
          </summary>
          <ul className="mt-2 grid gap-1.5 sm:grid-cols-2">
            {checks.map((c) => (
              <li key={c.id} className="flex gap-2 rounded-lg border border-line bg-surface px-3 py-2">
                <span aria-hidden className={c.passed ? "text-ok" : "text-warn"}>
                  {c.passed ? "✓" : "!"}
                </span>
                <span className="min-w-0">
                  <span className="font-medium text-fg">{checkName(c.id)}</span>
                  <span className="sr-only">{c.passed ? " passed" : " did not pass"}</span>
                  <span className="block text-muted">{c.note}</span>
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </header>
  );
}
