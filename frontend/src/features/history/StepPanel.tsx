/**
 * The selected point in words: who did what and why, its place in the hash chain, what it
 * changed against the point before (the server's diff, or its comparison with the earlier
 * analysis), and every choice in force at that point.
 */
import { ArrowRight, Link2, Unlink } from "lucide-react";
import { cn } from "@/lib/cn";
import { dateTime } from "@/lib/format";
import { Badge, Button, Card, CardBody, CardHeader, ErrorPanel, Hash, LoadingBlock } from "@/ui";
import { useHistoryCompare, useHistoryDiff, type ChoiceInForce, type HistoryView } from "./api";
import { ChoiceChanges, GeneChanges } from "./Changes";
import type { Point } from "./model";
import { ACTOR_LOWER, ACTOR_WORD, STATUS_WORD, pointTitle } from "./words";

const SHOWN = 6;

function Choices({ choices }: { choices: ChoiceInForce[] }) {
  return (
    <ul className="divide-y divide-line rounded-lg border border-line">
      {choices.map((c) => (
        <li key={c.card_id} className="flex flex-col gap-0.5 px-3 py-2 text-[13px]">
          <span className="text-muted">{c.title}</span>
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="font-medium text-fg">{c.option_label}</span>
            {c.planned ? (
              <Badge tone="neutral">as planned</Badge>
            ) : (
              <Badge tone="warn">not the planned option</Badge>
            )}
            <span className="text-[12px] text-faint">
              {c.decided
                ? `decided by ${ACTOR_LOWER[c.decided_by ?? ""] ?? "someone"}`
                : "not decided yet"}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** What a step changed: the server's diff of the step before and this one. */
function StepChange({
  wkey,
  studyId,
  from,
  to,
  onGene,
}: {
  wkey: string;
  studyId: string;
  from: number;
  to: number;
  onGene: (gene: string) => void;
}) {
  const diff = useHistoryDiff(wkey, studyId, from, to);
  if (diff.isPending) return <LoadingBlock label="Reading what changed" lines={2} />;
  if (diff.error) return <ErrorPanel error={diff.error} compact onRetry={() => diff.refetch()} />;
  const d = diff.data;
  if (d.same_analysis) return null;
  return (
    <div className="space-y-3">
      <ChoiceChanges rows={d.choices} />
      <GeneChanges
        rows={d.calls_changed}
        caption="Genes whose call changed at this step"
        onGene={onGene}
        showVerdict={d.calls_changed.some((g) => g.verdict)}
      />
      {d.fold_moves.length ? (
        <div className="space-y-1.5">
          <h4 className="text-[12px] font-medium tracking-wide text-muted uppercase">
            Fold changes that moved most
          </h4>
          <GeneChanges
            rows={d.fold_moves.slice(0, SHOWN)}
            caption="Fold changes that moved most at this step"
            onGene={onGene}
          />
        </div>
      ) : null}
      {d.audit_note ? <p className="text-[12px] text-faint">{d.audit_note}</p> : null}
    </div>
  );
}

/** What the change from the earlier analysis did (the comparison of the two analyses). */
function RoundTripChange({
  wkey,
  studyId,
  other,
  onGene,
}: {
  wkey: string;
  studyId: string;
  other: string;
  onGene: (gene: string) => void;
}) {
  const compare = useHistoryCompare(wkey, studyId, other);
  if (compare.isPending) return <LoadingBlock label="Comparing the two analyses" lines={2} />;
  if (compare.error)
    return <ErrorPanel error={compare.error} compact onRetry={() => compare.refetch()} />;
  const c = compare.data;
  return (
    <div className="space-y-3">
      <p className="text-[13px] text-fg">{c.summary}</p>
      {c.design.length ? (
        <ul className="space-y-1 text-[13px]">
          {c.design.map((d) => (
            <li key={d.field}>
              <span className="text-muted">{d.title}: </span>
              {d.added.map((a) => (
                <code
                  key={a}
                  className="mr-1 rounded bg-ok-soft px-1 font-mono text-[12px] text-ok"
                >
                  + {a}
                </code>
              ))}
              {d.removed.map((a) => (
                <code
                  key={a}
                  className="mr-1 rounded bg-danger-soft px-1 font-mono text-[12px] text-danger"
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
      ) : null}
      <GeneChanges
        rows={c.calls_changed}
        caption="Genes whose call differs between the two analyses"
        onGene={onGene}
        showCause
      />
      {c.fold_moves.length ? (
        <GeneChanges
          rows={c.fold_moves.slice(0, SHOWN)}
          caption="Fold changes that moved most between the two analyses"
          onGene={onGene}
        />
      ) : null}
    </div>
  );
}

export function StepPanel({
  wkey,
  view,
  point,
  previous,
  onGene,
  onOpenStudy,
}: {
  wkey: string;
  view: HistoryView;
  point: Point;
  previous: Point | null;
  onGene: (gene: string) => void;
  onOpenStudy: (studyId: string) => void;
}) {
  if (point.kind === "earlier") {
    return (
      <Card as="section" aria-labelledby="step-title">
        <CardHeader
          id="step-title"
          title="The earlier analysis"
          hint={pointTitle(point)}
          actions={
            <Button
              size="sm"
              variant="secondary"
              icon={<ArrowRight />}
              onClick={() => onOpenStudy(point.study.study_id)}
            >
              Open its history
            </Button>
          }
        />
        <CardBody className="space-y-3 text-[13px]">
          <p className="text-muted">
            This file was analysed before with another design. The map shows its calls as they stood
            after its{" "}
            {point.study.n_entries === 1 ? "one decision" : `${point.study.n_entries} decisions`}.
            Move on to step 0 to see what changed.
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-muted">Analysis</dt>
            <dd className="font-mono">{point.study.study_id}</dd>
            {point.study.created_at ? (
              <>
                <dt className="text-muted">Made</dt>
                <dd>{dateTime(point.study.created_at)}</dd>
              </>
            ) : null}
            {point.study.after ? (
              <>
                <dt className="text-muted">After</dt>
                <dd>{point.study.after}</dd>
              </>
            ) : null}
          </dl>
        </CardBody>
      </Card>
    );
  }

  const step = point.step;
  const status = step.status ? STATUS_WORD[step.status] : null;
  const fromEarlier = previous?.kind === "earlier" ? previous.study.study_id : null;
  return (
    <Card as="section" aria-labelledby="step-title">
      <CardHeader
        id="step-title"
        title={
          step.kind === "start"
            ? "Step 0 · as analysed"
            : `Step ${step.seq} · ${step.card_title ?? step.card_id}`
        }
        hint={step.effect}
      />
      <CardBody className="space-y-4">
        {step.kind === "decision" ? (
          <div className="space-y-2 text-[13px]">
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="font-medium text-fg">
                {ACTOR_WORD[step.actor ?? ""] ?? "Someone"}
              </span>
              <span className="text-muted">
                {step.undo
                  ? "undid back to"
                  : step.status === "pending_human"
                    ? "asked for"
                    : "chose"}
              </span>
              <span className="font-medium text-fg">{step.option_label ?? step.option}</span>
              {status ? <Badge tone={status.tone}>{status.word}</Badge> : null}
            </p>
            {step.reason ? (
              <blockquote className="border-l-2 border-line-strong pl-3 text-muted">
                “{step.reason}”
              </blockquote>
            ) : null}
            {step.at ? <p className="text-[12px] text-faint">{dateTime(step.at)}</p> : null}
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]">
          <Hash value={step.hash} prefix={step.kind === "start" ? "input" : "entry"} />
          {step.prev_hash ? (
            <>
              <span className="text-faint">links to</span>
              <Hash value={step.prev_hash} />
            </>
          ) : null}
          <Badge tone={step.link_ok ? "ok" : "danger"} icon={step.link_ok ? <Link2 /> : <Unlink />}>
            {step.link_ok ? "hash checks out" : "this link is broken"}
          </Badge>
        </div>

        <section aria-label="What changed" className={cn("space-y-2")}>
          <h3 className="text-[13px] font-semibold text-fg">
            {fromEarlier ? "What changed since the earlier analysis" : "What changed here"}
          </h3>
          {fromEarlier ? (
            <RoundTripChange
              wkey={wkey}
              studyId={view.study_id}
              other={fromEarlier}
              onGene={onGene}
            />
          ) : step.seq > 0 &&
            step.conclusions &&
            !step.conclusions.n_changed &&
            !step.conclusions.n_moved ? (
            <p className="text-[13px] text-muted">No call changed and no fold change moved.</p>
          ) : step.seq > 0 && step.analysis != null ? (
            <StepChange
              wkey={wkey}
              studyId={view.study_id}
              from={step.seq - 1}
              to={step.seq}
              onGene={onGene}
            />
          ) : (
            <p className="text-[13px] text-muted">
              {step.seq === 0
                ? "The starting point: the analysis as planned, before any decision."
                : (view.note ?? "This step cannot be replayed.")}
            </p>
          )}
        </section>

        <section aria-label="Choices in force" className="space-y-2">
          <h3 className="text-[13px] font-semibold text-fg">Choices in force at this point</h3>
          <Choices choices={step.choices} />
        </section>
      </CardBody>
    </Card>
  );
}
