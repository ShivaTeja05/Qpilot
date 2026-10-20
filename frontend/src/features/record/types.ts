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

/** The result of `POST /api/studies/{id}/record` (on the job). */
export interface RecordExport {
  record_id: string;
  chain_head: string;
  n_files: number;
  input_included: boolean;
  /** A download id (`/api/downloads/{id}`) or a same-origin URL. */
  download: string;
  file_name?: string | null;
  warnings?: string[];
}

/** How a record's audit is bound to it. */
export interface AuditBinding {
  status: string;
  message?: string | null;
}

/** `POST /api/records/verify`: `core.record.VerifyReport` plus the audit binding. */
export interface VerifyResult {
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
  audit?: AuditBinding | null;
  file_name?: string | null;
  bytes?: number | null;
}
