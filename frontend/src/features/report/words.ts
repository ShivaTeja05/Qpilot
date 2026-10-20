/** The Report section's vocabulary: MIQE statuses and review severities (glyph + word + tone). */
import type { Tone } from "@/ui";
import type { SectionId } from "@/shell/sections";
import type { MiqeStatus, ReviewFinding } from "./api";

export const MIQE_ORDER: MiqeStatus[] = ["met", "not_met", "not_applicable", "cannot_tell"];

export const MIQE: Record<MiqeStatus, { glyph: string; word: string; short: string; tone: Tone; stroke: string; text: string }> = {
  met: { glyph: "✓", word: "Met", short: "Met", tone: "ok", stroke: "stroke-ok", text: "text-ok" },
  not_met: { glyph: "✕", word: "Not met", short: "Not met", tone: "danger", stroke: "stroke-danger", text: "text-danger" },
  not_applicable: {
    glyph: "–",
    word: "Not applicable",
    short: "N/A",
    tone: "neutral",
    stroke: "stroke-faint",
    text: "text-muted",
  },
  cannot_tell: {
    glyph: "?",
    word: "Cannot tell from the data",
    short: "Cannot tell",
    tone: "warn",
    stroke: "stroke-warn",
    text: "text-warn",
  },
};

export type Severity = ReviewFinding["severity"];
export const SEVERITY_ORDER: Severity[] = ["major", "minor", "note"];
export const SEVERITY: Record<Severity, { glyph: string; word: string; tone: Tone; hint: string }> = {
  major: { glyph: "▲", word: "Major", tone: "danger", hint: "Could change what the paper claims" },
  minor: { glyph: "●", word: "Minor", tone: "warn", hint: "Report it or fix it" },
  note: { glyph: "○", word: "Note", tone: "info", hint: "Worth a line" },
};

/** Where a finding's "Open" button goes, and what it says. */
export const GO_TO: Record<string, { section: SectionId; label: string }> = {
  results: { section: "results", label: "Open Results" },
  gene: { section: "gene", label: "Open the gene" },
  audit: { section: "audit", label: "Open the audit" },
  record: { section: "record", label: "Open the Record" },
  design: { section: "design", label: "Open Design" },
  curves: { section: "curves", label: "Open Curves" },
};
