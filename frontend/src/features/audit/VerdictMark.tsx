/**
 * A verdict as glyph + word, drawn with the charts' marks so the tags, the verdict strip and the
 * map on one screen agree (the kit's `VerdictTag` draws two verdicts with other shapes; see the
 * bus, #0130). Swap back to `VerdictTag` once the kit's shapes match.
 */
import { Glyph, VERDICTS, isVerdict } from "@/charts";
import { cn } from "@/lib/cn";

export function VerdictMark({
  verdict,
  label,
  compact,
  className,
}: {
  verdict: string;
  /** The audit's own word for it (default: the charts'). */
  label?: string;
  /** Glyph only (the word stays for screen readers). */
  compact?: boolean;
  className?: string;
}) {
  if (!isVerdict(verdict))
    return <span className={cn("text-[13px] text-muted", className)}>{label ?? verdict}</span>;
  const mark = VERDICTS[verdict];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap text-[13px] font-medium",
        className,
      )}
    >
      <Glyph mark={mark} size={12} />
      <span className={cn(compact && "sr-only", "text-fg")}>{label ?? mark.label}</span>
    </span>
  );
}
