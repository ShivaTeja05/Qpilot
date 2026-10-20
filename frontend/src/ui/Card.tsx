import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

/** A surface with a 1 px line and a 12 px radius; no shadow (only floating layers have one). */
export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement> & { as?: "div" | "section" | "article" | "li" }>(
  function Card({ className, as: As = "div", ...rest }, ref) {
    // One element type for the props; the tag only changes semantics.
    const Comp = As as "div";
    return (
      <Comp
        ref={ref}
        className={cn("rounded-xl border border-line bg-surface", className)}
        {...rest}
      />
    );
  },
);

/** A card's header row: a title (and a hint) on the left, actions on the right. */
export function CardHeader({
  title,
  hint,
  actions,
  className,
  id,
  level = 2,
}: {
  title: ReactNode;
  hint?: ReactNode;
  actions?: ReactNode;
  className?: string;
  id?: string;
  level?: 2 | 3;
}) {
  const H = level === 2 ? "h2" : "h3";
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-x-4 gap-y-2 px-4 pt-4 pb-3", className)}>
      <div className="min-w-0">
        <H id={id} className="text-[15px] font-semibold tracking-tight text-fg">
          {title}
        </H>
        {hint ? <p className="mt-0.5 text-[13px] text-muted">{hint}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function CardBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-4 pb-4", className)} {...rest} />;
}

/** A section heading inside a page (not a card): eyebrow-sized title with an optional hint. */
export function SectionTitle({
  children,
  hint,
  actions,
  className,
  id,
}: {
  children: ReactNode;
  hint?: ReactNode;
  actions?: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <div className={cn("mb-3 flex flex-wrap items-end justify-between gap-2", className)}>
      <div className="min-w-0">
        <h2 id={id} className="text-base font-semibold tracking-tight text-fg">
          {children}
        </h2>
        {hint ? <p className="mt-0.5 text-[13px] text-muted">{hint}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/** The page title of a section, with its one-line purpose. */
export function PageHeader({
  title,
  hint,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  hint?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0 max-w-3xl">
        {eyebrow ? <div className="mb-1 text-xs font-medium uppercase tracking-wider text-faint">{eyebrow}</div> : null}
        <h1 className="text-2xl font-semibold tracking-tight text-fg">{title}</h1>
        {hint ? <p className="mt-1 text-sm text-muted">{hint}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

/** Label / value pairs (file facts, a check's numbers). */
export function KeyValues({ rows, className }: { rows: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[13px]", className)}>
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words text-fg tabular">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
