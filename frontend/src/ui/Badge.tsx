import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

export type Tone = "neutral" | "accent" | "ok" | "warn" | "danger" | "info";

const TONE: Record<Tone, string> = {
  neutral: "border-line bg-bg-subtle text-muted",
  accent: "border-accent/25 bg-accent-soft text-accent-strong",
  ok: "border-ok/25 bg-ok-soft text-ok",
  warn: "border-warn/30 bg-warn-soft text-warn",
  danger: "border-danger/30 bg-danger-soft text-danger",
  info: "border-info/25 bg-info-soft text-info",
};

/** A small label with meaning carried by its words (colour only reinforces it). */
export function Badge({
  tone = "neutral",
  icon,
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone; icon?: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-md border px-1.5 text-xs font-medium [&_svg]:size-3",
        TONE[tone],
        className,
      )}
      {...rest}
    >
      {icon}
      {children}
    </span>
  );
}

/** A keyboard key: `⌘`, `K`, `?`. */
export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded border border-line-strong border-b-2 bg-surface px-1 font-mono text-[11px] font-medium text-muted",
        className,
      )}
    >
      {children}
    </kbd>
  );
}

/** A status dot with a word for screen readers. */
export function Dot({ tone, label, pulse, className }: { tone: Tone; label?: string; pulse?: boolean; className?: string }) {
  const colour: Record<Tone, string> = {
    neutral: "bg-faint",
    accent: "bg-accent",
    ok: "bg-ok",
    warn: "bg-warn",
    danger: "bg-danger",
    info: "bg-info",
  };
  return (
    <span className={cn("relative inline-flex size-2 shrink-0", className)} role={label ? "img" : undefined} aria-label={label}>
      {pulse ? (
        <span className={cn("absolute inset-0 animate-ping rounded-full opacity-60 motion-reduce:hidden", colour[tone])} />
      ) : null}
      <span className={cn("relative size-2 rounded-full", colour[tone])} />
    </span>
  );
}
