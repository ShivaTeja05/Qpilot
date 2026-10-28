/**
 * The two sets of analyses behind every "holds" count, said the same way on every page: which
 * count is which, what each is for, and why one gene can hold in a different share of each
 * (docs/user-guide.md §3). The words live in `@/lib/vocab` (mirrored from
 * `qpilot/explain/sets.py`), so Results, Gene, Audit and Report never drift apart.
 */
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/cn";
import { DEFAULT_AUDIT, setsBridge, setsLine } from "@/lib/vocab";

export interface SetsNoteProps {
  /** qPilot's choice grid: the analyses qPilot checks (`n_cells`, 744 on the demo). */
  grid?: number | null;
  /** The audit's reasonable analyses (144 on the demo), when an audit has run. */
  reasonable?: number | null;
  /** Every analysis the audit runs (90 396 on the demo). */
  full?: number | null;
  /** The audit's decision ids (`AuditDecision.id`), when known. */
  decisions?: readonly string[];
  /** qPilot's grid tests the efficiency models too (a person asked). */
  efficiencyInGrid?: boolean;
  className?: string;
}

/** One line naming both counts, with "Why two counts?" folding out the difference. */
export function SetsNote({
  grid,
  reasonable,
  full,
  decisions = DEFAULT_AUDIT,
  efficiencyInGrid,
  className,
}: SetsNoteProps) {
  const line = setsLine({ grid, reasonable, full });
  return (
    <div className={cn("text-[13px] text-muted", className)} data-testid="sets-note">
      {line ? <p>{line}</p> : null}
      <details className="group mt-1">
        <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded text-accent hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent [&::-webkit-details-marker]:hidden">
          <ChevronRight
            className="size-3.5 transition-transform group-open:rotate-90"
            aria-hidden
          />
          Why two counts?
        </summary>
        <p className="mt-1">{setsBridge(decisions, { efficiencyInGrid })}</p>
      </details>
    </div>
  );
}
