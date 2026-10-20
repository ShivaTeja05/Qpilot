/**
 * One claim, opened: the sentence it was read from, how it was read, the verdict and the checks
 * behind it (every number a cited fact), the choices under which it would hold or stop holding,
 * and a sentence the record supports (copy it, or put it in place of yours).
 */
import { ArrowLeft, ArrowRight, ArrowUpRight, Replace } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "wouter";
import { Badge, Button, Card, ConclusionTag, CopyButton, IconButton, Kbd, Tooltip } from "@/ui";
import { cn } from "@/lib/cn";
import { fold } from "@/lib/format";
import type { ClaimChoice, ClaimView } from "./api";
import { CHECK_TITLE, CLAIM_VERDICT, ROLE_WORD } from "./marks";
import { ClaimVerdict, FactSentence, StatusSign } from "./parts";

/** The sentence a claim came from, with its words underlined. */
function Quoted({ text, claim }: { text: string; claim: ClaimView }) {
  const { start, end } = claim.sentence;
  const tone = CLAIM_VERDICT[claim.verdict].tone;
  const spans = claim.spans
    .filter((s) => s.start >= start && s.end <= end)
    .sort((a, b) => a.start - b.start);
  const out: ReactNode[] = [];
  let at = start;
  for (const s of spans) {
    if (s.start < at) continue;
    if (s.start > at) out.push(text.slice(at, s.start));
    out.push(
      <span
        key={`${s.start}-${s.role}`}
        title={ROLE_WORD[s.role]}
        style={{
          textDecorationLine: "underline",
          textDecorationColor: tone,
          textDecorationThickness: s.role === "gene" ? "3px" : "2px",
          textUnderlineOffset: "4px",
        }}
        className={cn(s.role === "gene" && "font-medium")}
      >
        {text.slice(s.start, s.end)}
      </span>,
    );
    at = s.end;
  }
  if (at < end) out.push(text.slice(at, end));
  return (
    <blockquote className="rounded-lg border border-line bg-sunken px-3 py-2 text-[14px] leading-7 text-fg">
      {out}
    </blockquote>
  );
}

function ChoiceRow({ choice }: { choice: ClaimChoice }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-1.5">
      <span
        className={cn(
          "w-4 shrink-0 text-center font-semibold",
          choice.holds ? "text-ok" : "text-danger",
        )}
      >
        <span aria-hidden>{choice.holds ? "✓" : "✕"}</span>
        <span className="sr-only">{choice.holds ? "holds" : "does not hold"}</span>
      </span>
      <span className="min-w-0 flex-1">
        <FactSentence text={choice.label} className="text-fg" />
        <span className="block text-[12px] text-muted">{choice.title}</span>
      </span>
      {choice.call ? <ConclusionTag conclusion={choice.call} compact /> : null}
      {choice.fc != null ? (
        <span className="tabular w-16 text-right font-mono text-[13px] text-fg">
          {fold(choice.fc)}
        </span>
      ) : null}
    </li>
  );
}

export function ClaimCard({
  text,
  claim,
  position,
  total,
  example,
  links,
  canReplace,
  onReplace,
  onMove,
}: {
  text: string;
  claim: ClaimView;
  position: number;
  total: number;
  /** What the example sentence was written to show (when the text is the server's example). */
  example?: string | null;
  links: { gene?: string; choices?: string; audit?: string };
  canReplace: boolean;
  onReplace: () => void;
  onMove: (step: 1 | -1) => void;
}) {
  const reading = claim.reading;
  // the headline is one of the checks: do not say it twice
  const said = (c: ClaimView["checks"][number]) => c.text.plain === claim.headline.plain;
  const all = claim.checks.filter((c) => !["grid", "audit", "choices"].includes(c.check));
  const main = all.length === 1 && said(all[0]!) ? [] : all;
  const context = claim.checks.filter(
    (c) => ["grid", "audit", "choices"].includes(c.check) && !said(c),
  );
  const holding = claim.choices.some((c) => c.holds);
  return (
    <Card as="article" aria-labelledby={`claim-${claim.id}`} className="overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
        <div className="flex items-center gap-2">
          <ClaimVerdict verdict={claim.verdict} />
          <span className="text-[12px] text-muted">
            claim {position} of {total}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <Tooltip
            content={
              <span>
                Previous claim <Kbd>k</Kbd>
              </span>
            }
          >
            <IconButton
              label="Previous claim"
              size="sm"
              onClick={() => onMove(-1)}
              disabled={position <= 1}
            >
              <ArrowLeft />
            </IconButton>
          </Tooltip>
          <Tooltip
            content={
              <span>
                Next claim <Kbd>j</Kbd>
              </span>
            }
          >
            <IconButton
              label="Next claim"
              size="sm"
              onClick={() => onMove(1)}
              disabled={position >= total}
            >
              <ArrowRight />
            </IconButton>
          </Tooltip>
        </div>
      </div>
      <div className="space-y-4 px-4 py-4">
        <Quoted text={text} claim={claim} />
        <div>
          <h3 className="mb-1.5 text-[12px] font-medium tracking-wide text-muted uppercase">
            Read as
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {reading.words.map((w, i) => (
              <Badge key={i} className="h-auto py-0.5 whitespace-normal">
                {w}
              </Badge>
            ))}
            {reading.source === "model" ? (
              <Badge tone="info">proposed by the model, checked by the rules</Badge>
            ) : null}
          </div>
        </div>
        <p id={`claim-${claim.id}`} className="text-[15px] leading-relaxed text-fg">
          <FactSentence text={claim.headline} />
        </p>
        {example ? (
          <p className="rounded-lg bg-bg-subtle px-3 py-2 text-[13px] text-muted">
            <span className="font-medium text-fg">Example: </span>
            {example}
          </p>
        ) : null}
        {main.length ? (
          <section aria-label="What was checked">
            <h3 className="mb-1.5 text-[12px] font-medium tracking-wide text-muted uppercase">
              Checked against the study
            </h3>
            <ul className="divide-y divide-line">
              {main.map((c, i) => (
                <li key={i} className="flex gap-2 py-2 text-[13px] leading-relaxed text-muted">
                  <StatusSign status={c.status} />
                  <span>
                    <span className="font-medium text-fg">{CHECK_TITLE[c.check] ?? c.check}. </span>
                    <FactSentence text={c.text} />
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        {context.length ? (
          <section aria-label="Other analyses">
            <h3 className="mb-1.5 text-[12px] font-medium tracking-wide text-muted uppercase">
              Under other choices
            </h3>
            <ul className="space-y-1.5 text-[13px] leading-relaxed text-muted">
              {context.map((c, i) => (
                <li key={i}>
                  <span className="font-medium text-fg">{CHECK_TITLE[c.check] ?? c.check}. </span>
                  <FactSentence text={c.text} />
                </li>
              ))}
            </ul>
            {claim.choices.length ? (
              <ul
                aria-label={
                  holding ? "Single choices under which it holds" : "Single choices that change it"
                }
                className="mt-2 divide-y divide-line rounded-lg border border-line px-3"
              >
                {claim.choices.map((c) => (
                  <ChoiceRow key={`${c.dimension}-${c.option}`} choice={c} />
                ))}
              </ul>
            ) : null}
          </section>
        ) : null}
        {claim.suggestion ? (
          <section
            aria-label="A sentence the record supports"
            className="rounded-lg border border-accent/30 bg-accent-soft/40 px-3 py-3"
          >
            <h3 className="mb-1 text-[12px] font-medium tracking-wide text-accent-strong uppercase">
              A sentence the record supports
            </h3>
            <p className="text-[14px] leading-relaxed text-fg">
              <FactSentence text={claim.suggestion} />
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              <CopyButton text={claim.suggestion.plain} label="Copy the sentence" showLabel />
              {canReplace ? (
                <Button size="sm" variant="ghost" icon={<Replace />} onClick={onReplace}>
                  Put it in place of mine
                </Button>
              ) : null}
            </div>
          </section>
        ) : null}
        {links.gene || links.choices || links.audit ? (
          <nav
            aria-label="Open in the study"
            className="flex flex-wrap gap-x-4 gap-y-1 text-[13px]"
          >
            {links.gene ? <StudyLink href={links.gene}>See {claim.gene}</StudyLink> : null}
            {links.choices ? <StudyLink href={links.choices}>See the choices</StudyLink> : null}
            {links.audit ? <StudyLink href={links.audit}>See the audit</StudyLink> : null}
          </nav>
        ) : null}
      </div>
    </Card>
  );
}

function StudyLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1 font-medium text-accent-strong underline-offset-2 hover:underline focus-visible:underline"
    >
      {children}
      <ArrowUpRight className="size-3.5" aria-hidden />
    </Link>
  );
}
