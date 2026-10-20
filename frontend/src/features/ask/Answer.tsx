import { ArrowRight, Bot, FileText, ShieldAlert, Wrench } from "lucide-react";
import { Badge, Table, TBody, TD, TH, THead, TR } from "@/ui";
import { cardFocus, type AskAnswer } from "./types";

/** Links out of an answer: the gene it is about, and the Decision Card a change request names. */
export interface AnswerLinks {
  gene?: (gene: string) => string;
  results?: string;
  /** Called with the card's focus target (`card:<id>`) when the card link is followed. */
  onOpenCard?: (focus: string) => void;
  /** Called when any other link out of the answer is followed. */
  onFollow?: () => void;
}

/** A number or a short word ("2.6×", "91%", "Moderate") sits in the number column; text wraps. */
const isShortValue = (v: string) => v.length <= 16 && !/\s\w+\s/.test(v);

/** First letter up, except for names that start lower-case (qPilot). */
const capitalise = (s: string) =>
  s && !s.startsWith("qPilot") ? s[0]!.toUpperCase() + s.slice(1) : s;

/**
 * One answer: the words, which tool answered and who picked it, who wrote the words, the
 * Decision Card a change request names, and the facts it cites. Every number shown here comes
 * from the answer or its facts; every label about how it was made is the server's own words.
 */
export function Answer({ answer, links }: { answer: AskAnswer; links: AnswerLinks }) {
  const gene = typeof answer.args?.gene === "string" ? answer.args.gene : null;
  const card = cardFocus(answer);
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm leading-relaxed whitespace-pre-wrap text-fg">{answer.answer}</p>

      {card ? (
        <div className="flex flex-col gap-1.5 rounded-lg border border-line bg-surface-2 px-3 py-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="info">A choice for a person</Badge>
            {links.results ? (
              <a
                href={links.results}
                onClick={() => links.onOpenCard?.(card)}
                className="inline-flex items-center gap-1 text-[13px] font-medium text-accent underline-offset-4 hover:underline"
              >
                Open the card
                <ArrowRight className="size-3.5" aria-hidden />
              </a>
            ) : null}
          </div>
          <p className="text-[13px] text-muted">
            {answer.note ??
              "Ask never changes an analysis choice: a person decides it on its Decision Card."}
          </p>
        </div>
      ) : null}

      <dl className="grid grid-cols-[auto_1fr] items-baseline gap-x-3 gap-y-1.5 text-[13px]">
        <dt className="flex items-center gap-1.5 text-muted">
          <Wrench className="size-3.5" aria-hidden />
          Answered by
        </dt>
        <dd className="min-w-0 text-fg">
          {capitalise(answer.tool_words)}
          {answer.engine === "audit" ? (
            <span className="text-muted"> (the robustness audit)</span>
          ) : null}
          <span className="block text-xs text-muted">Picked by {answer.routed_words}</span>
        </dd>
        <dt className="flex items-center gap-1.5 text-muted">
          {answer.written_by === "model" ? (
            <Bot className="size-3.5" aria-hidden />
          ) : (
            <FileText className="size-3.5" aria-hidden />
          )}
          Words by
        </dt>
        <dd className="min-w-0 break-words text-fg">
          {answer.written_by === "model" ? (
            <>
              <span className="font-mono text-[12px]">{answer.model ?? answer.writer_words}</span>
              <span className="block text-xs text-muted">
                A model; qPilot checked every number against the facts.
              </span>
            </>
          ) : (
            capitalise(answer.writer_words)
          )}
        </dd>
      </dl>

      {answer.note && !card ? <p className="text-xs text-muted">{answer.note}</p> : null}

      {!answer.validated ? (
        <p className="flex items-start gap-2 rounded-lg border border-warn/30 bg-warn-soft/60 px-3 py-2 text-[13px] text-fg">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
          Not every number in this answer could be traced to a fact. Check it against the study
          before you use it.
        </p>
      ) : null}

      {answer.facts.length ? (
        <div>
          <p className="pb-1.5 text-xs font-medium text-muted" aria-hidden>
            The numbers in this answer, from the study's facts
          </p>
          <div className="overflow-hidden rounded-lg border border-line">
            <Table caption="The numbers in this answer, from the study's facts">
              <THead>
                <TR>
                  <TH>Meaning</TH>
                  <TH numeric>Value</TH>
                </TR>
              </THead>
              <TBody>
                {answer.facts.map((f, i) => (
                  <TR key={f.id ?? `${f.meaning}-${i}`}>
                    <TD className="py-1.5">
                      <span title={f.id ?? undefined}>{f.meaning}</span>
                    </TD>
                    {isShortValue(f.value) ? (
                      <TD numeric>{f.value}</TD>
                    ) : (
                      <TD className="py-1.5 text-[13px]">{f.value}</TD>
                    )}
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
        </div>
      ) : (
        <p className="text-xs text-faint">This answer cites no numbers.</p>
      )}

      {gene && links.gene ? (
        <a
          href={links.gene(gene)}
          onClick={links.onFollow}
          className="inline-flex w-fit items-center gap-1 text-[13px] font-medium text-accent underline-offset-4 hover:underline"
        >
          Open {gene}
          <ArrowRight className="size-3.5" aria-hidden />
        </a>
      ) : null}
    </div>
  );
}
