/**
 * The Instruments section's words: who wrote a logbook entry, where it came from, what each entry
 * and each run-file field says, the G-INSTR statuses and the lookback's outcome. The wording
 * follows the method cards (`methods/instrument_context.md`, `methods/lookback.md`): "the file
 * says", "seen before", "changes k of N conclusions"; status words only. Pure functions.
 */
import type { Tone } from "@/ui";
import { count, fixed, plural } from "@/lib/format";
import type { EventView, IncidentView, KindView, TypedKind } from "./api";

// ---- dates ----------------------------------------------------------------------------------

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * An ISO day (`2025-08-28`) as `28 Aug 2025`, read as written (no time zone moves it a day);
 * a date-time keeps its day and adds the time it states (`10 May 2019, 09:00 UTC`).
 */
export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?(.*)$/.exec(iso.trim());
  if (!m) return iso;
  const [, y, mo, d, hh, mm, rest] = m;
  const date = `${Number(d)} ${MONTHS[Number(mo) - 1] ?? mo} ${y}`;
  if (!hh) return date;
  const zone = /Z|[+-]00:?00/.test(rest ?? "") ? " UTC" : "";
  return `${date}, ${hh}:${mm}${zone}`;
}

/** Today as an ISO day in this browser's calendar (the default of a date field). */
export function todayIso(now: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`;
}

// ---- who and where from ---------------------------------------------------------------------

export type Actor = "human" | "agent" | "system";

export const ACTOR_WORD: Record<Actor, string> = {
  human: "A person",
  agent: "An agent",
  system: "qPilot",
};

export const ACTOR_HINT: Record<Actor, string> = {
  human: "Typed by a person in qPilot",
  agent: "Proposed by an agent through qPilot's tools; a person decides",
  system: "Written by qPilot from a run file",
};

export function asActor(value: string): Actor {
  return value === "human" || value === "agent" ? value : "system";
}

export const SOURCE_WORD: Record<string, string> = {
  file: "The file says",
  inferred: "Inferred from two files",
  typed: "Typed",
};

export function sourceWord(source: string): string {
  return SOURCE_WORD[source] ?? source;
}

// ---- event kinds ----------------------------------------------------------------------------

/** What each kind a person can log means, under its word in the kind picker. */
export const KIND_HINT: Record<TypedKind, string> = {
  calibration: "A calibration done on the instrument: background, ROI, uniformity, a dye.",
  component_change: "A part replaced: the block, the heated cover, the lamp.",
  service: "An engineer's visit or a maintenance job.",
  move: "The instrument was moved to another place.",
  note: "Anything else worth remembering about it.",
};

/** The kinds the server lets a person log, in its words (falls back to the kind's id). */
export function kindOptions(kinds: readonly KindView[]) {
  return kinds.map((k) => ({ value: k.id, label: k.word, hint: KIND_HINT[k.id] }));
}

// ---- small word helpers ---------------------------------------------------------------------

/** `optical_head` → `optical head`, `cq_residual` → `Cq residual`, first letter up. */
export function words(code: string | null | undefined): string {
  if (!code) return "";
  const text = code.replace(/[_-]+/g, " ").trim();
  const fixedCq = text.replace(/\bcq\b/gi, "Cq").replace(/\broi\b/gi, "ROI");
  return fixedCq.charAt(0).toUpperCase() + fixedCq.slice(1);
}

/** A sentence from a fixed phrase: first letter up, a full stop at the end. */
export function sentence(text: string): string {
  const t = text.trim();
  if (!t) return t;
  const up = t.charAt(0).toUpperCase() + t.slice(1);
  return /[.!?]$/.test(up) ? up : `${up}.`;
}

/** Wells as a list a person reads: `B3, B4`. */
export function wellList(wells: readonly string[]): string {
  return wells.join(", ");
}

/** An incident's signature in words: `Cq residual high`, or the vendor code. */
export function signatureWords(i: Pick<IncidentView, "metric" | "direction" | "error_code">) {
  const parts: string[] = [];
  if (i.metric) parts.push(i.direction ? `${words(i.metric)} ${i.direction}` : words(i.metric));
  if (i.error_code) parts.push(`vendor code ${i.error_code}`);
  return parts.join(" · ");
}

export const INCIDENT_STATUS: Record<
  IncidentView["status"],
  { word: string; tone: Tone; meaning: string }
> = {
  proposed: {
    word: "Waiting for you",
    tone: "warn",
    meaning: "An agent proposed it; it matches nothing until a person confirms it.",
  },
  confirmed: {
    word: "Confirmed",
    tone: "accent",
    meaning: "Counts as seen before when a later run shows the same wells and signal.",
  },
  rejected: {
    word: "Turned down",
    tone: "neutral",
    meaning: "A person turned it down; it matches nothing.",
  },
};

// ---- a logbook entry's details --------------------------------------------------------------

const RUN_EVENT_WORD: Record<string, string> = {
  pause: "Paused",
  lid_open: "Lid opened",
  drawer: "Drawer opened",
  abort: "Aborted",
  power: "Power event",
  resume: "Resumed",
};

function str(v: unknown): string | null {
  return typeof v === "string" && v ? v : typeof v === "number" ? String(v) : null;
}

/**
 * What one logbook entry says beyond its kind, in words: the calibration's type and day, which
 * part, what the file states (a pause at a cycle), an incident's wells and signature, or which
 * incident a decision or a fix is about. Unknown details are listed as `name: value`.
 */
export function eventDetails(e: Pick<EventView, "kind" | "details" | "wells">): string[] {
  const d = { ...(e.details ?? {}) } as Record<string, unknown>;
  const out: string[] = [];
  const take = (k: string) => {
    const v = d[k];
    delete d[k];
    return v;
  };
  switch (e.kind) {
    case "calibration": {
      const type = str(take("type"));
      const on = str(take("performed_on"));
      if (type) out.push(`${words(type)} calibration`);
      if (on) out.push(`done on ${day(on)}`);
      break;
    }
    case "component_change": {
      const part = str(take("component"));
      if (part) out.push(`Part: ${words(part).toLowerCase()}`);
      break;
    }
    case "firmware_change":
    case "software_change": {
      const from = str(take("from"));
      const to = str(take("to"));
      if (from || to) out.push(`From ${from ?? "—"} to ${to ?? "—"}`);
      break;
    }
    case "run_event": {
      const what = str(take("what"));
      const state = str(take("state"));
      const cycle = take("cycle");
      if (what === "run_state") out.push(`Run state: ${state ?? "—"}`);
      else if (what)
        out.push(
          `${RUN_EVENT_WORD[what] ?? words(what)}${typeof cycle === "number" ? ` at cycle ${count(cycle)}` : ""}`,
        );
      break;
    }
    case "incident": {
      const action = str(take("action"));
      const target = take("incident");
      const status = str(take("status"));
      const sig = take("signature") as
        { metric?: string; direction?: string; error_code?: string } | undefined;
      take("numbers");
      if (action === "confirm" && typeof target === "number")
        out.push(`Confirmed the incident at entry ${count(target)}`);
      else if (action === "reject" && typeof target === "number")
        out.push(`Turned down the incident at entry ${count(target)}`);
      else {
        if (e.wells.length) out.push(`Wells ${wellList(e.wells)}`);
        if (sig)
          out.push(
            signatureWords({
              metric: sig.metric ?? null,
              direction: sig.direction ?? null,
              error_code: sig.error_code ?? null,
            }),
          );
        if (status === "proposed") out.push("proposed");
        else if (status === "confirmed") out.push("confirmed when logged");
      }
      break;
    }
    case "fix": {
      const target = take("incident");
      if (typeof target === "number") out.push(`Fix for the incident at entry ${count(target)}`);
      break;
    }
    default:
      break;
  }
  for (const [k, v] of Object.entries(d)) {
    if (v == null || k === "signature") continue;
    const value = typeof v === "object" ? JSON.stringify(v) : String(v);
    out.push(`${words(k)}: ${value}`);
  }
  return out.filter(Boolean);
}

// ---- run files ------------------------------------------------------------------------------

export const SOURCE_KIND_WORD: Record<string, string> = {
  eds: "QuantStudio-family run file (.eds)",
  quantstudio_export: "QuantStudio results export",
  cfx_run_information: "Bio-Rad CFX run information export",
  rdml: "RDML file",
};

export const RUN_STATE_WORD: Record<string, string> = {
  complete: "Completed",
  aborted: "Aborted",
  stopped: "Stopped",
  init: "Not started",
};

export const DATE_SOURCE_WORD: Record<string, string> = {
  instrument: "from the instrument's clock",
  "run name": "from the date in the run's name (not an instrument fact)",
};

/** The serial fields a file had, named, never their values. */
export const SERIAL_WORD: Record<string, string> = {
  serial: "the instrument's serial number",
  block_serial: "the block's serial number",
  cover_serial: "the heated cover's serial number",
  optical_head_serial: "the optical head's serial number",
  shuttle_serial: "the shuttle's serial number",
};

export const CHECKED_WORD: Record<string, string> = {
  identity: "which instrument",
  run_state: "whether the run finished",
  calibrations: "calibrations",
  event_log: "pauses and lid openings",
  temperature: "temperatures",
  well_flags: "vendor flags",
};

/** Identity keys shown under their own words (serials are never shown, only named). */
export const IDENTITY_WORD: Record<string, string> = {
  model: "Model",
  instrument_type: "Instrument type",
  firmware: "Firmware",
  software: "Software",
  block_type: "Block",
};

export const TEMPERATURE_WORD: Record<string, string> = {
  max_hold_deviation_c: "Largest hold deviation",
  zone_spread_p95_c: "Zone spread (95th percentile, holds)",
  min_lid_c_cycling: "Lowest lid temperature while cycling",
};

/** A temperature in °C, two decimals as the file gives them. */
export function celsius(value: unknown): string {
  return typeof value === "number" ? `${fixed(value, 2)} °C` : "not in the file";
}

/** A list joined as people write it: `a`, `a and b`, `a, b and c`. */
export function andList(items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
}

/** The serial fields a file carries, in one sentence (named, never their values). */
export function serialsSentence(present: readonly string[]): string {
  if (!present.length) return "The file carries no serial number.";
  const named = present.map((k) => SERIAL_WORD[k] ?? words(k).toLowerCase());
  return `The file carries ${andList(named)}. They stay in this computer's registry and are never shown or sent.`;
}

/** What a run-file event says: `Paused at cycle 23 (look at cycles 23–24)`. */
export function runEventWords(e: Record<string, unknown>): string {
  const kind = str(e.kind) ?? "event";
  const cycle = typeof e.cycle === "number" ? ` at cycle ${count(e.cycle)}` : "";
  const cycles = Array.isArray(e.cycles)
    ? (e.cycles as unknown[]).filter((c) => typeof c === "number")
    : [];
  const look =
    cycles.length > 1
      ? ` (look at cycles ${count(cycles[0] as number)}–${count(cycles.at(-1) as number)})`
      : "";
  return `${RUN_EVENT_WORD[kind] ?? words(kind)}${cycle}${look}`;
}

export const QUESTION_REASON: Record<string, string> = {
  unknown_serial:
    "The file carries a serial number that no registered instrument has yet. Say which one it is, once: the next file from it is recognised by itself.",
  no_serial:
    "The file carries no serial number, and no instrument was linked to how it names itself yet. Say which one it is, once: the next file from it is recognised by itself.",
};

// ---- G-INSTR statuses -----------------------------------------------------------------------

export type GateStatus = "pass" | "warn" | "info" | "fail" | "not_applicable";

export const GATE_WORD: Record<GateStatus, string> = {
  pass: "Pass",
  warn: "Warn",
  info: "Info",
  fail: "Fail",
  not_applicable: "Not applicable",
};

export const GATE_TONE: Record<GateStatus, Tone> = {
  pass: "ok",
  warn: "warn",
  info: "info",
  fail: "danger",
  not_applicable: "neutral",
};

export function asGateStatus(status: string): GateStatus {
  return status in GATE_WORD ? (status as GateStatus) : "not_applicable";
}

// ---- the lookback ---------------------------------------------------------------------------

export const LOOKBACK_STATUS: Record<string, string> = {
  evaluated: "Evaluated",
  cannot_evaluate: "Cannot evaluate",
  no_runs_in_window: "None of the study's runs is in the window",
};

/** The lookback's headline: `Changes 3 of 58 conclusions`. */
export function lookbackHeadline(v: { status: string; n_changed: number; n_conclusions: number }) {
  if (v.status !== "evaluated") return LOOKBACK_STATUS[v.status] ?? words(v.status);
  return `Changes ${count(v.n_changed)} of ${plural(v.n_conclusions, "conclusion")}`;
}
