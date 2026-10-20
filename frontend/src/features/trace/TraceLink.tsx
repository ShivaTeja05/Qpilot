/**
 * "Trace this gene": a link to `…/trace/<GENE>` in the current workspace, for other sections'
 * gene rows and pages. Inside a clickable row it does not also open the row. Its accessible name
 * starts with the words it shows (WCAG 2.5.3); the icon-only form is named "Trace <gene>".
 */
import { Route } from "lucide-react";
import { Link } from "wouter";
import { cn } from "@/lib/cn";
import { pathOf, useRoute } from "@/shell/route";

export function TraceLink({
  gene,
  compact,
  className,
}: {
  gene: string;
  /** Icon only (a table row); the accessible name still says what it does. */
  compact?: boolean;
  className?: string;
}) {
  const route = useRoute();
  if (!route.kind || !route.key) return null;
  return (
    <Link
      href={pathOf(route.kind, route.key, "trace", gene)}
      aria-label={compact ? `Trace ${gene}` : undefined}
      title={compact ? `Trace ${gene} down to its samples, wells and plates` : undefined}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-md text-accent underline-offset-4 hover:underline",
        compact ? "p-0.5 opacity-70 hover:opacity-100 focus-visible:opacity-100" : "text-[13px]",
        className,
      )}
    >
      <Route className="size-3.5" aria-hidden />
      {compact ? null : (
        <>
          Trace this gene
          <span className="sr-only">: {gene} down to its samples, wells and plates</span>
        </>
      )}
    </Link>
  );
}
