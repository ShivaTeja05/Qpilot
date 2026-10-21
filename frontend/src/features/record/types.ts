/**
 * The shapes the Record section reads, from the generated contract: api's chain view
 * (`qpilot/web/contract.py`) and api-files' record export / verify (`contract_files.py`).
 */
import type { Schemas } from "@/api/client";

export type Actor = Schemas["DecisionEntry"]["actor"];
export type EntryStatus = Schemas["DecisionEntry"]["status"];

/** One line of the study's decision chain (`decisions.jsonl`), with its card and option in words. */
export interface ChainEntry {
  seq: number;
  prev_hash: string;
  hash: string;
  card_id: string;
  /** The card's question in words ("Which control genes to normalise to"). */
  card_title?: string | null;
  option: string;
  /** The option's label in words. */
  option_label?: string | null;
  reason: string;
  actor: Actor;
  status: EntryStatus;
  at: string;
  /** Written by Undo (a new entry restoring the option before). */
  undo?: boolean;
}

/** `GET /api/studies/{id}/decisions` as the server sends it (`qpilot/web/contract.py`). */
export type DecisionsApi = Schemas["DecisionsView"];
/** A write refused as stale: logged beside the chain (`attempts.jsonl`), it never moved the head. */
export type StaleAttempt = Schemas["StaleAttempt"];

/** The chain as the Record section reads it. */
export interface DecisionsView {
  study_id: string;
  /** The chain's genesis: the input file's SHA-256. */
  root: string | null;
  head: string;
  entries: ChainEntry[];
  /** The server re-computed every link and hash. */
  chain_intact: boolean;
  /** The first entry that fails, when the chain is broken. */
  broken_at: number | null;
  /** Hashes of the agent requests still waiting for a person. */
  waiting: string[];
  attempts: StaleAttempt[];
}

/** The server's chain view in the Record section's shape. */
export function fromApi(view: DecisionsApi): DecisionsView {
  const entries = view.entries.map((e) => ({
    ...e.entry,
    card_title: e.card_title,
    option_label: e.option_label,
    undo: e.undo,
  }));
  return {
    study_id: view.study_id,
    root: view.root || entries[0]?.prev_hash || null,
    head: view.head,
    entries,
    chain_intact: view.chain_intact,
    broken_at: view.broken_at ?? null,
    waiting: view.pending.map((p) => p.entry.hash),
    attempts: view.attempts,
  };
}

/** A file qPilot wrote into its export folder (beside the store), served at `url` as an attachment. */
export type DownloadLink = Schemas["DownloadLink"];
/** The result of `POST /api/studies/{id}/record` (on the job); also each row of `GET …/records`. */
export type RecordExport = Schemas["RecordExported"];
/** `GET /api/studies/{id}/records`: the records exported for the study, newest first. */
export type RecordList = Schemas["RecordList"];
/** `core.record.VerifyReport`. */
export type VerifyReport = Schemas["VerifyReport"];
/** What a record says about itself (`record.json`), read from the uploaded zip. */
export type RecordFacts = Schemas["RecordFacts"];
/** Whether a robustness audit verifies and belongs to the record. */
export type AuditBinding = Schemas["AuditBinding"];
/** `POST /api/records/verify`. */
export type VerifyResult = Schemas["RecordVerified"];
