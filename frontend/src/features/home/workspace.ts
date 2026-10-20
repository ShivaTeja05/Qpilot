/**
 * Pure helpers for the Open screen: which dropped file is which, where a workspace opens, and a
 * workspace's stages in words. No data lives here; everything comes from the API.
 */
import type { Schemas } from "@/api/client";
import { plural } from "@/lib/format";
import { STAGE_LABEL } from "@/lib/vocab";
import { SECTION, type SectionId } from "@/shell/sections";

export type WorkspaceSummary = Schemas["WorkspaceSummary"];
export type StageView = Schemas["StageView"];

/** The one sentence about the experiment: `qpilot/web/views.py` MAX_SENTENCE. */
export const MAX_SENTENCE = 500;

/** What the server accepts (`qpilot/web/views.py` INPUT_SUFFIXES); the server is the judge. */
export const RDML_SUFFIXES = [".rdml", ".xml"] as const;
export const SHEET_SUFFIXES = [".xlsx", ".csv"] as const;

function suffix(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : name.slice(dot).toLowerCase();
}

export function isRdml(name: string): boolean {
  return (RDML_SUFFIXES as readonly string[]).includes(suffix(name));
}

export function isSheet(name: string): boolean {
  return (SHEET_SUFFIXES as readonly string[]).includes(suffix(name));
}

/**
 * Sort dropped or chosen files into the RDML file and the sample sheet. The first file of each
 * kind wins; anything else is named back so the page can say what it ignored.
 */
export function sortFiles<F extends { name: string }>(
  files: readonly F[],
): { rdml?: F; sheet?: F; ignored: F[] } {
  let rdml: F | undefined;
  let sheet: F | undefined;
  const ignored: F[] = [];
  for (const f of files) {
    if (!rdml && isRdml(f.name)) rdml = f;
    else if (!sheet && isSheet(f.name)) sheet = f;
    else ignored.push(f);
  }
  return { rdml, sheet, ignored };
}

/** A section id from the server's next step (`home`, `design`, …), or the fallback. */
export function asSection(section: string | null | undefined, fallback: SectionId): SectionId {
  return section && section in SECTION ? (section as SectionId) : fallback;
}

/**
 * Where a workspace opens from the Recent list: its results once they may be shown, else the
 * first blind stage still to confirm.
 */
export function workspaceSection(
  w: Pick<WorkspaceSummary, "kind" | "results_visible" | "stages">,
): SectionId {
  if (w.kind === "study" || w.results_visible) return "results";
  const design = w.stages.find((s) => s.stage === "design");
  return design && !design.confirmed ? "design" : "curves";
}

/** `67 plates · 427 samples · 66 genes` (what the file declares; missing counts left out). */
export function countsLine(
  w: Pick<WorkspaceSummary, "n_plates" | "n_samples" | "n_genes">,
): string {
  const parts: string[] = [];
  if (w.n_plates != null) parts.push(plural(w.n_plates, "plate"));
  if (w.n_samples != null) parts.push(plural(w.n_samples, "sample"));
  if (w.n_genes != null) parts.push(plural(w.n_genes, "gene"));
  return parts.join(" · ");
}

export type StageState = "confirmed" | "waiting" | "open" | "closed";

/** One stage chip: its label, its state, and the words a screen reader hears. */
export function stageChip(s: StageView): { label: string; state: StageState; words: string } {
  const label = STAGE_LABEL[s.stage] ?? s.stage;
  if (s.confirmed) return { label, state: "confirmed", words: `${label}: confirmed` };
  if (s.open && s.pending > 0) {
    return { label, state: "waiting", words: `${label}: ${plural(s.pending, "proposal")} waiting` };
  }
  if (s.open) return { label, state: "open", words: `${label}: open, not confirmed yet` };
  return { label, state: "closed", words: `${label}: not open yet` };
}
