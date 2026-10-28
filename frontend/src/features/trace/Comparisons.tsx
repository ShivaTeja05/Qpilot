/**
 * In a study with several comparisons: which one Trace follows (the picker Results uses, one
 * choice shared by Results, Trace and the gene's page) and how its call is made. Nothing for a
 * study with one comparison.
 */
import { useResults } from "@/features/results/api";
import { useShownComparison } from "@/features/results/comparison";
import { ComparisonPicker } from "@/features/results/ComparisonsPanel";
import type { TraceScope } from "./api";

export function TraceComparisons({ scope, rule }: { scope: TraceScope; rule?: string | null }) {
  const results = useResults(scope.key, scope.studyId);
  const [comparison, setComparison] = useShownComparison(scope.studyId);
  const tabs = results.data?.comparisons ?? [];
  if (tabs.length < 2) return null;
  const shown = tabs.find((t) => t.id === comparison) ?? tabs[0]!;
  return (
    <div className="mb-5 flex flex-col gap-1.5" data-testid="trace-comparisons">
      <ComparisonPicker tabs={tabs} value={shown.id} onChange={setComparison} />
      <p className="text-[12.5px] text-muted" role="status">
        Tracing {shown.label}: every sample set aside is set aside in every comparison, and the call
        is this comparison&apos;s{rule ? ` (${rule})` : ""}. Pick another comparison to trace it.
      </p>
    </div>
  );
}
