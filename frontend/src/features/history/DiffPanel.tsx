/**
 * Compare any two steps of the chain: the calls that changed between them, the fold changes and
 * shares of same-call analyses that moved most, and the choices that differ. The server reads
 * both analyses from the study's grid (`GET …/history/diff`).
 */
import { ArrowLeftRight } from "lucide-react";
import { count } from "@/lib/format";
import {
  Card,
  CardBody,
  CardHeader,
  ConclusionTag,
  ErrorPanel,
  Field,
  IconButton,
  LoadingBlock,
  Select,
} from "@/ui";
import { useHistoryDiff, type HistoryView } from "./api";
import { ChoiceChanges, GeneChanges } from "./Changes";
import { ACTOR_WORD } from "./words";

function stepOption(view: HistoryView, seq: number) {
  const s = view.steps[seq]!;
  if (s.kind === "start") return { value: "0", label: "#0 · As analysed" };
  const who = ACTOR_WORD[s.actor ?? ""] ?? "";
  return {
    value: String(s.seq),
    label: `#${s.seq} · ${s.option_label ?? s.option}`,
    hint: `${who}: ${s.card_title ?? s.card_id}`,
  };
}

function Counts({ counts }: { counts: Record<string, number> }) {
  return (
    <span className="inline-flex items-center gap-2 font-mono text-[12px] tabular">
      {(["up", "down", "none"] as const).map((c) => (
        <span key={c} className="inline-flex items-center gap-1">
          <ConclusionTag conclusion={c} compact />
          {count(counts[c] ?? 0)}
        </span>
      ))}
    </span>
  );
}

export function DiffPanel({
  wkey,
  view,
  from,
  to,
  onChange,
  onGene,
}: {
  wkey: string;
  view: HistoryView;
  from: number;
  to: number;
  onChange: (from: number, to: number) => void;
  onGene: (gene: string) => void;
}) {
  const diff = useHistoryDiff(wkey, view.study_id, from, to, view.comparison ?? null);
  const options = view.steps.map((s) => stepOption(view, s.seq));
  const d = diff.data;
  return (
    <Card as="section" aria-labelledby="diff-title">
      <CardHeader
        id="diff-title"
        title="Compare two points"
        hint="Pick any two steps of the chain: every call that changed between them, and the numbers that moved most."
      />
      <CardBody className="space-y-4">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="From">
            <Select
              size="sm"
              className="w-full sm:w-auto sm:min-w-[220px]"
              value={String(from)}
              options={options}
              onValueChange={(v) => onChange(Number(v), to)}
            />
          </Field>
          <IconButton
            label="Swap the two points"
            size="sm"
            variant="secondary"
            onClick={() => onChange(to, from)}
            className="mb-0.5"
          >
            <ArrowLeftRight />
          </IconButton>
          <Field label="To">
            <Select
              size="sm"
              className="w-full sm:w-auto sm:min-w-[220px]"
              value={String(to)}
              options={options}
              onValueChange={(v) => onChange(from, Number(v))}
            />
          </Field>
        </div>
        {diff.isPending ? (
          <LoadingBlock label="Reading both analyses" lines={3} />
        ) : diff.error ? (
          <ErrorPanel error={diff.error} compact onRetry={() => diff.refetch()} />
        ) : d ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg bg-sunken/60 px-3 py-2 text-[13px]">
              <span className="font-medium text-fg">{d.summary}</span>
              <span className="inline-flex items-center gap-2 text-muted">
                Calls: <Counts counts={d.from_counts} /> → <Counts counts={d.to_counts} />
              </span>
            </div>
            <ChoiceChanges rows={d.choices} />
            {d.same_analysis ? null : (
              <>
                <div className="space-y-1.5">
                  <h3 className="text-[13px] font-semibold text-fg">
                    Calls that changed ({count(d.calls_changed.length)})
                  </h3>
                  <GeneChanges
                    rows={d.calls_changed}
                    caption="Genes whose call changed between the two points"
                    onGene={onGene}
                    showVerdict={d.calls_changed.some((g) => g.verdict)}
                    empty="No call changed between these two points."
                  />
                </div>
                {d.fold_moves.length ? (
                  <div className="space-y-1.5">
                    <h3 className="text-[13px] font-semibold text-fg">
                      Fold changes that moved most{" "}
                      <span className="font-normal text-muted">
                        ({count(d.fold_moves.length)} of {count(d.n_moved)} that moved)
                      </span>
                    </h3>
                    <GeneChanges
                      rows={d.fold_moves}
                      caption="Fold changes that moved most between the two points"
                      onGene={onGene}
                    />
                  </div>
                ) : null}
                {d.holds_moves.length ? (
                  <div className="space-y-1.5">
                    <h3 className="text-[13px] font-semibold text-fg">
                      Robustness that moved most{" "}
                      <span className="font-normal text-muted">
                        (share of the {view.n_cells ? count(view.n_cells) : ""} analyses qPilot
                        checks that give the same call)
                      </span>
                    </h3>
                    <GeneChanges
                      rows={d.holds_moves}
                      caption="Shares of same-call analyses that moved most between the two points"
                      onGene={onGene}
                    />
                  </div>
                ) : null}
              </>
            )}
            {d.audit_note ? <p className="text-[12px] text-faint">{d.audit_note}</p> : null}
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}
