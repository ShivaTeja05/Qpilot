/**
 * The logbook in chain order: each entry's kind in words, where it came from (the file, two files,
 * typed), who wrote it (icon + word), when, its details and note as text, and its short hash; then
 * whether the chain verifies and the chain's head.
 */
import { BookOpen } from "lucide-react";
import { count, dateTime } from "@/lib/format";
import {
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Hash,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/ui";
import type { EventView, InstrumentView } from "./api";
import { ActorTag, ChainBadge, ChainProblems, SourceTag, TypedNote } from "./Pieces";
import { day, eventDetails } from "./words";

function When({ event }: { event: EventView }) {
  return (
    <div className="flex flex-col">
      <span className="whitespace-nowrap text-fg">{event.at ? day(event.at) : "—"}</span>
      <span className="text-xs whitespace-nowrap text-muted" title="When qPilot wrote it">
        logged {dateTime(event.recorded_at)}
      </span>
    </div>
  );
}

export function Logbook({ view }: { view: InstrumentView }) {
  const { instrument, events } = view;
  return (
    <Card as="section" aria-labelledby="instr-logbook">
      <CardHeader
        id="instr-logbook"
        title="Logbook"
        hint="Every entry in the order it was written. Each one is chained to the one before by its hash, so a line changed outside qPilot shows."
        actions={<ChainBadge ok={instrument.chain_ok} />}
      />
      <CardBody className="flex flex-col gap-3">
        <ChainProblems problems={instrument.problems} />
        {events.length ? (
          <div className="overflow-x-auto rounded-lg border border-line">
            <Table caption={`Logbook of ${instrument.display_name}, in chain order`}>
              <THead>
                <TR>
                  <TH numeric>Entry</TH>
                  <TH>What</TH>
                  <TH>When</TH>
                  <TH>Source</TH>
                  <TH>Who</TH>
                  <TH>Hash</TH>
                </TR>
              </THead>
              <TBody>
                {events.map((e) => {
                  const details = eventDetails(e);
                  return (
                    <TR key={e.seq} className="align-top">
                      <TD numeric className="py-2 align-top">
                        {count(e.seq)}
                      </TD>
                      <TD className="min-w-56 py-2 align-top">
                        <div className="font-medium text-fg">{e.kind_word}</div>
                        {details.length ? (
                          <div className="text-[13px] text-muted">{details.join(" · ")}</div>
                        ) : null}
                        <TypedNote text={e.note} className="mt-1" />
                      </TD>
                      <TD className="py-2 align-top">
                        <When event={e} />
                      </TD>
                      <TD className="py-2 align-top whitespace-nowrap">
                        <SourceTag source={e.source} />
                      </TD>
                      <TD className="py-2 align-top">
                        <ActorTag actor={e.actor} className="whitespace-nowrap" />
                      </TD>
                      <TD className="py-2 align-top">
                        <Hash value={e.hash} />
                      </TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
          </div>
        ) : instrument.chain_ok ? (
          <EmptyState icon={<BookOpen />} title="Nothing logged yet" compact headingLevel={3}>
            Log an event above, or link one of its run files: what the file states (a pause, an
            aborted run) is logged by itself.
          </EmptyState>
        ) : null}
        {instrument.chain_ok ? (
          <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted">
            <span>Chain head</span>
            <Hash value={view.head} length={12} prefix="head" />
          </p>
        ) : null}
      </CardBody>
    </Card>
  );
}
