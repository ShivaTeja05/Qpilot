import { ArrowRight, Bot, FileText, ShieldAlert, Wrench } from "lucide-react";
import { Badge, Table, TBody, TD, TH, THead, TR } from "@/ui";
import type { AskView } from "./types";
import { authorWords, routerWords, STATUS_WORDS, toolWords } from "./words";

/** Links out of an answer: the gene it is about, and the card a request waits on. */
export interface AnswerLinks {
  gene?: (gene: string) => string;
  results?: string;
}

/**
 * One answer: the words, which tool answered and who wrote the words, what happened to a change
 * request, and the facts it cites. Every number shown here comes from the answer or its facts.
 */
export function Answer({ answer, links }: { answer: AskView; links: AnswerLinks }) {
  const gene = typeof answer.args.gene === "string" ? answer.args.gene : null;
  const status = answer.status ? STATUS_WORDS[answer.status] : undefined;
  const router = routerWords(answer);
  return (
    <div className="flex flex-col gap-3">
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg">{answer.answer}</p>

      {status ? (
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={status.tone}>{status.label}</Badge>
          {answer.status === "pending_human" && links.results ? (
            <a
              href={links.results}
              className="text-[13px] font-medium text-accent underline-offset-4 hover:underline"
            >
              Decide it on its card in Results
            </a>
          ) : null}
        </div>
      ) : null}

      <dl className="grid grid-cols-[auto_1fr] items-baseline gap-x-3 gap-y-1 text-[13px]">
        <dt className="flex items-center gap-1.5 text-muted">
          <Wrench className="size-3.5" aria-hidden />
          Answered by
        </dt>
        <dd className="min-w-0 text-fg">
          {toolWords(answer)}
          {answer.engine === "audit" ? (
            <span className="text-muted"> (the robustness audit)</span>
          ) : null}
          {router ? <span className="block text-xs text-faint">{router}</span> : null}
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
            <span className="font-mono text-[12px]">{authorWords(answer)}</span>
          ) : (
            authorWords(answer)
          )}
          {answer.writtenBy === "model" ? (
            <span className="text-muted"> (numbers checked against the facts)</span>
          ) : null}
        </dd>
      </dl>

      {answer.note ? (
        <p className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-[13px] text-muted">
          {answer.writtenBy === "template" ? "The model was not used for these words: " : "Note: "}
          {answer.note}
        </p>
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
                {answer.facts.map((f) => (
                  <TR key={f.id}>
                    <TD>
                      <span title={f.id}>{f.meaning}</span>
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
