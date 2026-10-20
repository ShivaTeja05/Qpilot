/**
 * The audit's API views, as the page reads them. They are qsim `Screen`'s own dicts
 * (`sim/src/qsim/app.py`, `app_lab.py`) served unchanged under `/api/studies/{id}/audit/…`,
 * plus the audit's status and its verification. Structural types: only the fields this section
 * reads, so the generated contract types (`Schemas`) fit them once api-audit's routes land.
 */

/** A study's audit, in one word (GET /api/studies/{id}/audit). */
export type AuditState =
  "none" | "running" | "ready" | "refused" | "not_applicable" | "unavailable";

export interface ReproducesQpilot {
  ok: boolean;
  genes?: number;
  max_abs_diff_log2fc?: number;
  max_abs_diff_p?: number;
  tolerance?: number;
  mismatched?: string[];
}

export interface AuditScope {
  mode?: string;
  groups?: string[];
  n_samples?: number;
  n_genes_compared?: number;
  n_in_groups?: number[];
  prespecified_control_genes?: string[];
  amplification_rule?: string;
  wells_excluded_by_a_person?: number;
  /** Decision id → its option ids (the control genes are counted in `reference_sets`). */
  decisions?: Record<string, string[]>;
  reference_sets?: number;
  analyses_in_full_grid?: number;
}

/** `audit_manifest.json`: what was audited, from which record state, and how it was bound. */
export interface AuditManifest {
  study_id?: string;
  input_sha256?: string;
  chain_head?: string | null;
  design_hash?: string | null;
  source_file?: string;
  scope?: AuditScope;
  reproduces_qpilot?: ReproducesQpilot;
  lock_sha256?: string;
  grid_hash?: string;
  analyses?: number;
  verdict_counts?: Record<string, number>;
  your_choices?: {
    changes_from_prespecified?: Record<string, string>;
    no_simulator_counterpart?: string[];
    calls_that_differ?: string[];
  };
  settings?: Record<string, unknown>;
  versions?: Record<string, string>;
  checksums_sha256?: string;
}

export interface JobLike {
  id: string;
  status: "queued" | "running" | "done" | "failed";
}

export interface AuditStatus {
  status: AuditState;
  /** Why the audit cannot run or was refused, in words. */
  reason?: string | null;
  /** The running audit (so a reload re-attaches to it). */
  job?: JobLike | null;
  manifest?: AuditManifest | null;
  /** For a study not audited yet: what the audit would cover (when cheap to know). */
  scope?: AuditScope | null;
  /** The audit's folder on this computer (for the verify command). */
  dir?: string | null;
  /** When the audit was written (unix seconds or ISO). */
  created?: number | string | null;
}

// ---- Screen.overview() --------------------------------------------------------------------------

export interface OptionView {
  id: string;
  label: string;
  /** "your planned analysis" | "reasonable alternative" | "common shortcut" */
  tier: string;
}

export interface DecisionView {
  id: string;
  name: string;
  question: string;
  /** True for a choice that changes the question asked (the group cut-off, the correction). */
  changes_claim: boolean;
  baseline: string;
  options: OptionView[];
}

export interface IssueView {
  id: string;
  title: string;
  about: string;
  action: string;
  changes: string[];
  headline: string[];
  causes: string[];
  wells: string[];
  samples: string[];
  plate: string;
}

export interface VerdictRow {
  key: string;
  label: string;
  count: number;
  rule: string;
}

export interface OverviewGene {
  gene: string;
  fold: string;
  call: string;
  call_key?: string | null;
  verdict: string;
  label: string;
  headline: boolean;
}

export interface AuditOverview {
  study: {
    samples: number;
    genes: number;
    plates: number;
    group: string;
    group_def: string;
    analyses: number;
    reasonable: number;
  };
  verdicts: VerdictRow[];
  genes: OverviewGene[];
  headline: string[];
  source: { name: string; benchmark: boolean };
  decisions: DecisionView[];
  issues: IssueView[];
  n_issues: number;
  provenance: { run: string; lock: string; input: string; qsim: string; files: string[] };
}

// ---- LabViews.study_view() ----------------------------------------------------------------------

export interface AuditStudyView {
  map: {
    gene: string;
    log2: number;
    fold: string;
    holds: number;
    verdict: string;
    headline: boolean;
  }[];
  choices: { id: string; name: string; alone: number; spread: number; question: boolean }[];
  references: { gene: string; m: string; m_value?: number; differs: boolean }[];
  stable_below: string;
  reference_note: string;
  lock_headline: string[];
  lock_called: string[];
  influence: {
    one_sample_genes: number | null;
    ref_removals: string;
    ref_removals_flip: number | null;
  };
  line_log2: number;
  line: string;
}

// ---- LabViews.how_view() ------------------------------------------------------------------------

export interface HowDecision {
  name: string;
  question: string;
  planned: string;
  n_options: number;
  n_reasonable: number;
  n_shortcut: number;
  alone: number | null;
  changes_question: boolean;
  options: { label: string; tier: string }[];
  more: number;
}

export interface AuditHow {
  stages: { title: string; text: string; decisions: HowDecision[] }[];
  call_rule: string;
  total: string;
  reasonable: number;
  seconds: string;
  rules: Record<string, string>;
  faults?: { trials: number; changed: number; caught: number };
  small: { size: string; single: string; filtered: string }[];
  not_run: string[];
  known?: {
    dataset: string;
    cases: number;
    efficiency: { label: string; error: number; error_text: string; planned: boolean }[];
    spread_warns: { top: string; other: string };
    inside_range: number;
    inside_ci: number;
  };
}

// ---- Screen.run_whatif() ------------------------------------------------------------------------

export interface WhatifRow {
  gene: string;
  headline: boolean;
  picked: boolean;
  verdict: string;
  base: string;
  base_call: string;
  base_call_key?: string | null;
  new: string;
  new_call: string;
  new_call_key?: string | null;
  base_log2: number;
  new_log2: number;
  changed: boolean;
}

export interface AuditWhatif {
  changes: string[];
  rows: WhatifRow[];
  n_changed: number;
  n_genes: number;
  changed_genes: string[];
  line_log2: number;
  line: string;
}

// ---- verification -------------------------------------------------------------------------------

export interface AuditVerify {
  ok: boolean;
  problems: string[];
  checksums_sha256?: string | null;
  files?: { name: string; sha256: string; bytes?: number | null }[];
  binding?: {
    audited_head?: string | null;
    current_head?: string | null;
    head_in_chain?: boolean | null;
    is_current?: boolean | null;
    decisions_since?: number | null;
  } | null;
}

/** Decision id → option id: the what-if lab's choices that differ from the planned analysis. */
export type Changes = Record<string, string>;
