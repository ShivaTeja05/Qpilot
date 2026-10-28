/**
 * A gene's page in a study with several comparisons: which comparison the page shows (the
 * picker Results and Trace use; one choice shared by the three), and what follows it: the call,
 * the values per unit and the figure. The robustness audit audits the first comparison only.
 */
import { ComparisonPicker } from "@/features/results/ComparisonsPanel";
import type { ResultsView } from "./api";

export function GeneComparisons({
  tabs,
  value,
  onChange,
  audited,
}: {
  tabs: ResultsView["comparisons"];
  value: string;
  onChange: (id: string) => void;
  audited: boolean;
}) {
  const shown = tabs.find((t) => t.id === value) ?? tabs[0]!;
  const first = tabs[0]!;
  return (
    <div className="mb-4 flex flex-col gap-1.5" data-testid="gene-comparisons">
      <ComparisonPicker tabs={tabs} value={shown.id} onChange={onChange} />
      <p className="text-[12.5px] text-muted" role="status">
        Showing {shown.label}: the call, what holds, each unit&apos;s value and the figure are this
        comparison&apos;s; the figure draws every group.
        {audited && shown.id !== first.id
          ? ` The robustness audit audits ${first.label} only, so its views are not shown here.`
          : ""}
      </p>
    </div>
  );
}
