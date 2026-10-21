/**
 * Against a study: the genes whose sheet arithmetic reproduces but whose fold change differs from
 * qPilot's analysis (hand-overs — a difference of method, not a slip), each in the check's own
 * words with what visibly differs. Then the genes the sheet names (with any name that looks like
 * a date a spreadsheet made from it) and the check's notes.
 */
import { ArrowUpRight, CalendarX2, Dna, Info } from "lucide-react";
import { useId } from "react";
import { Link } from "wouter";
import { Badge, Card, CardBody, CardHeader } from "@/ui";
import type { WorkspaceSummary } from "@/shell/data";
import { pathOf } from "@/shell/route";
import type { SheetCheckView } from "./api";
import { FactText } from "./FactText";
import { causeWords } from "./words";

export function HandOvers({
  view,
  study,
}: {
  view: SheetCheckView;
  /** The compared study's workspace (for the link to its robustness audit). */
  study: WorkspaceSummary | undefined;
}) {
  const titleId = useId();
  if (!view.study_id) return null;
  const audit = study ? pathOf(study.kind === "session" ? "s" : "r", study.key, "audit") : null;
  return (
    <Card as="section" aria-labelledby={titleId}>
      <CardHeader
        id={titleId}
        title="Handed over to the study"
        hint={study ? `Compared with ${study.title}.` : "Compared with the study you chose."}
        actions={
          audit ? (
            <Link
              href={audit}
              className="inline-flex items-center gap-1 rounded-md text-[13px] font-medium text-accent underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            >
              Open its robustness audit
              <ArrowUpRight className="size-3.5" aria-hidden />
            </Link>
          ) : null
        }
      />
      <CardBody>
        {view.hand_overs.length ? (
          <ul className="flex flex-col gap-3">
            {view.hand_overs.map((h) => (
              <li key={h.gene} className="rounded-lg border border-line bg-surface-2 p-3">
                <div className="mb-1.5 flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[13px] font-semibold text-fg">{h.gene}</span>
                  {h.conclusion_differs ? (
                    <Badge tone="warn">The call differs</Badge>
                  ) : (
                    <Badge tone="neutral">Same call</Badge>
                  )}
                </div>
                <p className="text-[13px] leading-relaxed text-fg">
                  <FactText text={h.line} />
                </p>
                {h.causes.length ? (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                    <span>What differs:</span>
                    {h.causes.map((c) => (
                      <Badge key={c} tone="info">
                        {causeWords(c)}
                      </Badge>
                    ))}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-muted">
            No gene was handed over: where the sheet's arithmetic reproduces, its fold changes match
            qPilot's analysis of this study, or the study has no counterpart for the gene (see the
            notes).
          </p>
        )}
      </CardBody>
    </Card>
  );
}

/** The genes the sheet names, and any name that looks like a date a spreadsheet made. */
export function Genes({ view }: { view: SheetCheckView }) {
  const titleId = useId();
  if (!view.genes.length) return null;
  const flagged = view.genes.filter((g) => g.flagged);
  return (
    <Card as="section" aria-labelledby={titleId}>
      <CardHeader
        id={titleId}
        title="Gene names"
        hint="Each name in the sheet goes through the gene-symbol check."
      />
      <CardBody className="flex flex-col gap-3">
        {flagged.length ? (
          <ul className="flex flex-col gap-2" aria-label="Gene names to check">
            {flagged.map((g) => (
              <li
                key={g.key}
                className="flex items-start gap-2.5 rounded-lg border border-warn/30 bg-warn-soft/50 p-3 text-[13px]"
              >
                <CalendarX2 className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
                <div className="min-w-0">
                  <p>
                    <span className="font-mono font-semibold text-fg">{g.key}</span>{" "}
                    <Badge tone="warn">Check this name</Badge>
                  </p>
                  <p className="mt-0.5 text-muted">{g.note}</p>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
        <ul className="flex flex-wrap gap-1.5" aria-label="Genes in the sheet">
          {view.genes.map((g) => (
            <li
              key={g.key}
              title={g.note}
              className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2 py-0.5 text-[12.5px]"
            >
              <Dna className="size-3 text-muted" aria-hidden />
              <span className="font-mono text-fg">{g.key}</span>
              {g.reference ? <span className="text-xs text-muted">reference</span> : null}
              {g.flagged ? <span className="text-xs text-warn">check the name</span> : null}
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}

/** What the check noted (in its own words). */
export function Notes({ view }: { view: SheetCheckView }) {
  const titleId = useId();
  if (!view.notes.length) return null;
  return (
    <Card as="section" aria-labelledby={titleId}>
      <CardHeader id={titleId} title="Notes from the check" />
      <CardBody>
        <ul className="flex flex-col gap-2 text-[13px]">
          {view.notes.map((n, i) => (
            <li key={i} className="flex gap-2">
              <Info className="mt-0.5 size-3.5 shrink-0 text-info" aria-hidden />
              <span className="text-fg">{n}</span>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
