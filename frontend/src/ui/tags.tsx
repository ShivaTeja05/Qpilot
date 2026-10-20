/**
 * Meaning-carrying tags: a conclusion (arrow + word), a confidence level (bar count + word),
 * an audit verdict (glyph + word), an engine check. Colour reinforces; it never carries the
 * meaning alone (docs/app.md §5).
 */
import { cn } from "@/lib/cn";
import { Glyph } from "./Glyph";
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
          className={cn(
            "w-1 rounded-[1px]",
            i <= n ? LEVEL_BG[level] : "bg-line ring-1 ring-line-strong ring-inset",
          )}
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
      <Glyph mark={meta} />
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
