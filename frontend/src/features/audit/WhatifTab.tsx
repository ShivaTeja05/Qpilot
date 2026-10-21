/**
 * The What-if lab: one dropdown per analysis decision (options grouped by tier), and every gene
 * planned → chosen, re-run live by the engine. Calls that change come first. The choices are in
 * the URL, so a set of choices is a link; "Back to your planned analysis" clears them.
 */
import { RotateCcw, Stamp } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useLocation } from "wouter";
import { Dumbbell, callKey, whatifRows } from "@/charts";
import { count, plural } from "@/lib/format";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  ConclusionTag,
  CopyButton,
  ErrorPanel,
  LoadingBlock,
  SegmentedControl,
  Skeleton,
} from "@/ui";
import { type AuditTarget, shownError, useWhatif } from "./api";
import { ChoiceSelect } from "./ChoiceSelect";
import type { AuditOverview, Changes, DecisionView, ManifestLike, WhatifRow } from "./types";
import { DECISION_ORDER } from "./words";

/** The changes that name a real decision and option and differ from the plan; the rest, named. */
export function validChanges(
  decisions: DecisionView[],
  changes: Changes,
): { valid: Changes; ignored: string[] } {
  const valid: Changes = {};
  const ignored: string[] = [];
  for (const [d, o] of Object.entries(changes)) {
    const decision = decisions.find((x) => x.id === d);
    if (!decision || !decision.options.some((x) => x.id === o)) ignored.push(`${d}=${o}`);
    else if (decision.baseline !== o) valid[d] = o;
  }
  return { valid, ignored };
}

function ordered(decisions: DecisionView[]): DecisionView[] {
  const rank = (id: string) => {
    const i = (DECISION_ORDER as readonly string[]).indexOf(id);
    return i < 0 ? DECISION_ORDER.length : i;
  };
  return [...decisions].sort((a, b) => rank(a.id) - rank(b.id));
}

export function WhatifTab({
  target,
  overview,
  manifest,
  changes,
  geneHref,
  onChanges,
}: {
  target: AuditTarget;
  overview: AuditOverview | undefined;
  manifest: ManifestLike;
  changes: Changes;
  /** Where a gene opens (the Gene section); null when the audit is not about this study. */
  geneHref: ((gene: string) => string) | null;
  onChanges: (changes: Changes) => void;
}) {
  if (!overview) {
    return (
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
        <Skeleton className="h-96 rounded-xl" />
      </div>
    );
  }
  return (
    <Lab
      geneHref={geneHref}
      target={target}
      overview={overview}
      manifest={manifest}
      changes={changes}
      onChanges={onChanges}
    />
  );
}

function Lab({
  geneHref,
  target,
  overview,
  manifest,
  changes,
  onChanges,
}: {
  geneHref: ((gene: string) => string) | null;
  target: AuditTarget;
  overview: AuditOverview;
  manifest: ManifestLike;
  changes: Changes;
  onChanges: (changes: Changes) => void;
}) {
  const [, navigate] = useLocation();
  const [show, setShow] = useState<"some" | "all">("some");
  const decisions = useMemo(() => ordered(overview.decisions), [overview.decisions]);
  const { valid, ignored } = useMemo(() => validChanges(decisions, changes), [decisions, changes]);
  const whatif = useWhatif(target, valid, []);
  const moved = Object.keys(valid).length;

  const yours = manifest.your_choices?.changes_from_prespecified ?? null;
  const yoursValid = yours ? validChanges(decisions, yours).valid : null;
  const onYours = yoursValid != null && sameChanges(yoursValid, valid);

  const set = (d: string, o: string) => {
    const next = { ...valid };
    if (decisions.find((x) => x.id === d)?.baseline === o) delete next[d];
    else next[d] = o;
    onChanges(next);
  };

  return (
    <div className="space-y-5">
      <Card as="section" aria-labelledby="whatif-title">
        <CardHeader
          id="whatif-title"
          title="What if you had chosen differently?"
          hint="Change any choice and the engine re-runs every gene live. Nothing here changes your analysis or the record."
          actions={
            <>
              <CopyButton text={linkHere()} label="Copy a link to these choices" />
              <Button
                size="sm"
                variant="secondary"
                icon={<RotateCcw />}
                disabled={!moved}
                onClick={() => onChanges({})}
              >
                Back to your planned analysis
              </Button>
            </>
          }
        />
        <CardBody className="space-y-4">
          {ignored.length ? (
            <p
              role="status"
              className="rounded-lg border border-warn/30 bg-warn-soft/50 px-3 py-2 text-[13px] text-fg"
            >
              This link names {ignored.length === 1 ? "a choice" : "choices"} this audit does not
              have ({ignored.join(", ")}); {ignored.length === 1 ? "it is" : "they are"} left out.
            </p>
          ) : null}
          <div className="grid gap-x-4 gap-y-4 sm:grid-cols-2 xl:grid-cols-4">
            {decisions.map((d) => (
              <ChoiceSelect
                key={d.id}
                decision={d}
                value={valid[d.id] ?? d.baseline}
                onValueChange={(o) => set(d.id, o)}
              />
            ))}
          </div>
          <YourChoices
            yours={yoursValid}
            onYours={onYours}
            unmapped={manifest.your_choices?.no_simulator_counterpart ?? []}
            decisions={decisions}
            apply={() => yoursValid && onChanges(yoursValid)}
          />
        </CardBody>
      </Card>

      {shownError(whatif.error) ? (
        <ErrorPanel
          error={whatif.error}
          title="The engine could not re-run these choices"
          onRetry={() => void whatif.refetch()}
        >
          {moved ? (
            <Button
              size="sm"
              variant="secondary"
              className="mt-3 mr-2"
              icon={<RotateCcw />}
              onClick={() => onChanges({})}
            >
              Back to your planned analysis
            </Button>
          ) : null}
        </ErrorPanel>
      ) : !whatif.data ? (
        <Card>
          <CardBody className="pt-4">
            <LoadingBlock label="Re-running the study" lines={6} />
          </CardBody>
        </Card>
      ) : (
        <Outcome
          data={whatif.data}
          moved={moved}
          updating={whatif.isFetching && whatif.isPlaceholderData}
          group={overview.study.group}
          show={show}
          setShow={setShow}
          onSelect={geneHref ? (gene) => navigate(geneHref(gene)) : undefined}
        />
      )}
    </div>
  );
}

/** This page's address without the launch key (the key stays in the browser's cookie). */
function linkHere(): string {
  if (typeof window === "undefined") return "";
  const { origin, pathname, hash } = window.location;
  return `${origin}${pathname}${hash}`;
}

function sameChanges(a: Changes, b: Changes): boolean {
  const ka = Object.keys(a);
  return ka.length === Object.keys(b).length && ka.every((k) => a[k] === b[k]);
}

/** The person's own choices on the Decision Cards, as the audit mapped them. */
function YourChoices({
  yours,
  onYours,
  unmapped,
  decisions,
  apply,
}: {
  yours: Changes | null;
  onYours: boolean;
  unmapped: string[];
  decisions: DecisionView[];
  apply: () => void;
}) {
  if (yours == null) return null;
  const n = Object.keys(yours).length;
  const names = Object.entries(yours).map(([d, o]) => {
    const decision = decisions.find((x) => x.id === d);
    return `${decision?.name.toLowerCase() ?? d}: ${decision?.options.find((x) => x.id === o)?.label ?? o}`;
  });
  return (
    <div className="flex flex-wrap items-start gap-3 rounded-lg bg-sunken px-3 py-2.5 text-[13px]">
      <Stamp className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
      <div className="min-w-0 flex-1 text-muted">
        {n ? (
          <>
            <span className="font-medium text-fg">Your Decision Cards</span> differ from the plan in{" "}
            {plural(n, "choice")}: {names.join("; ")}.
          </>
        ) : (
          <>
            <span className="font-medium text-fg">Your Decision Cards</span> match the planned
            analysis in every choice the audit varies.
          </>
        )}
        {unmapped.length ? <> Not varied by the audit: {unmapped.join(", ")}.</> : null}
      </div>
      {n ? (
        <Button
          size="sm"
          variant={onYours ? "ghost" : "secondary"}
          disabled={onYours}
          onClick={apply}
        >
          {onYours ? "Showing your choices" : "Show your choices"}
        </Button>
      ) : null}
    </div>
  );
}

function Outcome({
  data,
  moved,
  updating,
  group,
  show,
  setShow,
  onSelect,
}: {
  data: NonNullable<ReturnType<typeof useWhatif>["data"]>;
  moved: number;
  updating: boolean;
  group: string;
  show: "some" | "all";
  setShow: (v: "some" | "all") => void;
  onSelect?: (gene: string) => void;
}) {
  const rows = useMemo(() => whatifRows(data), [data]);
  const changed = data.rows.filter((r) => r.changed);
  const shown =
    show === "all" || !moved ? rows : rows.filter((r) => r.baseCall !== r.newCall || r.headline);
  const summary = moved
    ? `With ${data.changes.join("; ")}: ${count(data.n_changed)} of ${plural(data.n_genes, "gene")} change their call.`
    : `Your planned analysis: ${plural(data.n_genes, "gene")}.`;
  return (
    <Card as="section" aria-labelledby="whatif-outcome" aria-busy={updating}>
      <CardHeader
        id="whatif-outcome"
        title={moved ? "What changes" : "Your planned analysis"}
        hint={
          moved
            ? `With ${data.changes.join("; ")}`
            : "Change a choice above to see which calls move."
        }
        actions={
          moved ? (
            <SegmentedControl
              size="sm"
              label="Genes shown"
              value={show}
              onValueChange={setShow}
              options={[
                { value: "some", label: "Changed and headline" },
                { value: "all", label: "All genes" },
              ]}
            />
          ) : null
        }
      />
      <CardBody className="space-y-4">
        {moved ? (
          <div
            className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-lg bg-sunken px-4 py-3"
            aria-live="polite"
          >
            <p className="flex items-baseline gap-2">
              <span className="font-mono text-3xl font-semibold text-fg tabular">
                {count(data.n_changed)}
              </span>
              <span className="text-sm text-muted">
                of {plural(data.n_genes, "call")} change{data.n_changed === 1 ? "s" : ""}
              </span>
            </p>
            {changed.length ? (
              <ChangedList rows={changed} onSelect={onSelect} />
            ) : (
              <p className="text-sm text-muted">Every call stays as planned.</p>
            )}
            {updating ? <span className="ml-auto text-xs text-muted">Re-running…</span> : null}
          </div>
        ) : null}
        <div className={updating ? "opacity-60 transition-opacity" : "transition-opacity"}>
          <Dumbbell
            rows={shown}
            line={data.line_log2}
            lineLabel={`${data.line} line`}
            lower={`lower in ${group}`}
            higher={`higher in ${group}`}
            summary={summary}
            fromLabel="Planned"
            toLabel={moved ? "With these choices" : "Planned"}
            onSelect={onSelect}
          />
        </div>
      </CardBody>
    </Card>
  );
}

function ChangedList({ rows, onSelect }: { rows: WhatifRow[]; onSelect?: (gene: string) => void }) {
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="Genes whose call changes">
      {rows.map((r) => (
        <li key={r.gene}>
          <ChipOf
            onClick={onSelect ? () => onSelect(r.gene) : undefined}
            title={`${r.gene}: ${r.base} (${r.base_call}) → ${r.new} (${r.new_call})`}
          >
            <span className={r.headline ? "font-semibold text-fg" : "text-fg"}>{r.gene}</span>
            <ConclusionTag
              conclusion={callKey({ call_key: r.base_call_key, call: r.base_call })}
              compact
            />
            <span aria-hidden className="text-faint">
              →
            </span>
            <span className="sr-only">becomes</span>
            <ConclusionTag
              conclusion={callKey({ call_key: r.new_call_key, call: r.new_call })}
              compact
            />
          </ChipOf>
        </li>
      ))}
    </ul>
  );
}

/** A gene chip: a button that opens the gene, or plain when there is no gene page for it. */
function ChipOf({
  onClick,
  title,
  children,
}: {
  onClick?: () => void;
  title: string;
  children: ReactNode;
}) {
  const cls =
    "inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-0.5 text-xs";
  return onClick ? (
    <button type="button" onClick={onClick} title={title} className={`${cls} hover:border-accent`}>
      {children}
    </button>
  ) : (
    <span title={title} className={cls}>
      {children}
    </span>
  );
}
