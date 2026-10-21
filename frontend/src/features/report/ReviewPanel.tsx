/**
 * The reviewer's report: what a careful reviewer would flag (most severe first, filterable by
 * severity), each read from the study's numbers, with a way to the section that shows it; then
 * what checks out.
 */
import { ArrowRight, CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { Link } from "wouter";
import { cn } from "@/lib/cn";
import { sectionPath, type SectionProps } from "@/shell/sections";
import { Badge, Button, SegmentedControl } from "@/ui";
import type { Facts, ReportView, ReviewFinding } from "./api";
import { Cited } from "./Cited";
import { GO_TO, SEVERITY, SEVERITY_ORDER, type Severity } from "./words";

type Filter = Severity | "all";

export function ReviewPanel({
  review,
  facts,
  workspace,
}: {
  review: ReportView["review"];
  facts: Facts;
  workspace: SectionProps["workspace"];
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const shown = review.findings.filter((f) => filter === "all" || f.severity === filter);
  return (
    <div className="flex flex-col gap-4">
      <p className="text-[14px] leading-relaxed text-muted">
        <Cited text={review.lead} facts={facts} />
      </p>
      <SegmentedControl<Filter>
        label="Show findings"
        size="sm"
        value={filter}
        onValueChange={setFilter}
        className="self-start"
        options={[
          { value: "all", label: `All ${review.findings.length}` },
          ...SEVERITY_ORDER.map((s) => ({
            value: s,
            label: `${SEVERITY[s].word} ${review.counts[s] ?? 0}`,
            disabled: !review.counts[s],
          })),
        ]}
      />
      <ol className="flex flex-col gap-2.5" aria-label="Findings">
        {shown.map((f) => (
          <Finding key={f.id} finding={f} facts={facts} workspace={workspace} />
        ))}
      </ol>
      {review.passed.length ? (
        <div className="rounded-xl border border-line bg-surface p-4">
          <h3 className="text-[14px] font-semibold text-fg">What checks out</h3>
          <ul className="mt-2 flex flex-col gap-2">
            {review.passed.map((p) => (
              <li key={p.id} className="flex gap-2 text-[13px] leading-relaxed text-muted">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />
                <span>
                  <span className="font-medium text-fg">{p.title}.</span>{" "}
                  <Cited text={p.text} facts={facts} />
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function Finding({
  finding: f,
  facts,
  workspace,
}: {
  finding: ReviewFinding;
  facts: Facts;
  workspace: SectionProps["workspace"];
}) {
  const sev = SEVERITY[f.severity];
  const go = f.go_to ? GO_TO[f.go_to] : null;
  const gene = f.go_to === "gene" ? f.genes[0] : undefined;
  const href = go && workspace ? sectionPath(workspace, go.section, ...(gene ? [gene] : [])) : null;
  return (
    <li
      className={cn(
        "rounded-xl border bg-surface p-4",
        f.severity === "major" ? "border-danger/35" : "border-line",
      )}
    >
      <h3 className="flex min-w-0 flex-wrap items-center gap-2 text-[14px] font-semibold text-fg">
        <Badge tone={sev.tone} title={sev.hint}>
          <span aria-hidden>{sev.glyph}</span> {sev.word}
        </Badge>
        <span className="min-w-0">{f.title}</span>
      </h3>
      <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
        <Cited text={f.text} facts={facts} />
      </p>
      {f.genes.length > 1 && workspace ? (
        <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Genes">
          {f.genes.map((g) => (
            <li key={g}>
              <Link
                href={sectionPath(workspace, "gene", g)}
                className="inline-flex h-6 items-center rounded-md border border-line bg-sunken px-2 font-mono text-[12px] text-fg hover:border-line-strong hover:bg-surface-2"
              >
                {g}
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
      {href && go ? (
        <Button asChild size="sm" variant="ghost" className="-ml-2 mt-1">
          <Link href={href}>
            {gene ? `Open ${gene}` : go.label}
            <ArrowRight aria-hidden />
          </Link>
        </Button>
      ) : null}
    </li>
  );
}
