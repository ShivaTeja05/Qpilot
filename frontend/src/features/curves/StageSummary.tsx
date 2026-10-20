/**
 * Where the curves stage stands: confirmed or not, the amplification rule in use, how many
 * proposals wait / were accepted / were rejected, and the waiting ones (each opens its well).
 */
import { CheckCircle2, CircleDashed, Hourglass } from "lucide-react";
import { count } from "@/lib/format";
import { KIND_TITLE } from "@/lib/vocab";
import type { SectionProps } from "@/shell/sections";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CheckTag,
  ErrorPanel,
  LoadingBlock,
} from "@/ui";
import { useCurveProposals } from "./api";

export function StageSummary({
  workspace,
  onOpenWell,
}: {
  workspace: NonNullable<SectionProps["workspace"]>;
  onOpenWell: (key: string) => void;
}) {
  const sid = workspace.key;
  const stage = workspace.stages.find((s) => s.stage === "curves");
  const inbox = useCurveProposals(sid);
  const list = inbox.data;
  const proposals = list?.proposals ?? [];
  const rule = proposals.find(
    (p) => p.kind === "curve.call_rule" && (p.status === "accepted" || p.status === "edited"),
  );
  const waiting = proposals.filter((p) => p.status === "proposed" && p.kind !== "stage.confirm");
  const decided = (s: string) =>
    proposals.filter((p) => p.status === s && p.kind !== "stage.confirm").length;

  const status = stage?.confirmed
    ? {
        icon: <CheckCircle2 className="size-4 text-ok" aria-hidden />,
        words: "Confirmed: the curves are decided.",
      }
    : waiting.length
      ? {
          icon: <Hourglass className="size-4 text-warn" aria-hidden />,
          words: `${count(waiting.length)} proposal${waiting.length === 1 ? "" : "s"} waiting for you.`,
        }
      : proposals.length
        ? {
            icon: <CircleDashed className="size-4 text-muted" aria-hidden />,
            words: "Nothing waiting: confirm the stage when you are ready.",
          }
        : {
            icon: <CircleDashed className="size-4 text-muted" aria-hidden />,
            words: "Not checked yet: Check the curves first.",
          };

  return (
    <Card as="section" aria-labelledby="curves-stage-title">
      <CardHeader
        id="curves-stage-title"
        title="The curves stage"
        hint={status.words}
        actions={status.icon}
      />
      <CardBody className="flex flex-col gap-4">
        {inbox.error ? (
          <ErrorPanel error={inbox.error} onRetry={() => void inbox.refetch()} compact />
        ) : !list ? (
          <LoadingBlock label="Reading the curves inbox" lines={2} />
        ) : (
          <>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px]">
              <dt className="text-muted">Rule in use</dt>
              <dd className="m-0 text-fg">
                {rule
                  ? (list.descriptions[rule.id] ?? KIND_TITLE[rule.kind])
                  : "LinRegPCR’s call (the engine’s default), until you accept a rule"}
              </dd>
              <dt className="text-muted">Decided</dt>
              <dd className="m-0 text-fg tabular">
                {count(decided("accepted") + decided("edited"))} accepted ·{" "}
                {count(decided("rejected"))} rejected · {count(waiting.length)} waiting
              </dd>
            </dl>
            {waiting.length ? (
              <ul className="flex flex-col divide-y divide-line rounded-lg border border-line">
                {waiting.map((p) => {
                  const well =
                    p.evidence.find((e) => e.kind === "well" || e.kind === "curve")?.ref ??
                    (p.kind === "curve.well_call" ? p.subject : null);
                  return (
                    <li
                      key={p.id}
                      className="flex flex-wrap items-center justify-between gap-2 px-3 py-2"
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 text-[12px] text-muted">
                          <span>{KIND_TITLE[p.kind]}</span>
                          <CheckTag status={p.check.status} />
                          <Badge>{p.level}</Badge>
                        </div>
                        <p className="mt-0.5 text-[13px] text-fg">
                          {list.descriptions[p.id] ?? p.subject}
                        </p>
                      </div>
                      {well ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label={`Open the curve of well ${well.slice(well.lastIndexOf("/") + 1)}`}
                          onClick={() => onOpenWell(well)}
                        >
                          Open the curve
                        </Button>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </>
        )}
      </CardBody>
    </Card>
  );
}
