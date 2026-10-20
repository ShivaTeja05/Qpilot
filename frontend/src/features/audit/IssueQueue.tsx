/**
 * The audit's issue queue, most consequential first: what to check, about what (a choice, a
 * reference gene, a well, a sample, a plate pattern, a control), the calls it changes, where to
 * look, and what to do. Filter by kind, or to the issues that change a call.
 */
import { ChevronDown } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "wouter";
import { cn } from "@/lib/cn";
import { count, plural } from "@/lib/format";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorPanel,
  LoadingBlock,
  SegmentedControl,
} from "@/ui";
import type { IssueView } from "./types";

const PAGE_SIZE = 8;
const SHOWN_GENES = 12;
const SHOWN_PLACES = 10;

export function IssueQueue({
  issues,
  total,
  loading,
  error,
  onRetry,
  geneHref,
  onOpenLab,
}: {
  issues: IssueView[] | undefined;
  /** How many issues the audit found (the list may be its first few until the queue loads). */
  total: number | undefined;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  geneHref: ((gene: string) => string) | null;
  /** Opens the What-if lab (offered on issues about an analysis choice). */
  onOpenLab?: () => void;
}) {
  const [about, setAbout] = useState<string>("all");
  const [onlyChanges, setOnlyChanges] = useState<"all" | "changes">("all");
  const [shown, setShown] = useState(PAGE_SIZE);

  const kinds = useMemo(() => {
    const n = new Map<string, number>();
    for (const i of issues ?? []) n.set(i.about, (n.get(i.about) ?? 0) + 1);
    return [...n.entries()].sort((a, b) => b[1] - a[1]);
  }, [issues]);
  const filtered = useMemo(
    () =>
      (issues ?? []).filter(
        (i) =>
          (about === "all" || i.about === about) && (onlyChanges === "all" || i.changes.length > 0),
      ),
    [issues, about, onlyChanges],
  );
  const complete = issues != null && total != null && issues.length >= total;

  return (
    <Card as="section" aria-labelledby="audit-issues">
      <CardHeader
        id="audit-issues"
        title="What to check first"
        hint={
          total != null
            ? `${plural(total, "issue")} in the queue, most consequential first. Each says what to look at and what to do; none is fixed for you.`
            : "The audit's issue queue, most consequential first."
        }
        actions={
          complete ? (
            <SegmentedControl
              size="sm"
              label="Which issues"
              value={onlyChanges}
              onValueChange={(v) => {
                setOnlyChanges(v);
                setShown(PAGE_SIZE);
              }}
              options={[
                { value: "all", label: "All" },
                { value: "changes", label: "Changes a call" },
              ]}
            />
          ) : null
        }
      />
      <CardBody>
        {error ? (
          <ErrorPanel
            compact
            error={error}
            title="The full queue could not be read"
            onRetry={onRetry}
            className="mb-3"
          />
        ) : null}
        {complete && kinds.length > 1 ? (
          <div
            role="group"
            aria-label="Filter by what the issue is about"
            className="mb-3 flex flex-wrap gap-1.5"
          >
            <FilterChip
              on={about === "all"}
              onClick={() => setAbout("all")}
              label="Everything"
              n={issues.length}
            />
            {kinds.map(([k, n]) => (
              <FilterChip
                key={k}
                on={about === k}
                onClick={() => {
                  setAbout(about === k ? "all" : k);
                  setShown(PAGE_SIZE);
                }}
                label={k[0]!.toUpperCase() + k.slice(1)}
                n={n}
              />
            ))}
          </div>
        ) : null}
        {loading && !issues ? (
          <LoadingBlock label="Reading the issue queue" lines={4} />
        ) : !filtered.length ? (
          <EmptyState
            compact
            title={issues?.length ? "No issue of this kind" : "The audit found nothing to check"}
          >
            {issues?.length
              ? "Choose another filter."
              : "No choice, well, sample or control changes a call."}
          </EmptyState>
        ) : (
          <>
            <ol className="divide-y divide-line">
              {filtered.slice(0, shown).map((issue) => (
                <IssueRow
                  key={issue.id}
                  issue={issue}
                  rank={(issues ?? []).indexOf(issue) + 1}
                  geneHref={geneHref}
                  onOpenLab={onOpenLab}
                />
              ))}
            </ol>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[13px] text-muted">
              <span className="tabular">
                Showing {count(Math.min(shown, filtered.length))} of {count(filtered.length)}
                {!complete && total != null ? ` (the first of ${count(total)})` : ""}
              </span>
              {shown < filtered.length ? (
                <Button
                  size="sm"
                  variant="secondary"
                  icon={<ChevronDown />}
                  onClick={() => setShown((n) => n + PAGE_SIZE * 2)}
                >
                  Show more
                </Button>
              ) : null}
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}

function FilterChip({
  on,
  onClick,
  label,
  n,
}: {
  on: boolean;
  onClick: () => void;
  label: string;
  n: number;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors",
        on
          ? "border-accent bg-accent-soft text-fg"
          : "border-line bg-surface text-muted hover:border-line-strong hover:text-fg",
      )}
    >
      {label}
      <span className="tabular text-faint">{count(n)}</span>
    </button>
  );
}

function IssueRow({
  issue,
  rank,
  geneHref,
  onOpenLab,
}: {
  issue: IssueView;
  rank: number;
  geneHref: ((gene: string) => string) | null;
  onOpenLab?: () => void;
}) {
  const genes = issue.changes.slice(0, SHOWN_GENES);
  const where = [
    issue.plate ? `plate ${issue.plate}` : null,
    issue.wells.length ? listed(issue.wells.length === 1 ? "well" : "wells", issue.wells) : null,
    issue.samples.length
      ? listed(issue.samples.length === 1 ? "sample" : "samples", issue.samples)
      : null,
  ].filter(Boolean);
  return (
    <li className="grid grid-cols-[2rem_minmax(0,1fr)] gap-x-2 py-3 first:pt-0 last:pb-0">
      <span
        className="pt-0.5 text-right font-mono text-xs text-faint tabular"
        aria-label={`Issue ${rank}`}
      >
        {rank}
      </span>
      <div className="min-w-0 space-y-1.5">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <h3 className="text-sm font-semibold text-fg">{issue.title}</h3>
          <Badge>{issue.about}</Badge>
          {issue.headline.length ? (
            <Badge tone="warn">headline: {issue.headline.join(", ")}</Badge>
          ) : null}
        </div>
        <p className="text-[13px] text-fg">{issue.action}</p>
        {genes.length ? (
          <div className="flex flex-wrap items-center gap-1 text-[13px]">
            <span className="mr-1 text-muted">Changes the call of</span>
            {genes.map((g) =>
              geneHref ? (
                <Link
                  key={g}
                  href={geneHref(g)}
                  className={cn(
                    "rounded-md border border-line px-1.5 py-px font-mono text-xs hover:border-accent hover:text-accent",
                    issue.headline.includes(g) ? "font-semibold text-fg" : "text-muted",
                  )}
                >
                  {g}
                </Link>
              ) : (
                <span
                  key={g}
                  className={cn(
                    "rounded-md border border-line px-1.5 py-px font-mono text-xs",
                    issue.headline.includes(g) ? "font-semibold text-fg" : "text-muted",
                  )}
                >
                  {g}
                </span>
              ),
            )}
            {issue.changes.length > SHOWN_GENES ? (
              <span className="text-xs text-faint">
                and {count(issue.changes.length - SHOWN_GENES)} more
              </span>
            ) : null}
          </div>
        ) : null}
        {where.length ? <p className="text-xs text-muted">Where: {where.join(" · ")}</p> : null}
        {issue.causes.length ? (
          <p className="text-xs text-faint">Consistent with {issue.causes.join("; ")}</p>
        ) : null}
        {onOpenLab && issue.id.startsWith("D-") ? (
          <Button size="sm" variant="link" className="h-auto px-0" onClick={onOpenLab}>
            Try this choice in the What-if lab
          </Button>
        ) : null}
      </div>
    </li>
  );
}

function listed(noun: string, items: string[]): string {
  const head = items.slice(0, SHOWN_PLACES).join(", ");
  return `${noun} ${head}${items.length > SHOWN_PLACES ? ` and ${count(items.length - SHOWN_PLACES)} more` : ""}`;
}
