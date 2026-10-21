/**
 * Small pieces of the Instruments section: who wrote an entry (icon + word), the logbook chain's
 * check, a G-INSTR status (glyph + word), the latest calibrations with their age, an incident's
 * facts, and a typed note shown as text (never markup).
 */
import {
  Bot,
  CircleCheck,
  CircleMinus,
  CircleX,
  Cpu,
  Info,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
  User,
} from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { count, plural } from "@/lib/format";
import { Badge, Hash } from "@/ui";
import type { CalibrationAge, IncidentView, InstrumentSummary } from "./api";
import {
  ACTOR_HINT,
  ACTOR_WORD,
  GATE_TONE,
  GATE_WORD,
  INCIDENT_STATUS,
  asActor,
  asGateStatus,
  day,
  sentence,
  signatureWords,
  sourceWord,
  wellList,
  words,
  type Actor,
  type GateStatus,
} from "./words";

const ACTOR_ICON: Record<Actor, ReactNode> = {
  human: <User aria-hidden />,
  agent: <Bot aria-hidden />,
  system: <Cpu aria-hidden />,
};

/** Who wrote an entry: an icon and a word (a person, an agent, qPilot from a file). */
export function ActorTag({ actor, className }: { actor: string; className?: string }) {
  const a = asActor(actor);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-[13px] text-fg [&_svg]:size-3.5",
        className,
      )}
      title={ACTOR_HINT[a]}
    >
      <span className="text-muted">{ACTOR_ICON[a]}</span>
      {ACTOR_WORD[a]}
    </span>
  );
}

/** Where an entry came from: the file, two files, or typed. */
export function SourceTag({ source }: { source: string }) {
  return <span className="text-[13px] text-muted">{sourceWord(source)}</span>;
}

/** Whether the logbook's hash chain verifies (glyph + words; never colour alone). */
export function ChainBadge({ ok }: { ok: boolean }) {
  return ok ? (
    <Badge tone="ok" icon={<ShieldCheck aria-hidden />}>
      Logbook chain verifies
    </Badge>
  ) : (
    <Badge tone="danger" icon={<ShieldAlert aria-hidden />}>
      Logbook chain does not verify
    </Badge>
  );
}

/** What is wrong with a chain, in words, and what it means for the page. */
export function ChainProblems({ problems }: { problems: readonly string[] }) {
  if (!problems.length) return null;
  return (
    <div className="rounded-lg border border-danger/30 bg-danger-soft/50 p-3 text-[13px]">
      <p className="font-medium text-fg">
        The logbook was changed outside qPilot, so its entries are not shown or counted:
      </p>
      <ul className="mt-1 list-disc pl-5 text-fg">
        {problems.map((p) => (
          <li key={p}>{sentence(p)}</li>
        ))}
      </ul>
    </div>
  );
}

const GATE_ICON: Record<GateStatus, ReactNode> = {
  pass: <CircleCheck aria-hidden />,
  warn: <TriangleAlert aria-hidden />,
  info: <Info aria-hidden />,
  fail: <CircleX aria-hidden />,
  not_applicable: <CircleMinus aria-hidden />,
};

/** A G-INSTR status as glyph + word. */
export function GateChip({ status }: { status: string }) {
  const s = asGateStatus(status);
  return (
    <Badge tone={GATE_TONE[s]} icon={GATE_ICON[s]}>
      {GATE_WORD[s]}
    </Badge>
  );
}

/** The latest calibration of each type, with its age in days (from the logbook). */
export function Calibrations({ items }: { items: readonly CalibrationAge[] }) {
  if (!items.length) return <span className="text-muted">None logged yet</span>;
  return (
    <ul className="flex flex-col gap-0.5">
      {items.map((c) => (
        <li key={c.type}>
          <span className="text-fg">{words(c.type)}</span>
          <span className="text-muted">
            {" "}
            · <span className="tabular text-fg">{plural(c.age_days, "day")}</span> ago, on{" "}
            {day(c.performed_on)} ({sourceWord(c.source).toLowerCase()})
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Open incidents and how many wait for a person, in words. */
export function OpenCount({ summary }: { summary: InstrumentSummary }) {
  if (!summary.n_open_incidents) return <span className="text-muted">None open</span>;
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <span className="tabular">{plural(summary.n_open_incidents, "open incident")}</span>
      {summary.n_proposed ? (
        <Badge
          tone="warn"
          icon={<Bot aria-hidden />}
          className="h-auto min-h-5 max-w-full shrink py-0.5 whitespace-normal"
        >
          {count(summary.n_proposed)} proposed by an agent, waiting for you
        </Badge>
      ) : null}
    </span>
  );
}

/** Text a person or an agent typed: shown exactly as typed, as text (markup stays literal). */
export function TypedNote({ text, className }: { text: string; className?: string }) {
  if (!text) return null;
  return (
    <p
      className={cn(
        "border-l-2 border-line-strong pl-3 text-[13px] whitespace-pre-wrap break-words text-fg",
        className,
      )}
    >
      {text}
    </p>
  );
}

const FIXED = { word: "Fixed", tone: "ok" as const };

/** An incident's facts: entry, status, wells, signature, run, who and when, the note, its fix. */
export function IncidentFacts({ incident }: { incident: IncidentView }) {
  const status = incident.fixes.length ? FIXED : INCIDENT_STATUS[incident.status];
  const sig = signatureWords(incident);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
        <span className="font-mono text-xs text-muted">entry {count(incident.seq)}</span>
        <Badge tone={status.tone}>{status.word}</Badge>
        {incident.wells.length ? (
          <span className="text-fg">
            Wells <span className="font-mono">{wellList(incident.wells)}</span>
          </span>
        ) : null}
        {sig ? <span className="text-fg">{sig}</span> : null}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted">
        <ActorTag actor={incident.actor} />
        <span>{day(incident.at)}</span>
        {incident.run_hash ? <Hash value={incident.run_hash} prefix="run" /> : null}
      </div>
      <TypedNote text={incident.note} />
      {incident.fixes.map((f, i) => (
        <div key={f.seq ?? i} className="text-[13px]">
          <span className="font-medium text-fg">What fixed it</span>
          {f.at ? <span className="text-muted"> ({day(f.at)})</span> : null}
          <TypedNote text={f.note} className="mt-1" />
        </div>
      ))}
    </div>
  );
}
