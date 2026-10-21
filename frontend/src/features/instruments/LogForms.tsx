/**
 * What a person logs on an instrument: an event (a calibration, a part change, a service visit,
 * a move or a note) and an incident they saw (wells, what was off and which way, a note). Both
 * are written as the person's own (`actor="human"`, set by the server); a person's incident is
 * confirmed at once.
 */
import { ClipboardPlus, TriangleAlert } from "lucide-react";
import { useState, type FormEvent } from "react";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Input,
  SegmentedControl,
  Select,
  Textarea,
} from "@/ui";
import { useLogEvent, useLogIncident, type KindView, type TypedKind } from "./api";
import { kindOptions } from "./words";

const MAX_NOTE = 2000;
const WELL_RE = /^[A-Z]{1,2}[0-9]{1,3}$/;
const METRIC_RE = /^[a-z0-9_]{1,64}$/;

/** Wells typed as `B3, B4` or `b3 b4`, upper-cased. */
export function parseWells(text: string): string[] {
  return text
    .split(/[\s,;]+/)
    .map((w) => w.trim().toUpperCase())
    .filter(Boolean);
}

/** Log a calibration, a part change, a service visit, a move or a note. */
export function LogEvent({
  instrumentId,
  kinds,
}: {
  instrumentId: string;
  kinds: readonly KindView[];
}) {
  const log = useLogEvent(instrumentId);
  const [kind, setKind] = useState<TypedKind>("calibration");
  const [at, setAt] = useState("");
  const [calibration, setCalibration] = useState("");
  const [component, setComponent] = useState("");
  const [note, setNote] = useState("");
  const [tried, setTried] = useState(false);

  const componentError =
    tried && kind === "component_change" && !component.trim()
      ? "Say which part was changed."
      : null;
  const noteError = tried && kind === "note" && !note.trim() ? "Write the note." : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if ((kind === "component_change" && !component.trim()) || (kind === "note" && !note.trim()))
      return;
    log.mutate(
      {
        kind,
        note,
        at: at || null,
        calibration_type: kind === "calibration" ? calibration.trim() || null : null,
        component: kind === "component_change" ? component.trim() : null,
      },
      {
        onSuccess: () => {
          setAt("");
          setCalibration("");
          setComponent("");
          setNote("");
          setTried(false);
        },
      },
    );
  };

  return (
    <Card as="section" aria-labelledby="instr-log-event">
      <CardHeader
        id="instr-log-event"
        title="Log an event"
        hint="What happened to the instrument that its run files do not say."
      />
      <CardBody>
        <form onSubmit={submit} noValidate className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="What happened">
              <Select<TypedKind>
                value={kind}
                onValueChange={(v) => {
                  setKind(v);
                  setTried(false);
                }}
                options={kindOptions(kinds)}
              />
            </Field>
            <Field label="When" optional hint="The day you log it, if left empty.">
              <Input type="date" value={at} onChange={(e) => setAt(e.target.value)} />
            </Field>
          </div>
          {kind === "calibration" ? (
            <Field
              label="Which calibration"
              optional
              hint="Background, ROI, uniformity, a dye … ; “calibration” if left empty."
            >
              <Input
                value={calibration}
                onChange={(e) => setCalibration(e.target.value)}
                maxLength={60}
                autoComplete="off"
              />
            </Field>
          ) : null}
          {kind === "component_change" ? (
            <Field
              label="Which part"
              hint="The block, the heated cover, the lamp …"
              error={componentError}
            >
              <Input
                value={component}
                onChange={(e) => setComponent(e.target.value)}
                maxLength={60}
                required
                autoComplete="off"
              />
            </Field>
          ) : null}
          <Field label="Note" optional={kind !== "note"} error={noteError}>
            <Textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={MAX_NOTE}
              showCount
              rows={2}
            />
          </Field>
          <div>
            <Button
              type="submit"
              variant="primary"
              icon={<ClipboardPlus />}
              loading={log.isPending}
            >
              Log it
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}

/** Log an incident the person saw: confirmed at once, since a person logs it. */
export function LogIncident({ instrumentId }: { instrumentId: string }) {
  const log = useLogIncident(instrumentId);
  const [wellsText, setWellsText] = useState("");
  const [metric, setMetric] = useState("");
  const [direction, setDirection] = useState<"low" | "high">("low");
  const [note, setNote] = useState("");
  const [tried, setTried] = useState(false);

  const wells = parseWells(wellsText);
  const badWells = wells.filter((w) => !WELL_RE.test(w));
  const wellsError = !tried
    ? null
    : !wells.length
      ? "Name at least one well, such as B3."
      : badWells.length
        ? `Not a well position: ${badWells.join(", ")}. Wells are written like B3 or AA12.`
        : null;
  const metricError =
    tried && !METRIC_RE.test(metric.trim())
      ? "A metric code is lower-case letters, digits and _, such as plateau."
      : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (!wells.length || badWells.length || !METRIC_RE.test(metric.trim())) return;
    log.mutate(
      { wells, metric: metric.trim(), direction, note, run_hash: null },
      {
        onSuccess: () => {
          setWellsText("");
          setMetric("");
          setNote("");
          setTried(false);
        },
      },
    );
  };

  return (
    <Card as="section" aria-labelledby="instr-log-incident">
      <CardHeader
        id="instr-log-incident"
        title="Log an incident you saw"
        hint="Confirmed at once, since you log it: later runs on this instrument that show the same wells and signal are flagged as seen before."
      />
      <CardBody>
        <form onSubmit={submit} noValidate className="flex flex-col gap-4">
          <Field label="Wells" hint="Such as B3, B4." error={wellsError}>
            <Input
              value={wellsText}
              onChange={(e) => setWellsText(e.target.value)}
              className="font-mono"
              autoComplete="off"
              required
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto]">
            <Field
              label="What was off (metric code)"
              hint="The code qPilot uses, such as plateau or cq_residual."
              error={metricError}
            >
              <Input
                value={metric}
                onChange={(e) => setMetric(e.target.value)}
                maxLength={64}
                className="font-mono"
                autoComplete="off"
                required
              />
            </Field>
            <div className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-fg">Which way</span>
              <SegmentedControl<"low" | "high">
                label="Which way"
                value={direction}
                onValueChange={setDirection}
                options={[
                  { value: "low", label: "Low" },
                  { value: "high", label: "High" },
                ]}
              />
            </div>
          </div>
          <Field label="What you saw" optional>
            <Textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={MAX_NOTE}
              showCount
              rows={2}
            />
          </Field>
          <div>
            <Button type="submit" icon={<TriangleAlert />} loading={log.isPending}>
              Log the incident
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}
