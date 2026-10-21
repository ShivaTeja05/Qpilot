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

/**
 * What the server accepts (`qpilot/web/views.py` INPUT_SUFFIXES): the `rdml` field, the `sheet`
 * field, and the `files` field (instrument exports, RDML and a sample sheet dropped together).
 * The server is the judge: it reads each file's content to decide what it is.
 */
export const RDML_SUFFIXES = [".rdml", ".xml"] as const;
export const SHEET_SUFFIXES = [".xlsx", ".csv"] as const;
export const EXPORT_SUFFIXES = [
  ".rdml",
  ".rdm",
  ".xml",
  ".lc96p",
  ".csv",
  ".tsv",
  ".txt",
  ".xlsx",
  ".xlsm",
] as const;
/** At most this many files at a time (`qpilot/web/intake.py` MAX_FILES). */
export const MAX_FILES = 64;

/** Instrument project files the server cannot read, and how to export from them. */
const PROJECT_FILES: Record<string, string> = {
  ".pcrd": "a CFX Manager project: export it with Export > Export All Data Sheets (CSV)",
  ".zpcr": "a CFX Maestro project: export it with Export > Export All Data Sheets (CSV)",
  ".eds": "a QuantStudio experiment: export Results and Amplification Data (.txt or .csv)",
  ".sds": "an SDS experiment: export Results and Amplification Data (.txt or .csv)",
  ".ixo": "a LightCycler 480 experiment: export the raw data with Export > Text",
  ".xls": "a legacy Excel workbook: save it as .xlsx or .csv",
};

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

/** Whether the server keeps a file of this name (`files` field); its content decides the rest. */
export function isAccepted(name: string): boolean {
  return (EXPORT_SUFFIXES as readonly string[]).includes(suffix(name));
}

/** Why a file is not taken, in words (an instrument project file says how to export it). */
export function refusalReason(name: string): string {
  const project = PROJECT_FILES[suffix(name)];
  if (project) return `${name} is ${project}, then open the exported files.`;
  return `${name}: qPilot opens RDML files and instrument exports (.rdml, .xml, .csv, .tsv, .txt, .xlsx).`;
}

/** What a file most likely is, from its name only (the server reads the content to decide). */
export interface FileGuess {
  kind: "rdml" | "export" | "table";
  label: string;
}

const NAME_HINTS: [RegExp, string][] = [
  [/quantification amplification results/i, "CFX amplification curves"],
  [/quantification (cq results|summary)/i, "CFX Cq results"],
  [/run information/i, "CFX run information"],
  [/melt curve rfu results/i, "CFX melt curves"],
  [/(melt curve (derivative|peak)|end point) results/i, "CFX sheet qPilot does not read"],
  [/amplification[ _]data/i, "QuantStudio amplification data"],
  [/sample[ _]setup/i, "QuantStudio sample setup"],
  [/multicomponent/i, "QuantStudio multicomponent data"],
  [/(^|[ _-])results?([ _-]|\.|$)/i, "Results table"],
];

export function guessFile(name: string): FileGuess {
  const s = suffix(name);
  if (s === ".rdml" || s === ".rdm" || s === ".lc96p") return { kind: "rdml", label: "RDML file" };
  if (s === ".xml") return { kind: "rdml", label: "RDML file (XML)" };
  for (const [pattern, label] of NAME_HINTS) {
    if (pattern.test(name)) {
      const dye = /_([A-Za-z0-9][A-Za-z0-9 ()+-]{0,23})\.[a-z]+$/i.exec(name)?.[1];
      const withDye = dye && label.endsWith("curves") && !/^\d+$/.test(dye);
      return { kind: "export", label: withDye ? `${label} (${dye})` : label };
    }
  }
  if (s === ".txt") return { kind: "export", label: "Text export" };
  if (s === ".xlsx" || s === ".xlsm")
    return { kind: "table", label: "Workbook: an export or a sample sheet" };
  return { kind: "table", label: "Table: an export or a sample sheet" };
}

/**
 * Add dropped or chosen files to those already picked: the same file twice is kept once, a file
 * the server does not take is named back with the reason, and at most {@link MAX_FILES} are kept.
 */
export function addFiles<F extends { name: string; size: number }>(
  current: readonly F[],
  incoming: readonly F[],
): { files: F[]; ignored: { file: F; reason: string }[] } {
  const files = [...current];
  const ignored: { file: F; reason: string }[] = [];
  for (const f of incoming) {
    if (files.some((g) => g.name === f.name && g.size === f.size)) continue;
    if (!isAccepted(f.name)) ignored.push({ file: f, reason: refusalReason(f.name) });
    else if (files.length >= MAX_FILES) {
      ignored.push({
        file: f,
        reason: `${f.name}: qPilot opens at most ${MAX_FILES} files at a time.`,
      });
    } else files.push(f);
  }
  return { files, ignored };
}

/** How the picked files are sent: one RDML file (and sheet) as before, or everything as files. */
export type UploadPlan<F> =
  { mode: "rdml"; rdml: F; sheet: F | null } | { mode: "files"; files: F[]; sheet: F | null };

/**
 * One RDML file (with at most one sheet next to it) goes in the `rdml` and `sheet` fields, as
 * before; anything else goes in `files`, where the server sorts the export, an RDML file and a
 * sample sheet by their content. `sheet` is a file the person added as the sample sheet.
 */
export function planUpload<F extends { name: string }>(
  files: readonly F[],
  sheet: F | null,
): UploadPlan<F> | null {
  if (!files.length) return null;
  const rdml = files.filter((f) => isRdml(f.name));
  if (rdml.length === 1 && files.length === 1) return { mode: "rdml", rdml: rdml[0]!, sheet };
  if (rdml.length === 1 && files.length === 2 && !sheet) {
    const other = files.find((f) => f !== rdml[0])!;
    if (isSheet(other.name)) return { mode: "rdml", rdml: rdml[0]!, sheet: other };
  }
  return { mode: "files", files: [...files], sheet };
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
