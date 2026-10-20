/**
 * The shapes the Record section reads. They mirror the Python models (`qpilot/schemas.py`
 * `DecisionEntry`, `qpilot/core/record.py` `RecordInfo` / `VerifyReport`) and are replaced by the
 * generated contract types (`Schemas[...]`) as each route lands.
 */

export type Actor = "human" | "agent" | "system";
export type EntryStatus = "applied" | "auto" | "pending_human" | "rejected" | "stale";

/** One line of the study's decision chain (`decisions.jsonl`), with its card and option in words. */
export interface ChainEntry {
  seq: number;
  prev_hash: string;
  hash: string;
  card_id: string;
  /** The card's question in words ("Which control genes to normalise to"). */
  card_title?: string | null;
  card_kind?: string | null;
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
export interface DecisionsApi {
  study_id: string;
  head: string;
  entries: DecisionEntryApi[];
  pending: DecisionEntryApi[];
  /** The chain's genesis (the input file's SHA-256), when the server sends it. */
  root?: string | null;
  /** The server re-computed every hash and link, when it sends it. */
  chain_intact?: boolean | null;
}

export interface DecisionEntryApi {
  entry: Omit<ChainEntry, "card_title" | "option_label" | "undo" | "card_kind">;
  card_title: string;
  option_label: string;
  undo: boolean;
}

/** The chain as the Record section reads it. */
export interface DecisionsView {
  study_id: string;
  /** The chain's first `prev_hash`: the input file's SHA-256 (null for an empty chain). */
  root: string | null;
  head: string;
  entries: ChainEntry[];
  chain_intact?: boolean | null;
  n_pending: number;
}

/** The server's chain view in the Record section's shape. */
export function fromApi(view: DecisionsApi): DecisionsView {
  const entries = view.entries.map((e) => ({ ...e.entry, card_title: e.card_title, option_label: e.option_label, undo: e.undo }));
  return {
    study_id: view.study_id,
    root: view.root ?? entries[0]?.prev_hash ?? null,
    head: view.head,
    entries,
    chain_intact: view.chain_intact,
    n_pending: view.pending.length,
  };
}

/** A file this server wrote into its export folder, served at `url` as an attachment. */
export interface DownloadLink {
  id: string;
  url: string;
  /** The file name the browser saves it under. */
  name: string;
  bytes: number;
}

/** The result of `POST /api/studies/{id}/record` (on the job); also each row of `GET …/records`. */
export interface RecordExport {
  study_id: string;
  record_id: string;
  chain_head: string;
  n_files: number;
  input_included: boolean;
  written_at?: string | null;
  download: DownloadLink;
  /** Card ids of choices that can change a conclusion and are still open. */
  open_flips?: string[];
  /** The chain head moved since the head the page sent. */
  head_moved?: boolean;
  /** The old page's warnings, in words. */
  warnings: string[];
  commands: { verify: string; rerun: string };
}

/** `GET /api/studies/{id}/records`: the records this launch exported, newest first. */
export interface RecordList {
  study_id: string;
  records: RecordExport[];
}

/** `core.record.VerifyReport`. */
export interface VerifyReport {
  ok: boolean;
  changed: string[];
  missing: string[];
  unlisted: string[];
  chain_broken_at: number | null;
  inconsistent: string[];
  n_entries: number;
  has_proposals: boolean;
  proposal_chain_broken_at: number | null;
  n_proposal_entries: number;
}

/** What a record says about itself (`record.json`), read from the uploaded zip. */
export interface RecordFacts {
  study_id?: string | null;
  input_sha256?: string | null;
  chain_head?: string | null;
  written_at?: string | null;
  input_included?: boolean | null;
  shared?: boolean;
  record_id?: string | null;
}

/** Whether a robustness audit verifies and belongs to the record. */
export interface AuditBinding {
  /** zip: the audit came in the uploaded zip; store: this qPilot's audit of the record's study. */
  source: "zip" | "store";
  ok: boolean;
  problems: string[];
  study_id?: string | null;
}

/** `POST /api/records/verify`. */
export interface VerifyResult {
  /** The record verifies (and its audit, when one is bound). */
  ok: boolean;
  file_name: string;
  summary: string[];
  report: VerifyReport;
  record: RecordFacts;
  audit?: AuditBinding | null;
  /** Which audit was checked, or why none was. */
  audit_note: string;
  known_study: boolean;
  note: string;
}
