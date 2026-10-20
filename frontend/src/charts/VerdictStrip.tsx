/**
 * The audit's verdicts at a glance: one proportional bar (a segment per verdict, 2 px gaps) and a
 * tile per verdict with its glyph, count, word and rule. Tiles filter (press again to clear).
 */
import { cn } from "@/lib/cn";
import { Glyph } from "./core/Glyph";
import { VERDICTS, VERDICT_ORDER, isVerdict, type VerdictKey } from "./core/encodings";
import { fmtCount } from "./core/format";

export interface VerdictCount {
  verdict: VerdictKey | string;
  count: number;
  /** The verdict's rule in words (from the audit). */
  rule?: string;
  /** The audit's own label, if it differs from ours. */
  label?: string;
}

export interface VerdictStripProps {
  counts: VerdictCount[];
  selected?: string | null;
  onSelect?: (verdict: string | null) => void;
  /** Show the rule under each tile (default true). */
  rules?: boolean;
  className?: string;
}

export function VerdictStrip({
  counts,
  selected,
  onSelect,
  rules = true,
  className,
}: VerdictStripProps) {
  const known = counts.filter((c) => isVerdict(c.verdict));
  const ordered = VERDICT_ORDER.map((v) => known.find((c) => c.verdict === v)).filter(
    (c): c is VerdictCount => Boolean(c),
  );
  const total = ordered.reduce((n, c) => n + c.count, 0);
  const summary = ordered
    .map((c) => `${c.count} ${(c.label ?? VERDICTS[c.verdict as VerdictKey].label).toLowerCase()}`)
    .join(", ");
  return (
    <div className={cn("min-w-0", className)}>
      <div
        className="flex h-3 w-full gap-[2px] overflow-hidden rounded-full"
        role="img"
        aria-label={`Verdicts for ${fmtCount(total)} genes: ${summary}.`}
      >
        {ordered
          .filter((c) => c.count > 0)
          .map((c) => (
            <div
              key={c.verdict}
              className="h-full first:rounded-l-full last:rounded-r-full"
              style={{
                flexGrow: c.count,
                flexBasis: 0,
                background: VERDICTS[c.verdict as VerdictKey].tone,
                opacity: selected && selected !== c.verdict ? 0.3 : 1,
                transition: "opacity 160ms ease-out",
              }}
            />
          ))}
      </div>
      <ul className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        {ordered.map((c) => {
          const v = VERDICTS[c.verdict as VerdictKey];
          const on = selected === c.verdict;
          const body = (
            <>
              <span className="flex items-center gap-2">
                <Glyph mark={v} size={16} />
                <span className="tabular text-xl font-semibold text-fg">{fmtCount(c.count)}</span>
              </span>
              <span className="mt-0.5 block text-[13px] font-medium text-fg">
                {c.label ?? v.label}
              </span>
              {rules && c.rule && (
                <span className="mt-1 block text-[12px] leading-snug text-muted">{c.rule}</span>
              )}
            </>
          );
          return (
            <li key={c.verdict} className="min-w-0">
              {onSelect ? (
                <button
                  type="button"
                  aria-pressed={on}
                  onClick={() => onSelect(on ? null : c.verdict)}
                  className={cn(
                    "h-full w-full rounded-xl border bg-surface p-3 text-left transition-colors duration-150 hover:border-line-strong",
                    on ? "border-accent ring-1 ring-accent" : "border-line",
                    selected && !on && "opacity-60",
                  )}
                >
                  {body}
                </button>
              ) : (
                <div className="h-full rounded-xl border border-line bg-surface p-3">{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
