/**
 * Words whose numbers are facts: each cited value is drawn as a number (tabular, medium weight),
 * carries its fact id, and says where in the check it comes from on hover. Text only — nothing
 * from the server is ever HTML; nothing here re-types a number.
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
        return f ? (
          <span
            key={i}
            data-fact={f.id}
            className="tabular font-medium text-fg"
            title={f.path ? `From the check: ${f.path}` : undefined}
          >
            {s.text}
          </span>
        ) : (
          <span key={i}>{s.text}</span>
        );
      })}
    </span>
  );
}
