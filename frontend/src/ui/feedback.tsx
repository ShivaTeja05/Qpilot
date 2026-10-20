/** Loading, empty and progress states. Empty states always say what to do next. */
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/** A placeholder block while data loads (shimmer stops under reduced motion). */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("qp-skeleton rounded-md", className)} />;
}

/** A few skeleton lines with a screen-reader "Loading …" message. */
export function LoadingBlock({
  label = "Loading",
  lines = 3,
  className,
}: {
  label?: string;
  lines?: number;
  className?: string;
}) {
  return (
    <div role="status" className={cn("flex flex-col gap-2", className)}>
      <span className="sr-only">{label}…</span>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn("h-4", i === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}

/** Nothing here yet: an icon, what this place is for, and the action that fills it. */
export function EmptyState({
  icon,
  title,
  children,
  action,
  className,
  compact,
  headingLevel = 2,
}: {
  icon?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
  compact?: boolean;
  /** The title's heading level (1 when the empty state is the whole page section). */
  headingLevel?: 1 | 2 | 3;
}) {
  const H = `h${headingLevel}` as "h1" | "h2" | "h3";
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed border-line-strong text-center",
        compact ? "gap-2 px-4 py-6" : "gap-3 px-6 py-12",
        className,
      )}
    >
      {icon ? (
        <div
          className="flex size-10 items-center justify-center rounded-full bg-bg-subtle text-muted [&_svg]:size-5"
          aria-hidden
        >
          {icon}
        </div>
      ) : null}
      <div className="max-w-md">
        <H className="text-sm font-semibold text-fg">{title}</H>
        {children ? <div className="mt-1 text-[13px] text-muted">{children}</div> : null}
      </div>
      {action ? (
        <div className="mt-1 flex flex-wrap items-center justify-center gap-2">{action}</div>
      ) : null}
    </div>
  );
}

/** A thin progress bar: determinate with `value` (0–1), indeterminate without. */
export function ProgressBar({
  value,
  label,
  className,
}: {
  value?: number | null;
  label: string;
  className?: string;
}) {
  const known = value != null && Number.isFinite(value);
  const pct = known ? Math.round(Math.min(1, Math.max(0, value)) * 100) : undefined;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      className={cn("relative h-1.5 w-full overflow-hidden rounded-full bg-bg-subtle", className)}
    >
      {known ? (
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-300 ease-out"
          style={{ width: `${pct}%` }}
        />
      ) : (
        <div className="qp-indeterminate absolute inset-y-0 w-2/5 rounded-full bg-accent/70" />
      )}
    </div>
  );
}
