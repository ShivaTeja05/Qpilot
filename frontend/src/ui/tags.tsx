/**
 * Meaning-carrying tags: a conclusion (arrow + word), a confidence level (bar count + word),
 * an audit verdict (glyph + word), an engine check. Colour reinforces; it never carries the
 * meaning alone (docs/app.md §5).
 */
import { cn } from "@/lib/cn";
import {
  CHECK,
  CONCLUSION,
  LEVEL,
  VERDICT,
  asConclusion,
  asLevel,
  asVerdict,
  type CheckStatus,
  type Conclusion,
  type Level,
  type Verdict,
  type VerdictShape,
} from "@/lib/vocab";

const CONCLUSION_TEXT: Record<Conclusion, string> = {
  up: "text-up",
  down: "text-down",
  none: "text-none",
};

/** ▲ up · ▼ down · — no call. `compact` shows only the arrow (with the word for screen readers). */
export function ConclusionTag({
  conclusion,
  compact,
  long,
  className,
}: {
  conclusion: Conclusion | string | null | undefined;
  compact?: boolean;
  long?: boolean;
  className?: string;
}) {
  const c = asConclusion(conclusion);
  const v = CONCLUSION[c];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap font-medium",
        CONCLUSION_TEXT[c],
        className,
      )}
    >
      <span aria-hidden className="text-[0.8em] leading-none">
        {v.glyph}
      </span>
      {compact ? <span className="sr-only">{v.word}</span> : <span>{long ? v.long : v.word}</span>}
    </span>
  );
}

const LEVEL_BG: Record<Level, string> = {
  High: "bg-l-high",
  Moderate: "bg-l-moderate",
  Low: "bg-l-low",
  "Very low": "bg-l-verylow",
};

/** The four bars of a level (4 High … 1 Very low). */
export function LevelBars({ level, className }: { level: Level; className?: string }) {
  const n = LEVEL[level].bars;
  return (
    <span aria-hidden className={cn("inline-flex h-3 items-end gap-[2px]", className)}>
      {[1, 2, 3, 4].map((i) => (
        <span
          key={i}
          className={cn("w-[3px] rounded-[1px]", i <= n ? LEVEL_BG[level] : "bg-line-strong")}
          style={{ height: `${4 + i * 2}px` }}
        />
      ))}
    </span>
  );
}

/** An ordinal confidence level (never a percentage): bars + word. */
export function LevelTag({
  level,
  className,
  hideWord,
}: {
  level: Level | string | null | undefined;
  className?: string;
  hideWord?: boolean;
}) {
  const l = asLevel(level);
  if (!l) return <span className={cn("text-muted", className)}>—</span>;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap text-[13px] font-medium",
        className,
      )}
    >
      <LevelBars level={l} />
      <span className={cn(hideWord && "sr-only", "text-fg")}>
        {l}
        <span className="sr-only"> confidence ({LEVEL[l].bars} of 4)</span>
      </span>
    </span>
  );
}

const VERDICT_TEXT: Record<Verdict, string> = {
  solid: "text-v-solid",
  "holds with caveats": "text-v-caveats",
  "depends on your choices": "text-v-depends",
  fragile: "text-v-fragile",
  "check data first": "text-v-check",
  "no call": "text-v-nocall",
};

/** The SVG glyph of a verdict shape (12 px box; uses currentColor). Charts may reuse it. */
export function ShapeGlyph({
  shape,
  size = 12,
  className,
}: {
  shape: VerdictShape;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 12 12"
      width={size}
      height={size}
      aria-hidden
      className={cn("shrink-0", className)}
    >
      {shape === "disc" && <circle cx="6" cy="6" r="5" fill="currentColor" />}
      {shape === "half" && (
        <>
          <circle cx="6" cy="6" r="4.4" fill="none" stroke="currentColor" strokeWidth="1.4" />
          <path d="M6 1.6a4.4 4.4 0 0 1 0 8.8z" fill="currentColor" />
        </>
      )}
      {shape === "diamond" && <path d="M6 0.8 11.2 6 6 11.2 0.8 6z" fill="currentColor" />}
      {shape === "cross" && (
        <path
          d="M2.2 2.2 9.8 9.8M9.8 2.2 2.2 9.8"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
        />
      )}
      {shape === "alert" && (
        <>
          <path d="M6 0.9 11.4 10.8H0.6z" fill="currentColor" />
          <path d="M6 4.4v3" stroke="var(--surface)" strokeWidth="1.4" strokeLinecap="round" />
          <circle cx="6" cy="9.1" r="0.8" fill="var(--surface)" />
        </>
      )}
      {shape === "ring" && (
        <circle cx="6" cy="6" r="4.4" fill="none" stroke="currentColor" strokeWidth="1.6" />
      )}
    </svg>
  );
}

/** An audit verdict: glyph + word. `compact` shows the glyph only (word for screen readers). */
export function VerdictTag({
  verdict,
  compact,
  className,
}: {
  verdict: Verdict | string | null | undefined;
  compact?: boolean;
  className?: string;
}) {
  const v = asVerdict(verdict);
  if (!v) return <span className={cn("text-muted", className)}>—</span>;
  const meta = VERDICT[v];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap text-[13px] font-medium",
        className,
      )}
    >
      <ShapeGlyph shape={meta.shape} className={VERDICT_TEXT[v]} />
      <span className={cn(compact && "sr-only", "text-fg")}>{meta.label}</span>
    </span>
  );
}

const CHECK_STYLE: Record<CheckStatus, string> = {
  consistent: "border-ok/25 bg-ok-soft text-ok",
  contradicted: "border-danger/30 bg-danger-soft text-danger",
  cannot_check: "border-line bg-bg-subtle text-muted",
};
const CHECK_GLYPH: Record<CheckStatus, string> = {
  consistent: "✓",
  contradicted: "✕",
  cannot_check: "?",
};

/** The engine's check of a proposal: consistent / contradicted / cannot check. */
export function CheckTag({ status, className }: { status: CheckStatus; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-md border px-1.5 text-xs font-medium",
        CHECK_STYLE[status],
        className,
      )}
    >
      <span aria-hidden>{CHECK_GLYPH[status]}</span>
      {CHECK[status].word}
    </span>
  );
}
