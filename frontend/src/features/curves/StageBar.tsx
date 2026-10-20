/**
 * Where the curves stage stands, above its inbox: how many proposals wait and how many the
 * engine contradicts, the amplification rule in use, the bulk actions and "check again".
 */
import { count } from "@/lib/format";
import { effectivePayload, ruleWords } from "@/lib/vocab";
import type { SectionProps } from "@/shell/sections";
import { BulkActions, useStageProposals } from "@/ui/proposal";
import { CheckCurvesButton, type CheckCurvesState } from "./CheckCurves";

export function StageBar({
  workspace,
  check,
}: {
  workspace: NonNullable<SectionProps["workspace"]>;
  check: CheckCurvesState;
}) {
  const sid = workspace.key;
  const stage = workspace.stages.find((s) => s.stage === "curves");
  const list = useStageProposals(sid, "curves").data;
  const proposals = list?.proposals ?? [];
  if (!proposals.length) return null;
  const confirmed = Boolean(stage?.confirmed);
  const waiting = proposals.filter((p) => p.status === "proposed");
  const contradicted = waiting.filter((p) => p.check.status === "contradicted").length;
  // The bulk actions are for proposals about the curves, not the confirm step.
  const curvesWaiting = waiting.filter((p) => p.kind !== "stage.confirm").length;
  const rule = proposals.find(
    (p) => p.kind === "curve.call_rule" && (p.status === "accepted" || p.status === "edited"),
  );
  const ruleText = rule
    ? ruleWords(effectivePayload(rule).rule)
    : "LinRegPCR’s call, the engine’s default, until a rule is accepted";

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-line bg-surface px-4 py-3">
      <div className="min-w-0 text-[13px] text-muted">
        <p>
          {waiting.length ? (
            <>
              <span className="font-semibold text-fg tabular">{count(waiting.length)}</span> waiting
              · <span className="font-semibold text-danger tabular">{count(contradicted)}</span>{" "}
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
          {curvesWaiting ? <BulkActions sid={sid} stage="curves" pending={curvesWaiting} /> : null}
          <CheckCurvesButton state={check} again />
        </div>
      ) : null}
    </div>
  );
}
