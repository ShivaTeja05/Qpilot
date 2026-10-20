/**
 * Text whose numbers are facts: each cited value is drawn as a number (tabular, medium weight) and
 * says where it comes from on hover. Text only — nothing from the server is ever HTML.
 */
import { cn } from "@/lib/cn";
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
            className="tabular font-medium text-fg"
            title={f.path ? `From the result: ${f.path}` : undefined}
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

/** Who wrote the words: qPilot's template, or a model whose numbers were checked. */
export function FactSource({
  text,
  className,
}: {
  text: Fact | null | undefined;
  className?: string;
}) {
  if (!text) return null;
  return (
    <span className={cn("text-[12px] text-muted", className)}>
      {text.source === "model"
        ? "Worded by the model; every number in it is a checked fact."
        : "qPilot's own wording; every number is a fact from the result."}
    </span>
  );
}
