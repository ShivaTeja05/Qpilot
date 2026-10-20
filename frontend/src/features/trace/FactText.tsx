/**
 * A trace sentence whose numbers and names are facts: each cited value is drawn as a number
 * (tabular, medium weight) and says where it comes from on hover. Text only.
 */
import type { FactText as Fact } from "./api";

export function FactText({
  text,
  className,
}: {
  text: Fact | null | undefined;
  className?: string;
}) {
  if (!text) return null;
  const facts = new Map(text.facts.map((f) => [f.id, f]));
  if (!text.segments.length) return <span className={className}>{text.plain}</span>;
  return (
    <span className={className}>
      {text.segments.map((s, i) => {
        const f = s.fact ? facts.get(s.fact) : undefined;
        if (!f) return <span key={i}>{s.text}</span>;
        const numeric = typeof f.value === "number";
        return (
          <span
            key={i}
            className={numeric ? "tabular font-medium text-fg" : "font-medium text-fg"}
            title={f.path ? `From the trace: ${f.path}` : undefined}
          >
            {s.text}
          </span>
        );
      })}
    </span>
  );
}
