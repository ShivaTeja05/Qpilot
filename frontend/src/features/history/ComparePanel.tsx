/**
 * Compare with another analysis of this file (before and after a Prism round trip, say): which
 * conclusions differ and why — the design (what changed in it, item by item) or the choices in
 * force. When the later analysis' grid holds the earlier choices, the server splits every change
 * exactly into what the design did and what the choices did.
 */
import { ArrowRight, GitCompare } from "lucide-react";
import { useState } from "react";
import { count, dateTime } from "@/lib/format";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorPanel,
  Field,
  LoadingBlock,
  Select,
} from "@/ui";
import { useHistoryCompare, type HistoryView, type RelatedStudy } from "./api";
import { ChoiceChanges, GeneChanges } from "./Changes";

function studyOption(r: RelatedStudy) {
  const when = r.created_at ? dateTime(r.created_at) : "time unknown";
  return {
    value: r.study_id,
    label: `${r.study_id} · ${when}`,
    hint: [
      r.after ? `after: ${r.after}` : null,
      `${count(r.n_entries)} ${r.n_entries === 1 ? "chain entry" : "chain entries"}`,
      r.current ? "the session's current analysis" : null,
    ]
      .filter(Boolean)
      .join(" · "),
  };
}

export function ComparePanel({
  wkey,
  view,
  onGene,
  onOpenStudy,
}: {
  wkey: string;
  view: HistoryView;
  onGene: (gene: string) => void;
  onOpenStudy: (studyId: string) => void;
}) {
  const [other, setOther] = useState<string | null>(view.related[0]?.study_id ?? null);
  const picked = view.related.some((r) => r.study_id === other)
    ? other
    : (view.related[0]?.study_id ?? null);
  const compare = useHistoryCompare(wkey, view.study_id, picked);
  const c = compare.data;

  return (
    <Card as="section" aria-labelledby="compare-title">
      <CardHeader
        id="compare-title"
        title="Compare with another analysis of this file"
        hint="The same input file analysed with another design (a Prism round trip that leaves a value out makes one): which conclusions differ, and whether the design or the choices did it."
      />
      <CardBody className="space-y-4">
        {!view.related.length ? (
          <EmptyState
            icon={<GitCompare />}
            title="This is the only analysis of this file"
            compact
            headingLevel={3}
          >
            A change to the confirmed design (a well left out after a Prism round trip, a sample
            moved to another group) makes another analysis of the same file. It will show here, with
            what changed.
          </EmptyState>
        ) : (
          <>
            <div className="flex flex-wrap items-end gap-2">
              <Field label="The other analysis">
                <Select
                  size="sm"
                  className="w-full sm:w-auto sm:min-w-[280px]"
                  value={picked ?? undefined}
                  options={view.related.map(studyOption)}
                  onValueChange={setOther}
                />
              </Field>
              {picked ? (
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<ArrowRight />}
                  onClick={() => onOpenStudy(picked)}
                >
                  Open its history
                </Button>
              ) : null}
            </div>
            {compare.isPending ? (
              <LoadingBlock label="Comparing the two analyses" lines={3} />
            ) : compare.error ? (
              <ErrorPanel error={compare.error} compact onRetry={() => compare.refetch()} />
            ) : c ? (
              <div className="space-y-4 text-[13px]">
                <p className="rounded-lg bg-sunken/60 px-3 py-2 font-medium text-fg">{c.summary}</p>
                <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
                  {(
                    [
                      ["Earlier", c.before],
                      ["Later", c.after],
                    ] as const
                  ).map(([word, side]) => (
                    <div key={word} className="rounded-lg border border-line px-3 py-2">
                      <dt className="text-[12px] text-muted">
                        {word}
                        {side.study_id === view.study_id ? " (this analysis)" : ""}
                        {side.current ? " · the session's current analysis" : ""}
                      </dt>
                      <dd className="font-mono text-[12px] text-fg">{side.study_id}</dd>
                      <dd className="text-[12px] text-faint">
                        {side.created_at ? dateTime(side.created_at) : null} ·{" "}
                        {count(side.n_entries)}{" "}
                        {side.n_entries === 1 ? "chain entry" : "chain entries"} · ▲{" "}
                        {count(side.counts.up ?? 0)} ▼ {count(side.counts.down ?? 0)} —{" "}
                        {count(side.counts.none ?? 0)}
                      </dd>
                    </div>
                  ))}
                </dl>
                {c.design.length ? (
                  <div className="space-y-1.5">
                    <h3 className="font-semibold text-fg">What differs in the design</h3>
                    <ul className="space-y-1.5">
                      {c.design.map((d) => (
                        <li key={d.field} className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                          <span className="text-muted">{d.title}:</span>
                          {d.added.map((a) => (
                            <code
                              key={`+${a}`}
                              className="rounded bg-ok-soft px-1.5 font-mono text-[12px] text-ok"
                            >
                              + {a}
                            </code>
                          ))}
                          {d.removed.map((a) => (
                            <code
                              key={`-${a}`}
                              className="rounded bg-danger-soft px-1.5 font-mono text-[12px] text-danger"
                            >
                              − {a}
                            </code>
                          ))}
                          {d.before != null || d.after != null ? (
                            <span className="font-mono text-[12px]">
                              {d.before ?? "—"} → {d.after ?? "—"}
                            </span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {c.choices.length ? (
                  <div className="space-y-1.5">
                    <h3 className="font-semibold text-fg">Choices in force that differ</h3>
                    <ChoiceChanges rows={c.choices} />
                  </div>
                ) : null}
                <div className="space-y-1.5">
                  <h3 className="font-semibold text-fg">
                    Calls that differ ({count(c.calls_changed.length)})
                  </h3>
                  <GeneChanges
                    rows={c.calls_changed}
                    caption="Genes whose call differs between the two analyses"
                    onGene={onGene}
                    showCause
                    empty="Every gene has the same call in both analyses."
                  />
                </div>
                {c.fold_moves.length ? (
                  <div className="space-y-1.5">
                    <h3 className="font-semibold text-fg">
                      Fold changes that moved{" "}
                      <span className="font-normal text-muted">
                        ({count(c.fold_moves.length)} of {count(c.n_moved)})
                      </span>
                    </h3>
                    <GeneChanges
                      rows={c.fold_moves}
                      caption="Fold changes that moved between the two analyses"
                      onGene={onGene}
                    />
                  </div>
                ) : null}
                {c.genes_only_before.length || c.genes_only_after.length ? (
                  <p className="text-muted">
                    {c.genes_only_before.length
                      ? `Only in the earlier analysis: ${c.genes_only_before.join(", ")}. `
                      : ""}
                    {c.genes_only_after.length
                      ? `Only in the later analysis: ${c.genes_only_after.join(", ")}.`
                      : ""}
                  </p>
                ) : null}
              </div>
            ) : null}
          </>
        )}
      </CardBody>
    </Card>
  );
}
