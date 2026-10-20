/**
 * The shapes the Record section reads. They mirror the Python models (`qpilot/schemas.py`
 * `DecisionEntry`, `qpilot/core/record.py` `RecordInfo` / `VerifyReport`) and are replaced by the
 * generated contract types (`Schemas[...]`) as each route lands.
 */

export type Actor = "human" | "agent" | "system";
export type EntryStatus = "applied" | "auto" | "pending_human" | "rejected" | "stale";

/** One line of the study's decision chain (`decisions.jsonl`). */
export interface ChainEntry {
  seq: number;
  prev_hash: string;
  hash: string;
  card_id: string;
  /** The card's question in words ("Which control genes to normalise to"), when the server gives it. */
  card_title?: string | null;
  card_kind?: string | null;
  option: string;
  /** The option's label in words, when the server gives it. */
  option_label?: string | null;
  reason: string;
  actor: Actor;
  status: EntryStatus;
  at: string;
}

/** `GET /api/studies/{id}/decisions`. */
export interface DecisionsView {
  study_id: string;
  /** The chain's first `prev_hash`: the input file's SHA-256. */
  root: string;
  head: string;
  entries: ChainEntry[];
  /** True when every link and every hash checks out (the server re-computes them). */
  chain_intact?: boolean | null;
  n_pending?: number;
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
