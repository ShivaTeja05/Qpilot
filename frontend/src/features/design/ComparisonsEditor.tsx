/**
 * Several comparisons, set by a person on the Design page: each group against a control, every
 * pair of groups, or their own list; the correction for comparing several (Holm, Dunnett for a
 * control, Tukey for every pair, or none); and, when the person accepted pairings (a donor or
 * animal column), a paired test. Written as the person's own comparison item; the engine checks
 * it when it is set, and the study is analysed with every comparison.
 */
import { GitCompareArrows, Plus, X } from "lucide-react";
import { useState } from "react";
import { count } from "@/lib/format";
import { Button, IconButton, SegmentedControl, Select, Switch } from "@/ui";
import { withItems, type Draft, type EditorView } from "./draft";
import {
  corrections,
  fittingCorrection,
  pairsWords,
  planItem,
  planNow,
  planPairs,
  type Correction,
  type Pair,
  type Pattern,
  type PlanChoice,
} from "./plan";

const PATTERNS: { value: Pattern; label: string }[] = [
  { value: "vs_control", label: "Each group against a control" },
  { value: "all_pairs", label: "Every pair of groups" },
  { value: "chosen", label: "My own list" },
];

export function ComparisonsEditor({
  view,
  draft,
  onDraft,
  names,
  sizes,
}: {
  view: EditorView;
  draft: Draft;
  onDraft: (next: Draft) => void;
  names: string[];
  sizes: Map<string, number>;
}) {
  const [choice, setChoice] = useState<PlanChoice>(() =>
    planNow(names, view.comparison_plan ?? null),
  );
  const [adding, setAdding] = useState<{ a?: string; b?: string }>({});
  const pairBy = view.pair_by ?? null;
  const update = (next: Partial<PlanChoice>) =>
    setChoice((c) => {
      const merged = { ...c, ...next };
      return { ...merged, correction: fittingCorrection(merged) };
    });
  const pairs = planPairs(names, choice);
  const item = planItem(names, choice, pairBy);
  const problem = typeof item === "string" ? item : null;
  const options = names.map((g) => ({
    value: g,
    label: g,
    hint: `${count(sizes.get(g) ?? 0)} study sample${sizes.get(g) === 1 ? "" : "s"}`,
  }));
  const addPair = () => {
    const { a, b } = adding;
    if (!a || !b || a === b) return;
    update({ pairs: [...choice.pairs, [a, b] as Pair] });
    setAdding({});
  };
  return (
    <div className="flex flex-col gap-3" data-testid="comparisons-editor">
      <p className="max-w-prose text-[13px] text-muted">
        Compare several pairs of groups in one study. Every comparison is analysed with the same
        choices; the first one is listed first everywhere. qPilot never chooses these for you.
      </p>
      <SegmentedControl
        label="Which comparisons"
        size="sm"
        value={choice.pattern}
        onValueChange={(pattern) => update({ pattern })}
        options={PATTERNS}
      />
      {choice.pattern === "vs_control" ? (
        <div className="flex flex-col gap-1">
          <span className="text-[13px] font-medium text-fg">Control group</span>
          <Select
            label="Control group"
            value={choice.control ?? undefined}
            placeholder="Choose the control"
            onValueChange={(control) => update({ control })}
            options={options}
            className="w-56"
          />
        </div>
      ) : null}
      {choice.pattern === "chosen" ? (
        <div className="flex flex-col gap-2">
          <ul className="flex flex-col gap-1" aria-label="Your comparisons">
            {choice.pairs.map(([a, b], i) => (
              <li key={`${a}\u0000${b}`} className="flex items-center gap-2 text-[13px] text-fg">
                <span>
                  {a} <span className="text-muted">relative to</span> {b}
                  {i === 0 ? <span className="text-muted"> (the first)</span> : null}
                </span>
                <IconButton
                  size="sm"
                  label={`Remove ${a} vs ${b}`}
                  icon={<X />}
                  onClick={() => update({ pairs: choice.pairs.filter((_, j) => j !== i) })}
                />
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-end gap-2">
            <Select
              label="Compared group"
              placeholder="Compared group"
              value={adding.a}
              onValueChange={(a) => setAdding((x) => ({ ...x, a }))}
              options={options}
              className="w-48"
            />
            <span className="pb-1.5 text-[13px] text-muted">relative to</span>
            <Select
              label="Reference group"
              placeholder="Reference group"
              value={adding.b}
              onValueChange={(b) => setAdding((x) => ({ ...x, b }))}
              options={options}
              className="w-48"
            />
            <Button
              size="sm"
              variant="secondary"
              icon={<Plus />}
              disabled={!adding.a || !adding.b || adding.a === adding.b}
              onClick={addPair}
            >
              Add
            </Button>
          </div>
        </div>
      ) : null}
      {pairBy && (view.n_paired ?? 0) > 0 ? (
        <Switch
          checked={choice.paired}
          onCheckedChange={(paired) => update({ paired })}
          label={`Paired by ${pairBy}`}
          hint={`${count(view.n_paired ?? 0)} study samples have a ${pairBy}: each comparison is a paired test within each ${pairBy}, so n is the number of complete pairs.`}
        />
      ) : null}
      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1 text-[13px] font-medium text-fg">
          Correction for comparing each gene several times
        </legend>
        {corrections(choice).map((c) => (
          <label
            key={c.value}
            className={
              c.unavailable
                ? "flex cursor-not-allowed items-start gap-2 text-[13px] text-faint"
                : "flex cursor-pointer items-start gap-2 text-[13px] text-fg"
            }
          >
            <input
              type="radio"
              name="correction"
              value={c.value}
              checked={choice.correction === c.value}
              disabled={Boolean(c.unavailable)}
              onChange={() => update({ correction: c.value as Correction })}
              className="mt-1 accent-[var(--accent)]"
            />
            <span>
              <span className="font-medium">{c.label}</span>
              <span className="text-muted"> · {c.unavailable ?? c.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <p className="text-[13px] text-fg" role="status">
        {problem ??
          `${count(pairs.length)} comparison${pairs.length === 1 ? "" : "s"}: ${pairsWords(pairs)}.`}
      </p>
      <div>
        <Button
          variant="primary"
          icon={<GitCompareArrows />}
          disabled={Boolean(problem)}
          onClick={() => typeof item !== "string" && onDraft(withItems(draft, [item]))}
        >
          Set the comparisons
        </Button>
      </div>
    </div>
  );
}
