/**
 * The summary bar (k of n claims supported, a count per verdict that filters the list) and the
 * list of claims, each a button that opens it.
 */
import { cn } from "@/lib/cn";
import { SegmentedControl } from "@/ui";
import type { ClaimsReport, ClaimView, Verdict } from "./api";
import { CLAIM_VERDICT, VERDICT_ORDER } from "./marks";
import { ClaimVerdict, FactSentence } from "./parts";

export function SummaryBar({
  report,
  filter,
  onFilter,
}: {
  report: ClaimsReport;
  filter: Verdict | null;
  onFilter: (v: Verdict | null) => void;
}) {
  const { n, supported, counts } = report.summary;
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
      <p className="text-[15px] text-fg" aria-live="polite">
        {n ? (
          <>
            <span className="tabular text-2xl font-semibold">{supported}</span>
            <span className="text-muted"> of </span>
            <span className="tabular text-2xl font-semibold">{n}</span>
            <span className="text-muted"> claim{n === 1 ? "" : "s"} supported</span>
          </>
        ) : (
          report.summary.sentence
        )}
      </p>
      {n ? (
        <div role="group" aria-label="Show claims by verdict" className="flex flex-wrap gap-1.5">
          {VERDICT_ORDER.filter((v) => (counts[v] ?? 0) > 0).map((v) => {
            const on = filter === v;
            return (
              <button
                key={v}
                type="button"
                aria-pressed={on}
                onClick={() => onFilter(on ? null : v)}
                className={cn(
                  "inline-flex h-7 items-center gap-1.5 rounded-md border px-2 text-[13px] transition-colors duration-150",
                  on
                    ? "border-line-strong bg-surface-2 text-fg"
                    : "border-line bg-surface text-muted hover:border-line-strong hover:text-fg",
                )}
              >
                <ClaimVerdict verdict={v} short className="text-inherit" />
                <span className="tabular font-semibold text-fg">{counts[v]}</span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

export function ClaimList({
  claims,
  selected,
  order,
  onOrder,
  onSelect,
}: {
  claims: ClaimView[];
  selected: string | null;
  order: "text" | "severity";
  onOrder: (o: "text" | "severity") => void;
  onSelect: (id: string) => void;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-fg">Every claim</h2>
        <SegmentedControl
          size="sm"
          label="Order"
          value={order}
          onValueChange={onOrder}
          options={[
            { value: "text", label: "As written" },
            { value: "severity", label: "Most serious first" },
          ]}
        />
      </div>
      <ol className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
        {claims.map((c) => {
          const on = c.id === selected;
          return (
            <li key={c.id}>
              <button
                type="button"
                aria-current={on ? "true" : undefined}
                onClick={() => onSelect(c.id)}
                className={cn(
                  "flex w-full flex-col items-start gap-1 px-3 py-2.5 text-left transition-colors duration-150 sm:flex-row sm:gap-3",
                  on ? "bg-accent-soft/40" : "hover:bg-bg-subtle",
                )}
                style={
                  on ? { boxShadow: `inset 3px 0 0 ${CLAIM_VERDICT[c.verdict].tone}` } : undefined
                }
              >
                <span className="shrink-0 sm:mt-0.5 sm:w-44">
                  <ClaimVerdict verdict={c.verdict} short />
                </span>
                <span className="min-w-0 flex-1 text-[13px] leading-relaxed">
                  <span className="block font-medium text-fg">{c.reading.words.join(" · ")}</span>
                  <span className="line-clamp-2 text-muted">
                    <FactSentence text={c.headline} />
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
