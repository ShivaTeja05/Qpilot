import type { ReactNode } from "react";
import { Card, CardBody, CardHeader } from "@/ui";
import { cn } from "@/lib/cn";

/** One block of the Gene section: a card with a heading the page's jump list can scroll to. */
export function Panel({
  id,
  title,
  hint,
  actions,
  children,
  className,
}: {
  id: string;
  title: ReactNode;
  hint?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card as="section" aria-labelledby={`${id}-title`} id={id} className={cn("scroll-mt-6", className)}>
      <CardHeader id={`${id}-title`} title={title} hint={hint} actions={actions} />
      <CardBody>{children}</CardBody>
    </Card>
  );
}

/** A labelled fact inside a panel (a number with its words). */
export function Stat({ label, value, sub }: { label: ReactNode; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-0.5 font-mono text-lg font-semibold text-fg tabular">{value}</div>
      {sub ? <div className="text-xs text-muted">{sub}</div> : null}
    </div>
  );
}

/** A plain list of sentences from the engine or the audit. */
export function Sentences({ items, className }: { items: readonly string[]; className?: string }) {
  if (!items.length) return null;
  return (
    <ul className={cn("space-y-1.5 text-[13px] text-fg", className)}>
      {items.map((s, i) => (
        <li key={`${i}:${s}`} className="flex gap-2">
          <span aria-hidden className="mt-[7px] size-1 shrink-0 rounded-full bg-faint" />
          <span className="min-w-0">{s}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * Label / value rows for a narrow column: the label wraps, the value stays whole on the right
 * (the kit's KeyValues squeezes long values when its labels are long).
 */
export function FactRows({ rows, className }: { rows: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={cn("divide-y divide-line text-[13px]", className)}>
      {rows.map(([k, v], i) => (
        <div key={i} className="flex items-baseline justify-between gap-3 py-1.5 first:pt-0 last:pb-0">
          <dt className="min-w-0 text-muted">{k}</dt>
          <dd className="max-w-[65%] shrink-0 text-right font-mono text-fg tabular">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
