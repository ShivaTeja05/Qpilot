/**
 * Small pieces of the Claims section: a sentence whose numbers are cited facts, a claim's verdict
 * as a mark and a word, and a check's outcome sign.
 */
import { Glyph } from "@/ui";
import { cn } from "@/lib/cn";
import type { CheckStatus, ClaimFact, ClaimText, Verdict } from "./api";
import { CLAIM_VERDICT, STATUS_WORD } from "./marks";

const ORIGIN: Record<ClaimFact["origin"], string> = {
  result: "From the study's result",
  grid: "Computed from qPilot's choice grid",
  audit: "From the robustness audit",
  text: "Quoted from your text",
};

/** Where a cited value comes from, in words (shown on hover). */
export function factSource(fact: ClaimFact): string {
  return fact.path ? `${ORIGIN[fact.origin]}: ${fact.path}` : ORIGIN[fact.origin];
}

/**
 * A sentence from the server: plain text with each cited value set apart (tabular figures; a
 * value quoted from the person's own text comes in quotation marks). Text only, never HTML.
 */
export function FactSentence({
  text,
  className,
}: {
  text: ClaimText | null | undefined;
  className?: string;
}) {
  if (!text) return null;
  const facts = new Map(text.facts.map((f) => [f.id, f]));
  return (
    <span className={className}>
      {text.segments.map((s, i) => {
        const f = s.fact ? facts.get(s.fact) : undefined;
        if (!f) return <span key={i}>{s.text}</span>;
        if (f.origin === "text") {
          // the server sets a quoted value in quotation marks; it is the person's own words
          return (
            <span key={i} title={factSource(f)} className="font-medium text-fg">
              {s.text}
            </span>
          );
        }
        return (
          <span
            key={i}
            title={factSource(f)}
            className={cn(
              "tabular font-medium text-fg",
              f.origin !== "result" &&
                "decoration-line-strong underline decoration-dotted underline-offset-2",
            )}
          >
            {s.text}
          </span>
        );
      })}
    </span>
  );
}

/** A claim's verdict: its mark and its word (the word carries the meaning). */
export function ClaimVerdict({
  verdict,
  short,
  className,
}: {
  verdict: Verdict;
  short?: boolean;
  className?: string;
}) {
  const meta = CLAIM_VERDICT[verdict];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap text-[13px] font-medium text-fg",
        className,
      )}
    >
      <Glyph mark={meta} />
      {short ? meta.short : meta.label}
    </span>
  );
}

/** A check's outcome: a sign (decoration) and its words for screen readers. */
export function StatusSign({ status }: { status: CheckStatus }) {
  const s = STATUS_WORD[status];
  return (
    <span className={cn("inline-flex w-4 shrink-0 justify-center font-semibold", s.tone)}>
      <span aria-hidden>{s.sign}</span>
      <span className="sr-only">{s.word}</span>
    </span>
  );
}
