/**
 * Read a run file: drop an `.eds`, a QuantStudio or CFX export, or an RDML file, and see what it
 * says about the instrument (model, software, the run's state and times, calibrations and their
 * age, pauses, temperatures, vendor flags), its G-INSTR lines, and the registered instrument it
 * names, or the one question "Which instrument is this?" with **Link**. Serial numbers are named
 * (the file has one), never shown: the server never sends them.
 */
import { FileUp, Link2 } from "lucide-react";
import { useId, useRef, useState, type DragEvent, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { count } from "@/lib/format";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ErrorPanel,
  KeyValues,
  LoadingBlock,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/ui";
import { FactText } from "@/features/results/FactText";
import {
  useLinkRun,
  useReadRun,
  type InstrumentSummary,
  type Linked,
  type RunFileView,
  type RunQuestion,
} from "./api";
import { GateChip } from "./Pieces";
import { RegisterButton } from "./Register";
import {
  CHECKED_WORD,
  DATE_SOURCE_WORD,
  IDENTITY_WORD,
  QUESTION_REASON,
  RUN_STATE_WORD,
  SOURCE_KIND_WORD,
  TEMPERATURE_WORD,
  andList,
  celsius,
  day,
  runEventWords,
  sentence,
  serialsSentence,
  words,
} from "./words";

const ACCEPT = ".eds,.csv,.txt,.rdml,.xml";

type Dict = Record<string, unknown>;

function asDict(v: unknown): Dict {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Dict) : {};
}
function asList(v: unknown): Dict[] {
  return Array.isArray(v) ? v.map(asDict) : [];
}
function text(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}

/** "Yes, expired" / "No" / "Not known", as a word (never colour alone). */
function Expired({ value }: { value: unknown }) {
  if (value === true) return <Badge tone="warn">Yes, past its expiry</Badge>;
  if (value === false) return <span className="text-fg">No</span>;
  return <span className="text-muted">Not known</span>;
}

/** What the run file says, from the run context's model view (no serial, no local fact). */
function WhatItSays({ context }: { context: Dict }) {
  const identity = asDict(context.identity);
  const run = asDict(context.run);
  const calibrations = asList(context.calibrations);
  const events = asList(context.events);
  const temperature = context.temperature == null ? null : asDict(context.temperature);
  const flags = asDict(context.well_flags);
  const notes = Array.isArray(context.notes)
    ? context.notes.filter((n) => typeof n === "string")
    : [];
  const checked = Array.isArray(context.checked)
    ? (context.checked as unknown[]).filter((c): c is string => typeof c === "string")
    : [];
  const serials = Array.isArray(context.serials_present)
    ? (context.serials_present as unknown[]).filter((s): s is string => typeof s === "string")
    : [];

  const rows: [ReactNode, ReactNode][] = [];
  const kind = text(context.source_kind);
  if (kind) rows.push(["Kind of file", SOURCE_KIND_WORD[kind] ?? words(kind)]);
  for (const [key, word] of Object.entries(IDENTITY_WORD)) {
    const value = text(identity[key]);
    if (value) rows.push([word, value]);
  }
  if (!text(identity.model))
    rows.push([
      "Model",
      <span key="m" className="text-muted">
        Not in the file
      </span>,
    ]);
  const state = text(run.state);
  rows.push([
    "Run",
    state ? (
      (RUN_STATE_WORD[state] ?? words(state))
    ) : (
      <span key="s" className="text-muted">
        The file does not say whether it finished
      </span>
    ),
  ]);
  if (text(run.start) || text(run.end))
    rows.push(["Started – ended", `${day(text(run.start))} – ${day(text(run.end))}`]);
  const source = text(run.date_source);
  if (text(run.date))
    rows.push([
      "Run date",
      `${day(text(run.date))}${source ? `, ${DATE_SOURCE_WORD[source] ?? source}` : ""}`,
    ]);
  if (temperature)
    for (const [key, word] of Object.entries(TEMPERATURE_WORD))
      rows.push([
        word,
        <span key={key} className="tabular">
          {celsius(temperature[key])}
        </span>,
      ]);
  const flagged = Object.entries(flags);
  if (checked.includes("well_flags") || flagged.length)
    rows.push([
      "Vendor flags",
      flagged.length ? (
        <ul key="f" className="flex flex-col">
          {flagged.map(([well, set]) => (
            <li key={well}>
              <span className="font-mono">{well}</span>:{" "}
              {Array.isArray(set) ? set.map(String).join(", ") : String(set)}
            </li>
          ))}
        </ul>
      ) : (
        "None set"
      ),
    ]);
  rows.push(["Serial numbers", serialsSentence(serials)]);
  if (checked.length)
    rows.push([
      "What it let qPilot check",
      sentence(andList(checked.map((c) => CHECKED_WORD[c] ?? words(c).toLowerCase()))),
    ]);

  return (
    <div className="flex flex-col gap-4">
      <KeyValues rows={rows} />
      {calibrations.length ? (
        <div className="overflow-x-auto rounded-lg border border-line">
          <Table caption="Calibrations the file records">
            <THead>
              <TR>
                <TH>Calibration</TH>
                <TH>Done on</TH>
                <TH numeric>Age at the run</TH>
                <TH>Expires on</TH>
                <TH>Expired at the run</TH>
              </TR>
            </THead>
            <TBody>
              {calibrations.map((c, i) => (
                <TR key={text(c.type) ?? i}>
                  <TD>{text(c.label) ?? words(text(c.type))}</TD>
                  <TD className="whitespace-nowrap">
                    {text(c.performed_on)
                      ? day(text(c.performed_on))
                      : (text(c.performed_on_raw) ?? "Not in the file")}
                  </TD>
                  <TD numeric>
                    {typeof c.age_days === "number" ? `${count(c.age_days)} days` : "—"}
                  </TD>
                  <TD className="whitespace-nowrap">
                    {text(c.expires_on) ? day(text(c.expires_on)) : "—"}
                  </TD>
                  <TD>
                    <Expired value={c.expired_at_run} />
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
      ) : null}
      {events.length ? (
        <div>
          <h4 className="text-[13px] font-medium text-fg">During the run</h4>
          <ul className="mt-1 list-disc pl-5 text-[13px] text-fg">
            {events.map((e, i) => (
              <li key={i}>{runEventWords(e)}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {notes.length ? (
        <div>
          <h4 className="text-[13px] font-medium text-fg">What the file does not say</h4>
          <ul className="mt-1 list-disc pl-5 text-[13px] text-muted">
            {notes.map((n) => (
              <li key={n}>{sentence(n)}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** "Which instrument is this?": the registered instruments as choices, then Link. */
function WhichInstrument({ run, question }: { run: RunFileView; question: RunQuestion }) {
  const name = useId();
  const [choice, setChoice] = useState<string>("");
  const [linked, setLinked] = useState<Linked | null>(null);
  const link = useLinkRun(run.run_id);
  const choices = question.choices.filter((c) => c.instrument_id);

  if (linked) {
    const to = choices.find((c) => c.instrument_id === linked.instrument_id);
    return (
      <div role="status" className="rounded-lg border border-ok/30 bg-ok-soft/50 p-3 text-[13px]">
        <p className="text-fg">{linked.message}</p>
        <p className="mt-1">
          <a
            className="font-medium text-accent-strong underline-offset-2 hover:underline"
            href={`#/instruments/${encodeURIComponent(linked.instrument_id)}`}
          >
            Open {to?.display_name ?? linked.instrument_id}
          </a>
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-accent/30 bg-accent-soft/40 p-3">
      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-semibold text-fg">{question.question}</legend>
        <p className="text-[13px] text-muted">
          {QUESTION_REASON[question.reason] ?? "No registered instrument matches this file yet."}
        </p>
        {choices.length ? (
          <div className="flex flex-col gap-1.5">
            {choices.map((c) => {
              const id = `${name}-${c.instrument_id}`;
              return (
                <label
                  key={c.instrument_id}
                  htmlFor={id}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-0.5 text-[13px] text-fg hover:bg-bg-subtle"
                >
                  <input
                    id={id}
                    type="radio"
                    name={name}
                    value={c.instrument_id}
                    checked={choice === c.instrument_id}
                    onChange={() => setChoice(c.instrument_id!)}
                    className="size-4 accent-accent"
                  />
                  {c.display_name ?? c.instrument_id}
                </label>
              );
            })}
          </div>
        ) : (
          <p className="text-[13px] text-fg">
            No instrument is registered yet. Register it first, then read the file again.
          </p>
        )}
      </fieldset>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {choices.length ? (
          <Button
            variant="primary"
            size="sm"
            icon={<Link2 />}
            disabled={!choice}
            loading={link.isPending}
            onClick={() => link.mutate(choice, { onSuccess: setLinked })}
          >
            Link
          </Button>
        ) : null}
        <RegisterButton variant="secondary" label="Register a new one" />
      </div>
    </div>
  );
}

/** What one run file says, its G-INSTR lines and its instrument (or the question). */
export function RunFileAnswer({
  run,
  instruments,
}: {
  run: RunFileView;
  instruments: readonly InstrumentSummary[];
}) {
  const named = run.instrument_id
    ? instruments.find((i) => i.instrument_id === run.instrument_id)
    : undefined;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="min-w-0 truncate font-mono text-[13px] text-fg" title={run.name}>
          {run.name}
        </p>
      </div>

      <section aria-label="Which instrument">
        {run.instrument_id ? (
          <p className="text-[13px] text-fg">
            From{" "}
            <a
              className="font-medium text-accent-strong underline-offset-2 hover:underline"
              href={`#/instruments/${encodeURIComponent(run.instrument_id)}`}
            >
              {named?.display_name ?? run.instrument_id}
            </a>
            , recognised from the file itself.
          </p>
        ) : run.question ? (
          <WhichInstrument run={run} question={run.question} />
        ) : null}
      </section>

      {run.gate.length ? (
        <section aria-labelledby="run-gate">
          <h3 id="run-gate" className="text-sm font-semibold text-fg">
            What qPilot checks (G-INSTR)
          </h3>
          <p className="text-xs text-muted">
            Facts to weigh, never a reason to set the run aside by themselves.
          </p>
          <ul className="mt-2 flex flex-col gap-1.5">
            {run.gate.map((line, i) => (
              <li key={`${line.code}-${i}`} className="flex items-start gap-2 text-[13px]">
                <GateChip status={line.status} />
                <FactText text={line.text} className="text-fg" />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="run-says">
        <h3 id="run-says" className="mb-2 text-sm font-semibold text-fg">
          What the file says
        </h3>
        <WhatItSays context={run.context} />
      </section>
    </div>
  );
}

/** The card: choose or drop a file, then its answer. */
export function RunFileCard({ instruments }: { instruments: readonly InstrumentSummary[] }) {
  const read = useReadRun();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const inputId = useId();

  const choose = (files: FileList | null) => {
    const file = files?.[0];
    if (file) read.mutate(file);
  };
  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    choose(e.dataTransfer.files);
  };

  return (
    <Card as="section" aria-labelledby="instr-run">
      <CardHeader
        id="instr-run"
        title="Read a run file"
        hint="What a run file says about its instrument, and which instrument it is. The file is read on this computer; serial numbers are never shown."
      />
      <CardBody className="flex flex-col gap-4">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={drop}
          className={cn(
            "flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-5 text-center text-[13px] text-muted transition-colors",
            over ? "border-accent bg-accent-soft/40" : "border-line-strong",
          )}
        >
          <p>Drop an .eds, a QuantStudio or CFX export, or an RDML file here, or</p>
          <Button icon={<FileUp />} onClick={() => input.current?.click()} loading={read.isPending}>
            Choose a run file
          </Button>
          <label htmlFor={inputId} className="sr-only">
            Run file
          </label>
          <input
            id={inputId}
            ref={input}
            type="file"
            accept={ACCEPT}
            className="sr-only"
            tabIndex={-1}
            onChange={(e) => {
              choose(e.target.files);
              e.target.value = "";
            }}
          />
        </div>
        {read.isPending ? <LoadingBlock label="Reading the run file" lines={4} /> : null}
        {read.error ? (
          <ErrorPanel error={read.error} title="This file could not be read" compact />
        ) : null}
        {read.data && !read.isPending ? (
          <RunFileAnswer
            key={read.data.run_id + String(read.submittedAt)}
            run={read.data}
            instruments={instruments}
          />
        ) : null}
      </CardBody>
    </Card>
  );
}
