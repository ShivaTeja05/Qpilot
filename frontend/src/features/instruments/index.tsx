/**
 * Instruments (`#/instruments`, `#/instruments/<id>`): each instrument's logbook, incidents to
 * confirm, and which conclusions used a period. A lab's working memory, not a regulated record:
 * what the run files say, what people logged, and the incidents a person confirmed.
 *
 * The list shows every registered instrument (latest calibrations and their age, open incidents
 * and how many an agent proposed, whether its logbook chain verifies), **Register an
 * instrument**, **Read a run file** and the **Lookback**. One instrument shows what waits for a
 * person (Confirm / Turn down), open incidents (Note what fixed it), Log an event, Log an incident
 * you saw, and the logbook in chain order. Every write is the person's (the server records it).
 */
import { ArrowLeft, Gauge, Info, MapPin } from "lucide-react";
import type { SectionProps } from "@/shell/sections";
import { plural } from "@/lib/format";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorPanel,
  KeyValues,
  LoadingBlock,
  PageHeader,
} from "@/ui";
import {
  useInstrument,
  useInstruments,
  useInstrumentsLive,
  type InstrumentSummary,
  type InstrumentsView,
} from "./api";
import { OpenIncidents, SettledIncidents, WaitingForYou } from "./Incidents";
import { LogEvent, LogIncident } from "./LogForms";
import { Logbook } from "./Logbook";
import { LookbackCard } from "./Lookback";
import { Calibrations, ChainBadge, ChainProblems, OpenCount } from "./Pieces";
import { RegisterButton } from "./Register";
import { RunFileCard } from "./RunFile";

const PURPOSE =
  "Each instrument's logbook, incidents to confirm, and which conclusions used a period.";

function href(id: string): string {
  return `#/instruments/${encodeURIComponent(id)}`;
}

/** What the registry is, and what it is not (the server's own words). */
function RegistryNote({ note }: { note: string | undefined }) {
  if (!note) return null;
  return (
    <p className="flex gap-2 text-[13px] text-muted">
      <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{note}</span>
    </p>
  );
}

function SharedWord({ shared }: { shared: boolean }) {
  return shared ? <Badge tone="info">Shared</Badge> : null;
}

function placeLine(i: InstrumentSummary): string {
  return [i.make_model, i.location].filter(Boolean).join(" · ");
}

/** One instrument in the list. */
function InstrumentItem({ instrument: i }: { instrument: InstrumentSummary }) {
  return (
    <Card as="li" className="flex flex-col">
      <CardHeader
        level={3}
        title={
          <a
            href={href(i.instrument_id)}
            className="text-fg underline-offset-2 hover:text-accent-strong hover:underline"
          >
            {i.display_name}
          </a>
        }
        hint={
          <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
            {placeLine(i) ? (
              <span className="inline-flex items-center gap-1">
                <MapPin className="size-3.5" aria-hidden />
                {placeLine(i)}
              </span>
            ) : null}
            <SharedWord shared={i.shared} />
          </span>
        }
        actions={<ChainBadge ok={i.chain_ok} />}
      />
      <CardBody className="flex flex-1 flex-col gap-3">
        <ChainProblems problems={i.problems} />
        <KeyValues
          rows={[
            ["Latest calibrations", <Calibrations key="c" items={i.calibrations} />],
            ["Incidents", <OpenCount key="o" summary={i} />],
            ["Logbook", plural(i.n_events, "entry", "entries")],
          ]}
        />
        <div className="mt-auto">
          <a
            href={href(i.instrument_id)}
            className="text-[13px] font-medium text-accent-strong underline-offset-2 hover:underline"
          >
            Open the logbook{i.n_proposed ? " and decide" : ""}
            <span className="sr-only"> of {i.display_name}</span>
          </a>
        </div>
      </CardBody>
    </Card>
  );
}

function InstrumentList({ view }: { view: InstrumentsView }) {
  if (!view.instruments.length)
    return (
      <EmptyState icon={<Gauge />} title="No instrument registered yet" action={<RegisterButton />}>
        Register the qPCR instruments your lab uses. Each one gets a logbook: what its run files say
        (calibrations, pauses, an aborted run), what people log (a service visit, a part changed),
        and incidents a person confirmed, so the next time a well looks odd you can see whether it
        was seen before and what fixed it, and which conclusions used a bad period.
      </EmptyState>
    );
  return (
    <ul className="grid gap-4 lg:grid-cols-2" aria-label="Registered instruments">
      {view.instruments.map((i) => (
        <InstrumentItem key={i.instrument_id} instrument={i} />
      ))}
    </ul>
  );
}

function ListPage() {
  const list = useInstruments();
  const view = list.data;
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 pb-6">
      <PageHeader
        title="Instruments"
        hint={PURPOSE}
        actions={view?.instruments.length ? <RegisterButton /> : null}
      />
      <RegistryNote note={view?.note} />
      {list.error && !view ? (
        <ErrorPanel
          error={list.error}
          title="The instrument registry could not be read"
          onRetry={() => void list.refetch()}
        />
      ) : !view ? (
        <Card className="p-4">
          <LoadingBlock label="Reading the instrument registry" lines={4} />
        </Card>
      ) : (
        <InstrumentList view={view} />
      )}
      {view ? (
        <div className="grid items-start gap-4 xl:grid-cols-2">
          <RunFileCard instruments={view.instruments} />
          <LookbackCard instruments={view.instruments} />
        </div>
      ) : null}
    </div>
  );
}

function InstrumentPage({ id }: { id: string }) {
  const one = useInstrument(id);
  const list = useInstruments();
  const view = one.data;
  const summary = view?.instrument ?? list.data?.instruments.find((i) => i.instrument_id === id);
  const kinds = list.data?.kinds ?? [];
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 pb-6">
      <div>
        <a
          href="#/instruments"
          className="inline-flex items-center gap-1 text-[13px] text-muted underline-offset-2 hover:text-fg hover:underline"
        >
          <ArrowLeft className="size-3.5" aria-hidden />
          All instruments
        </a>
      </div>
      <PageHeader
        eyebrow="Instrument"
        title={summary?.display_name ?? id}
        hint={
          summary ? (
            <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
              {placeLine(summary) || "No model or place given"}
              <SharedWord shared={summary.shared} />
            </span>
          ) : undefined
        }
        actions={summary ? <ChainBadge ok={summary.chain_ok} /> : null}
      />
      <RegistryNote note={list.data?.note} />
      {one.error && !view ? (
        <ErrorPanel
          error={one.error}
          title="This instrument's logbook could not be read"
          onRetry={() => void one.refetch()}
        >
          {summary && !summary.chain_ok ? <ChainProblems problems={summary.problems} /> : null}
        </ErrorPanel>
      ) : !view ? (
        <Card className="p-4">
          <LoadingBlock label="Reading the logbook" lines={5} />
        </Card>
      ) : (
        <>
          <Card as="section" aria-labelledby="instr-now">
            <CardHeader id="instr-now" title="Now" />
            <CardBody>
              <KeyValues
                rows={[
                  [
                    "Latest calibrations",
                    <Calibrations key="c" items={view.instrument.calibrations} />,
                  ],
                  ["Incidents", <OpenCount key="o" summary={view.instrument} />],
                  ["Logbook", plural(view.instrument.n_events, "entry", "entries")],
                ]}
              />
            </CardBody>
          </Card>
          <WaitingForYou instrumentId={id} incidents={view.incidents} />
          <OpenIncidents instrumentId={id} incidents={view.incidents} />
          {view.instrument.chain_ok ? (
            <div className="grid items-start gap-4 xl:grid-cols-2">
              <LogEvent instrumentId={id} kinds={kinds} />
              <LogIncident instrumentId={id} />
            </div>
          ) : null}
          <Logbook view={view} />
          <SettledIncidents incidents={view.incidents} />
          <LookbackCard instruments={list.data?.instruments ?? []} instrumentId={id} />
        </>
      )}
    </div>
  );
}

export default function Section({ rest }: SectionProps) {
  useInstrumentsLive();
  const id = rest[0];
  return id ? <InstrumentPage key={id} id={id} /> : <ListPage />;
}
