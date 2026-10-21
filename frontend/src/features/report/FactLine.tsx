/**
 * A sentence whose numbers and names are facts (`FactText`, the Run Review's lines): each cited
 * value is drawn in medium weight (numbers tabular) and says where it comes from on hover. Text
 * only: a reviewer's comment or a name from a file is never markup.
 */
import { cn } from "@/lib/cn";
import type { FactText } from "./api";

type Segment = FactText["segments"][number];

/**
 * The segments after a leading phrase the page already shows (an Evidence Ledger item's
 * "Title: status. "), when that phrase is plain text at the start of the sentence; otherwise the
 * whole sentence, so nothing is ever lost.
 */
export function afterLead(text: FactText, lead: string): Segment[] {
  const joined = text.segments.map((s) => s.text).join("");
  if (!lead || joined !== text.plain || !joined.startsWith(lead)) return text.segments;
  let left = lead.length;
  const out: Segment[] = [];
  for (const s of text.segments) {
    // A phrase that runs into a fact is not one the page shows elsewhere: keep the whole line.
    if (left <= 0) out.push(s);
    else if (s.fact) return text.segments;
    else if (s.text.length <= left) left -= s.text.length;
    else {
      out.push({ ...s, text: s.text.slice(left) });
      left = 0;
    }
  }
  return out;
}

export function FactLine({
  text,
  lead,
  className,
}: {
  text: FactText | null | undefined;
  /** A leading phrase shown elsewhere (left out when the sentence starts with it). */
  lead?: string;
  className?: string;
}) {
  if (!text) return null;
  const facts = new Map(text.facts.map((f) => [f.id, f]));
  if (!text.segments.length) {
    const plain = lead && text.plain.startsWith(lead) ? text.plain.slice(lead.length) : text.plain;
    return <span className={cn("[overflow-wrap:anywhere]", className)}>{plain}</span>;
  }
  const segments = lead ? afterLead(text, lead) : text.segments;
  return (
    <span className={cn("[overflow-wrap:anywhere]", className)}>
      {segments.map((s, i) => {
        const f = s.fact ? facts.get(s.fact) : undefined;
        if (!f) return <span key={i}>{s.text}</span>;
        return (
          <span
            key={i}
            className={cn("font-medium text-fg", typeof f.value === "number" && "tabular")}
            title={f.path ? `${f.id}, from ${f.path}` : f.id}
            data-fact={f.id}
          >
            {s.text}
          </span>
        );
      })}
    </span>
  );
}
