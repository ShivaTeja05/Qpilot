/**
 * Text whose numbers are facts (`ReportText`): each cited number is drawn as a number and says
 * where it comes from on hover and to screen readers; quoted strings from the study (names, a
 * person's reasons) and citation markers are text. Nothing from the server is ever HTML.
 */
import { cn } from "@/lib/cn";
import type { Facts, ReportText } from "./api";

type Segment = ReportText["segments"][number];

/** Segments with adjacent citation markers merged into one ``[2, 3]``. */
export function citeGroups(text: ReportText): { seg: Segment; cites: number[] | null }[] {
  const out: { seg: Segment; cites: number[] | null }[] = [];
  for (const seg of text.segments) {
    const last = out[out.length - 1];
    if (seg.cite != null && last?.cites) last.cites.push(seg.cite);
    else out.push({ seg, cites: seg.cite != null ? [seg.cite] : null });
  }
  return out;
}

/** A fact's provenance in words, for its hover text. */
export function whereFrom(fact: Facts[string] | undefined, id: string): string {
  if (!fact) return id;
  return fact.derived ? `${id}, read from ${fact.path}` : `${id}, the engine's fact (${fact.path})`;
}

export function Cited({
  text,
  facts,
  cites = false,
  className,
}: {
  text: ReportText | null | undefined;
  facts: Facts;
  /** Show the citation markers (the Methods). */
  cites?: boolean;
  className?: string;
}) {
  if (!text) return null;
  return (
    <span className={cn("[overflow-wrap:anywhere]", className)}>
      {citeGroups(text).map(({ seg, cites: group }, i) => {
        if (group) {
          return cites ? (
            <sup key={i} className="ml-0.5 text-[10.5px] font-medium text-accent-strong">
              [{group.join(", ")}]
            </sup>
          ) : null;
        }
        if (seg.fact) {
          const fact = facts[seg.fact];
          return (
            <span
              key={i}
              className="tabular font-medium text-fg underline decoration-faint decoration-dotted underline-offset-[3px]"
              title={whereFrom(fact, seg.fact)}
              data-fact={seg.fact}
            >
              {seg.text}
            </span>
          );
        }
        return (
          <span key={i} className={cn(seg.quote && "text-fg")}>
            {seg.text}
          </span>
        );
      })}
    </span>
  );
}
