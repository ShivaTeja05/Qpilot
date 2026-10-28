/**
 * Where the curves stage stands, above its inbox: how many proposals wait and how many the
 * engine contradicts, where the Curve Judge disagrees (one line per plate, each opening that
 * plate with its proposals), the amplification rule in use, the bulk actions and "check again".
 */
import { count, plural } from "@/lib/format";
import { effectivePayload, ruleWords, type Proposal } from "@/lib/vocab";
import type { SectionProps } from "@/shell/sections";
import { Button } from "@/ui";
import { BulkActions, useStageProposals } from "@/ui/proposal";
import { CheckCurvesButton, type CheckCurvesState } from "./CheckCurves";

export interface PlateDisagreements {
  run: string;
  wells: number;
  contradicted: number;
}

/** The waiting Curve Judge well calls, by plate (most first). */
export function disagreementsByPlate(proposals: readonly Proposal[]): PlateDisagreements[] {
  const by = new Map<string, PlateDisagreements>();
  for (const p of proposals) {
    if (p.status !== "proposed" || p.kind !== "curve.well_call") continue;
    const run = p.subject.slice(0, p.subject.lastIndexOf("/"));
    const row = by.get(run) ?? { run, wells: 0, contradicted: 0 };
    row.wells += 1;
    if (p.check.status === "contradicted") row.contradicted += 1;
    by.set(run, row);
  }
  return [...by.values()].sort((a, b) => b.wells - a.wells || a.run.localeCompare(b.run));
}

/** One sentence: how many wells, on which plates, and how many the engine's check refutes. */
export function disagreementSentence(rows: readonly PlateDisagreements[]): string {
  const wells = rows.reduce((n, r) => n + r.wells, 0);
  const refuted = rows.reduce((n, r) => n + r.contradicted, 0);
  const where =
    rows.length === 1 ? `all on plate ${rows[0]!.run}` : `on ${count(rows.length)} plates`;
  const check =
    refuted === wells
      ? `the engine’s check refutes ${wells === 1 ? "it" : `all ${count(wells)}`}`
      : refuted === 0
        ? "the engine’s check refutes none of them"
        : `the engine’s check refutes ${count(refuted)} of them`;
  return `The Curve Judge reads ${plural(wells, "well")} differently from LinRegPCR, ${where}; ${check}.`;
}

export function StageBar({
  workspace,
  check,
  onShowPlate,
  cqOnly = false,
}: {
  workspace: NonNullable<SectionProps["workspace"]>;
  check: CheckCurvesState;
  /** Open a plate with its waiting proposals (filters the inbox to it). */
  onShowPlate: (run: string) => void;
  /** A file of Cq values only: the rule reads the file's own Cq (docs/cq-tables.md). */
  cqOnly?: boolean;
}) {
  const sid = workspace.key;
  const stage = workspace.stages.find((s) => s.stage === "curves");
  const list = useStageProposals(sid, "curves").data;
  const proposals = list?.proposals ?? [];
  if (!proposals.length) return null;
  const confirmed = Boolean(stage?.confirmed);
  // The confirm step is ConfirmStage's, not a proposal about the curves.
  const waiting = proposals.filter((p) => p.status === "proposed" && p.kind !== "stage.confirm");
  const contradicted = waiting.filter((p) => p.check.status === "contradicted").length;
  const plates = disagreementsByPlate(proposals);
  const rule = proposals.find(
    (p) => p.kind === "curve.call_rule" && (p.status === "accepted" || p.status === "edited"),
  );
  const ruleText = rule
    ? ruleWords(effectivePayload(rule).rule, cqOnly || effectivePayload(rule).basis === "cq")
    : cqOnly
      ? "the file’s own Cq, the engine’s default, until a rule is accepted"
      : "LinRegPCR’s call, the engine’s default, until a rule is accepted";

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-line bg-surface px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="min-w-0 text-[13px] text-muted">
          <p>
            {waiting.length ? (
              <>
                <span className="font-semibold text-fg tabular">{count(waiting.length)}</span>{" "}
                waiting ·{" "}
                <span className="font-semibold text-danger tabular">{count(contradicted)}</span>{" "}
                contradicted
              </>
            ) : confirmed ? (
              "The curves are confirmed. A later decision on a curves proposal re-opens this stage."
            ) : (
              "Every curves proposal is decided: confirm the stage to show the results."
            )}
          </p>
          <p className="mt-0.5">
            Rule in use: <span className="text-fg">{ruleText}</span>
          </p>
        </div>
        {!confirmed ? (
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <BulkActions sid={sid} stage="curves" />
            <CheckCurvesButton state={check} again />
          </div>
        ) : null}
      </div>
      {plates.length ? (
        <div className="border-t border-line pt-3 text-[13px]">
          <p className="text-fg">{disagreementSentence(plates)}</p>
          <ul
            className="mt-2 flex flex-col gap-1"
            aria-label="Where the Curve Judge disagrees, by plate"
          >
            {plates.map((r) => (
              <li key={r.run} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="font-mono text-[12.5px] text-fg">{r.run}</span>
                <span className="text-muted tabular">
                  {plural(r.wells, "well")} · {count(r.contradicted)} contradicted
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Show the plate and its proposals: ${r.run}`}
                  onClick={() => onShowPlate(r.run)}
                >
                  Show the plate and its proposals
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
