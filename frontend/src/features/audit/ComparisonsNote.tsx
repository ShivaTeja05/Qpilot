/**
 * A study with several comparisons: the audit audits the first one alone, and the page says so
 * (the server's words, `scope.comparisons.note`). Nothing for a study with one comparison.
 */
import { GitCompare } from "lucide-react";
import type { Schemas } from "@/api/client";
import { cn } from "@/lib/cn";

export function ComparisonsNote({
  comparisons,
  className,
}: {
  comparisons: Schemas["AuditComparisons"] | null | undefined;
  className?: string;
}) {
  if (!comparisons) return null;
  return (
    <p
      className={cn(
        "flex items-start gap-2 rounded-lg border border-line bg-sunken/60 px-3 py-2 text-[13px] text-fg",
        className,
      )}
      data-testid="audit-comparisons"
    >
      <GitCompare className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
      <span>{comparisons.note}</span>
    </p>
  );
}
