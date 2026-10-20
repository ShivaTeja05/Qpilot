/**
 * The audit's API views, as the generated contract types (`qpilot/web/contract_audit.py`). The
 * views are qsim `Screen`'s own dicts (`sim/src/qsim/app.py`, `app_lab.py`), typed key for key;
 * the status, run, verification and attached folders are the API's own.
 */
import type { Schemas } from "@/api/client";

/** A study's audit, in one word (GET /api/studies/{id}/audit). */
export type AuditState = Schemas["AuditStatus"]["status"];
export type AuditStatus = Schemas["AuditStatus"];
export type AuditManifest = Schemas["AuditManifestView"];
export type AuditScope = Schemas["AuditScope"];

/** What the ready view reads of a status (an attached folder has no status of its own). */
export type ReadyStatus = Partial<
  Pick<AuditStatus, "manifest" | "current" | "decisions_since" | "views_ready" | "loading">
>;
/** A manifest as the tabs read it (an attached plain run has none). */
export type ManifestLike = Partial<AuditManifest>;

export type AuditOverview = Schemas["AuditOverview"];
export type DecisionView = Schemas["AuditDecision"];
export type OptionView = Schemas["AuditOption"];
export type IssueView = Schemas["AuditIssue"];
export type AuditIssues = Schemas["AuditIssues"];
export type AuditStudyView = Schemas["AuditStudyView"];
export type AuditHow = Schemas["AuditHow"];
export type HowDecision = Schemas["AuditHowDecision"];
export type AuditWhatif = Schemas["AuditWhatIf"];
export type WhatifRow = Schemas["AuditWhatIfRow"];
export type AuditVerify = Schemas["AuditVerifyView"];
export type AuditFile = Schemas["AuditFile"];

/** A results folder attached read-only when the server started (`qpilot app --audit DIR`). */
export type AttachedAudit = Schemas["AttachedAudit"];

/** Decision id → option id: the what-if lab's choices that differ from the planned analysis. */
export type Changes = Record<string, string>;
