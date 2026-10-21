/**
 * Incidents that need a person: the ones an agent proposed (**Confirm** / **Turn down**: only a
 * person decides), and confirmed ones still open (**Note what fixed it**). A confirmed incident
 * counts as "seen before" when a later run on this instrument shows the same wells and signal; a
 * turned-down one matches nothing.
 */
import { Check, Wrench, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { count } from "@/lib/format";
import { Button, Card, CardBody, CardHeader, Field, Input, Textarea } from "@/ui";
import { useDecideIncident, useFixIncident, type IncidentView } from "./api";
import { IncidentFacts } from "./Pieces";

const MAX_NOTE = 2000;

/** One proposed incident with the person's two choices. */
function ProposedIncident({
  instrumentId,
  incident,
}: {
  instrumentId: string;
  incident: IncidentView;
}) {
  const decide = useDecideIncident(instrumentId);
  const pending = decide.isPending ? decide.variables?.decision : null;
  return (
    <li className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-3">
      <IncidentFacts incident={incident} />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          size="sm"
          icon={<Check />}
          loading={pending === "confirm"}
          disabled={decide.isPending}
          aria-label={`Confirm the incident at entry ${count(incident.seq)}`}
          onClick={() => decide.mutate({ seq: incident.seq, decision: "confirm" })}
        >
          Confirm
        </Button>
        <Button
          size="sm"
          icon={<X />}
          loading={pending === "reject"}
          disabled={decide.isPending}
          aria-label={`Turn down the incident at entry ${count(incident.seq)}`}
          onClick={() => decide.mutate({ seq: incident.seq, decision: "reject" })}
        >
          Turn down
        </Button>
      </div>
    </li>
  );
}

/** Incidents an agent proposed, waiting for a person's decision. */
export function WaitingForYou({
  instrumentId,
  incidents,
}: {
  instrumentId: string;
  incidents: readonly IncidentView[];
}) {
  const proposed = incidents.filter((i) => i.can_confirm);
  if (!proposed.length) return null;
  return (
    <Card as="section" aria-labelledby="instr-waiting" className="border-warn/40">
      <CardHeader
        id="instr-waiting"
        title={`Waiting for you (${count(proposed.length)})`}
        hint={
          <>
            An agent proposed {proposed.length === 1 ? "this incident" : "these incidents"}; only a
            person decides. <strong className="font-medium text-fg">Confirm</strong>: it counts as
            &ldquo;seen before&rdquo; when a later run on this instrument shows the same wells and
            signal. <strong className="font-medium text-fg">Turn down</strong>: it matches nothing.
          </>
        }
      />
      <CardBody>
        <ul className="flex flex-col gap-3">
          {proposed.map((i) => (
            <ProposedIncident key={i.seq} instrumentId={instrumentId} incident={i} />
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}

/** A confirmed open incident with the "what fixed it" note (required). */
function OpenIncident({
  instrumentId,
  incident,
}: {
  instrumentId: string;
  incident: IncidentView;
}) {
  const fix = useFixIncident(instrumentId);
  const [note, setNote] = useState("");
  const [at, setAt] = useState("");
  const [tried, setTried] = useState(false);
  const error = tried && !note.trim() ? "Say what fixed it." : null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (!note.trim()) return;
    fix.mutate(
      { seq: incident.seq, note, at: at || null },
      {
        onSuccess: () => {
          setNote("");
          setAt("");
          setTried(false);
        },
      },
    );
  };
  return (
    <li className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-3">
      <IncidentFacts incident={incident} />
      <form
        onSubmit={submit}
        noValidate
        className="flex flex-col gap-3"
        aria-label={`What fixed the incident at entry ${count(incident.seq)}`}
      >
        <Field label="What fixed it" error={error}>
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={MAX_NOTE}
            showCount
            rows={2}
            required
          />
        </Field>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="When it was fixed" optional>
            <Input
              type="date"
              value={at}
              onChange={(e) => setAt(e.target.value)}
              className="w-44"
            />
          </Field>
          <Button type="submit" icon={<Wrench />} loading={fix.isPending}>
            Note what fixed it
          </Button>
        </div>
      </form>
    </li>
  );
}

/** Confirmed incidents with no fix on record yet. */
export function OpenIncidents({
  instrumentId,
  incidents,
}: {
  instrumentId: string;
  incidents: readonly IncidentView[];
}) {
  const open = incidents.filter((i) => i.can_fix);
  if (!open.length) return null;
  return (
    <Card as="section" aria-labelledby="instr-open">
      <CardHeader
        id="instr-open"
        title={`Open incidents (${count(open.length)})`}
        hint="Confirmed and not fixed yet. When it is fixed, note what fixed it: the next time it is seen, that is what qPilot shows."
      />
      <CardBody>
        <ul className="flex flex-col gap-3">
          {open.map((i) => (
            <OpenIncident key={i.seq} instrumentId={instrumentId} incident={i} />
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}

/** Incidents that are settled: fixed, or turned down (read-only). */
export function SettledIncidents({ incidents }: { incidents: readonly IncidentView[] }) {
  const done = incidents.filter((i) => !i.can_confirm && !i.can_fix);
  if (!done.length) return null;
  return (
    <Card as="section" aria-labelledby="instr-settled">
      <CardHeader
        id="instr-settled"
        title={`Fixed or turned down (${count(done.length)})`}
        level={2}
      />
      <CardBody>
        <ul className="flex flex-col gap-3">
          {done.map((i) => (
            <li key={i.seq} className="rounded-lg border border-line p-3">
              <IncidentFacts incident={i} />
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
