/**
 * The Evidence Ledger (`GET …/evidence`): what this study cannot tell you. The items the file
 * lacks (absent) or that could not be judged (unknown) come first, each with its status as a
 * glyph and a word; what the study does show is folded under "What it does show". Every number in
 * a sentence is one of the ledger's cited facts (FactText). A ledger that could not be built says
 * why, calmly; it never changes a conclusion or a confidence grade.
 */
import {
  ChevronRight,
  CircleCheck,
  CircleHelp,
  CircleMinus,
  CircleSlash,
  Info,
} from "lucide-react";
import type { ReactNode } from "react";
import { count } from "@/lib/format";
import { Badge, Card, CardBody, CardHeader, ErrorPanel, LoadingBlock, type Tone } from "@/ui";
import { useEvidence, type EvidenceItem, type EvidenceView, type FactText as Fact } from "./api";
import { FactText } from "./FactText";

/** Each status as a glyph and a tone; the word is the API's own (`status_word`). */
const STATUS: Record<EvidenceItem["status"], { icon: ReactNode; tone: Tone }> = {
  present: { icon: <CircleCheck aria-hidden />, tone: "ok" },
  absent: { icon: <CircleSlash aria-hidden />, tone: "warn" },
  unknown: { icon: <CircleHelp aria-hidden />, tone: "info" },
  not_applicable: { icon: <CircleMinus aria-hidden />, tone: "neutral" },
};

const SOURCE: Record<EvidenceView["source"], string> = {
  kept: "Kept with the study when it was analysed.",
  rebuilt: "Read again from the study's file for this page; nothing was saved.",
  none: "",
};

/**
 * The item's sentence without its leading "Title: status. " (the row shows both already). Only
 * that plain lead is cut; every cited number stays the segment the server sent.
 */
export function itemSentence(item: EvidenceItem): Fact {
  const line = item.line;
  const lead = `${item.title}: ${item.status_word}. `;
  const plain = line.plain.startsWith(lead) ? line.plain.slice(lead.length) : line.plain;
  if (!line.segments.length) return { ...line, plain };
  const first = line.segments[0]!;
  if (first.fact || !first.text.startsWith(lead)) return line;
  const rest = first.text.slice(lead.length);
  const segments = rest
    ? [{ ...first, text: rest }, ...line.segments.slice(1)]
    : line.segments.slice(1);
  return { ...line, plain, segments };
}

/** Cannot-tell items first (absent, unknown), then the ones the study does show. */
export function ledgerParts(view: EvidenceView): {
  cannot: EvidenceItem[];
  shows: EvidenceItem[];
} {
  const items = view.items ?? [];
  return { cannot: items.filter((i) => i.cannot_tell), shows: items.filter((i) => !i.cannot_tell) };
}

export function EvidenceStatus({ item }: { item: Pick<EvidenceItem, "status" | "status_word"> }) {
  const s = STATUS[item.status] ?? STATUS.unknown;
  return (
    <Badge tone={s.tone} icon={s.icon}>
      {item.status_word}
    </Badge>
  );
}

function ItemRow({ item }: { item: EvidenceItem }) {
  return (
    <li className="flex flex-col gap-1 py-2.5 first:pt-0 last:pb-0" data-item={item.id}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <EvidenceStatus item={item} />
        <span className="text-[13px] font-medium text-fg">{item.title}</span>
        {item.miqe.length ? (
          <span className="text-[12px] text-faint">MIQE 2.0 · {item.miqe.join(", ")}</span>
        ) : null}
      </div>
      <p className="text-[13px] leading-relaxed text-muted">
        <FactText text={itemSentence(item)} />
      </p>
    </li>
  );
}

export function Ledger({ view }: { view: EvidenceView }) {
  if (!view.available) {
    return (
      <div className="flex flex-col gap-2 text-[13px]">
        <p className="flex items-start gap-2 rounded-lg bg-sunken p-3 text-fg">
          <Info className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
          <span>{view.note}</span>
        </p>
        <p className="text-muted">{view.rule}</p>
      </div>
    );
  }
  const { cannot, shows } = ledgerParts(view);
  const ruleSaid = Boolean(view.summary?.plain.includes(view.rule));
  return (
    <div className="flex flex-col gap-4">
      {view.summary ? (
        <p className="text-[13px] leading-relaxed text-fg">
          <FactText text={view.summary} />
        </p>
      ) : null}
      {cannot.length ? (
        <ul aria-label="What this study cannot tell you" className="divide-y divide-line">
          {cannot.map((i) => (
            <ItemRow key={i.id} item={i} />
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted">
          Nothing on the ledger is absent or unknown for this study.
        </p>
      )}
      {shows.length ? (
        <details className="group rounded-lg border border-line px-3 py-2">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[13px] font-medium text-fg select-none [&::-webkit-details-marker]:hidden">
            <ChevronRight
              className="size-4 text-muted transition-transform duration-150 group-open:rotate-90 motion-reduce:transition-none"
              aria-hidden
            />
            What it does show
            <span className="tabular font-normal text-muted">({count(shows.length)})</span>
          </summary>
          <ul aria-label="What it does show" className="mt-2 divide-y divide-line">
            {shows.map((i) => (
              <ItemRow key={i.id} item={i} />
            ))}
          </ul>
        </details>
      ) : null}
      <p className="text-[12px] text-muted">
        {ruleSaid ? null : <>{view.rule} </>}
        {SOURCE[view.source]} Method: <span className="font-mono">{view.method_card}</span>
      </p>
    </div>
  );
}

export function EvidencePanel({
  workspaceKey,
  studyId,
}: {
  workspaceKey: string;
  studyId: string;
}) {
  const q = useEvidence(workspaceKey, studyId);
  return (
    <Card as="section" aria-labelledby="evidence-title">
      <CardHeader
        id="evidence-title"
        title="What this study cannot tell you"
        hint="What the file holds, lacks or could not be judged on (the Evidence Ledger), and what that means for the conclusions."
      />
      <CardBody>
        {q.error ? (
          <ErrorPanel
            compact
            error={q.error}
            title="The Evidence Ledger could not be read"
            onRetry={() => void q.refetch()}
          />
        ) : !q.data ? (
          <LoadingBlock label="Reading the Evidence Ledger" lines={4} />
        ) : (
          <Ledger view={q.data} />
        )}
      </CardBody>
    </Card>
  );
}
