import { cn } from "@/lib/cn";

/** qPilot's mark: an amplification curve in a rounded square (theme colours). */
export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-7 shrink-0", className)} aria-hidden>
      <rect width="32" height="32" rx="8" fill="var(--accent)" />
      <path
        d="M5 23c4 0 5-1 7-5s3-11 7-11 4 4 8 4"
        fill="none"
        stroke="var(--accent-fg)"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
      <circle cx="19" cy="7" r="2.2" fill="var(--accent-soft)" />
    </svg>
  );
}

/** The mark and the name. */
export function Brand({ compact }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2">
      <Mark />
      <span
        className={cn("text-[15px] font-semibold tracking-tight text-fg", compact && "sr-only")}
      >
        qPilot
      </span>
    </span>
  );
}
