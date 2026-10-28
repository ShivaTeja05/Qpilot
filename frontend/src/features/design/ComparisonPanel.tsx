/**
 * Which two groups are compared, and which one is the reference (the baseline the fold change
 * is relative to). The groups are those of the design so far with the draft applied.
 */
import { ArrowLeftRight, GitCompareArrows } from "lucide-react";
import { useState } from "react";
import { count } from "@/lib/format";
import { Button, Select } from "@/ui";
import {
  comparisonItem,
  comparisonNow,
  groupsNow,
  withItems,
  type Draft,
  type EditorView,
} from "./draft";

const CONTROL_LIKE =
  /(^|[^a-z])(ctrl|control|vehicle|veh|pbs|wt|wild.?type|untreated|baseline|sham|mock|naive)([^a-z]|$)/i;

export function ComparisonPanel({
  view,
  draft,
  onDraft,
  onGoSamples,
}: {
  view: EditorView;
  draft: Draft;
  onDraft: (next: Draft) => void;
  onGoSamples: () => void;
}) {
  const groups = groupsNow(view, draft);
  const names = [...groups.keys()];
  const now = comparisonNow(view, draft);
  const guessB = names.find((g) => CONTROL_LIKE.test(g)) ?? names[1];
  const guessA = names.find((g) => g !== guessB);
  const [a, setA] = useState<string | undefined>(now?.group_a ?? guessA);
  const [b, setB] = useState<string | undefined>(now?.group_b ?? guessB);
  const groupA = a && groups.has(a) ? a : guessA;
  const groupB = b && groups.has(b) ? b : guessB;

  if (names.length < 2) {
    return (
      <div className="flex flex-col items-start gap-2 text-[13px] text-muted">
        <p>
          {names.length
            ? `Only one group so far (${names[0]}). Put the study samples in at least two groups first.`
            : "No group yet. Put the study samples in their groups first."}
        </p>
        <Button size="sm" variant="secondary" onClick={onGoSamples}>
          Set the groups
        </Button>
      </div>
    );
  }
  const options = names.map((g) => ({
    value: g,
    label: g,
    hint: `${count(groups.get(g) ?? 0)} study sample${groups.get(g) === 1 ? "" : "s"}`,
  }));
  const same = groupA === groupB;
  const isNow = now && now.group_a === groupA && now.group_b === groupB;
  return (
    <div className="flex flex-col gap-3">
      <p className="max-w-prose text-[13px] text-muted">
        The fold change of every gene is the compared group relative to the reference group (the
        baseline, usually the control). qPilot never chooses this for you.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-[13px] font-medium text-fg" id="cmp-a">
            Compared group
          </span>
          <Select
            label="Compared group"
            value={groupA}
            onValueChange={setA}
            options={options}
            className="w-56"
          />
        </div>
        <Button
          size="sm"
          variant="ghost"
          icon={<ArrowLeftRight />}
          aria-label="Swap the two groups"
          onClick={() => {
            setA(groupB);
            setB(groupA);
          }}
        >
          Swap
        </Button>
        <div className="flex flex-col gap-1">
          <span className="text-[13px] font-medium text-fg" id="cmp-b">
            Reference group (baseline)
          </span>
          <Select
            label="Reference group"
            value={groupB}
            onValueChange={setB}
            options={options}
            className="w-56"
          />
        </div>
      </div>
      <p className="text-[13px] text-fg">
        {same ? "Choose two different groups." : `Fold change = ${groupA} relative to ${groupB}.`}
        {names.length > 2
          ? ` ${count(names.length - 2)} other group${names.length === 3 ? " is" : "s are"} not compared.`
          : ""}
      </p>
      <div>
        <Button
          variant="primary"
          icon={<GitCompareArrows />}
          disabled={same || !groupA || !groupB || Boolean(isNow)}
          onClick={() =>
            groupA && groupB && onDraft(withItems(draft, [comparisonItem(groupA, groupB)]))
          }
        >
          {isNow ? "This is the comparison" : "Set the comparison"}
        </Button>
      </div>
    </div>
  );
}
