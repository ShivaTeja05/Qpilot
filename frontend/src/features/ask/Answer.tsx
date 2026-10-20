import { ArrowRight, Bot, FileText, ShieldAlert, Wrench } from "lucide-react";
import { Badge, Table, TBody, TD, TH, THead, TR } from "@/ui";
import type { AskView } from "./types";
import { authorWords, routerWords, STATUS_WORDS, toolWords } from "./words";

/** Links out of an answer: the gene it is about, and the card a request waits on. */
export interface AnswerLinks {
  gene?: (gene: string) => string;
  results?: string;
  /** Called with the card's focus target (`card:<id>`) when the card link is followed. */
  onOpenCard?: (focus: string) => void;
}

/** First letter up, except for names that start lower-case (qPilot). */
const capitalise = (s: string) =>
  s && !s.startsWith("qPilot") ? s[0]!.toUpperCase() + s.slice(1) : s;

/**
 * One answer: the words, which tool answered and who wrote the words, what happened to a change
 * request, and the facts it cites. Every number shown here comes from the answer or its facts.
 */
export function Answer({ answer, links }: { answer: AskView; links: AnswerLinks }) {
  const gene = typeof answer.args.gene === "string" ? answer.args.gene : null;
  const status = answer.status ? STATUS_WORDS[answer.status] : undefined;
  // The Decision Card the answer is about (a change request), as a focus target for Results.
  const focus = answer.focus?.startsWith("card:")
    ? answer.focus
    : answer.cardId
      ? `card:${answer.cardId}`
      : null;
  const router = routerWords(answer);
  return (
    <div className="flex flex-col gap-3">
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg">{answer.answer}</p>

      {status || focus ? (
        <div className="flex flex-col gap-1.5 rounded-lg border border-line bg-surface-2 px-3 py-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={status?.tone ?? "info"}>{status?.label ?? "A choice for a person"}</Badge>
            {focus && links.results && answer.status !== "applied" ? (
              <a
                href={links.results}
                onClick={() => links.onOpenCard?.(focus)}
                className="inline-flex items-center gap-1 text-[13px] font-medium text-accent underline-offset-4 hover:underline"
              >
                Open the card
                <ArrowRight className="size-3.5" aria-hidden />
              </a>
            ) : null}
          </div>
          <p className="text-[13px] text-muted">
            {answer.note ??
              (answer.status === "pending_human"
                ? "The request waits for you on the card, with a button to turn it down."
                : answer.status === "applied"
                  ? "Ask applied it as an agent; it is in the decision log, and Undo is on its card."
                  : "Ask does not change analysis choices: a person decides them on the Decision Card.")}
          </p>
        </div>
      ) : null}

      <dl className="grid grid-cols-[auto_1fr] items-baseline gap-x-3 gap-y-1.5 text-[13px]">
        <dt className="flex items-center gap-1.5 text-muted">
          <Wrench className="size-3.5" aria-hidden />
          Answered by
        </dt>
        <dd className="min-w-0 text-fg">
          {capitalise(toolWords(answer))}
          {answer.engine === "audit" ? (
            <span className="text-muted"> (the robustness audit)</span>
          ) : null}
          {router ? <span className="block text-xs text-muted">Picked by {router}</span> : null}
        </dd>
        <dt className="flex items-center gap-1.5 text-muted">
          {answer.writtenBy === "model" ? (
            <Bot className="size-3.5" aria-hidden />
          ) : (
            <FileText className="size-3.5" aria-hidden />
          )}
          Words by
        </dt>
        <dd className="min-w-0 break-words text-fg">
          {answer.writtenBy === "model" ? (
            <>
              <span className="font-mono text-[12px]">{authorWords(answer)}</span>
              <span className="block text-xs text-muted">
                A model; qPilot checked every number against the facts.
              </span>
            </>
          ) : (
            capitalise(authorWords(answer))
          )}
        </dd>
      </dl>

      {answer.note && !status && !focus ? (
        <p className="text-xs text-muted">{answer.note}</p>
      ) : null}

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
                    <TD>
                      <span title={f.id ?? undefined}>{f.meaning}</span>
                    </TD>
                    <TD numeric>
                      <span className="font-mono tabular">{f.value}</span>
                    </TD>
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
          className="inline-flex w-fit items-center gap-1 text-[13px] font-medium text-accent underline-offset-4 hover:underline"
        >
          Open {gene}
          <ArrowRight className="size-3.5" aria-hidden />
        </a>
      ) : null}
    </div>
  );
}
