/** The drawer's words for tools, authors and outcomes. */
import type { AskView } from "./types";

/** Each tool that can answer, in plain words. */
export const TOOL_WORDS: Record<string, string> = {
  // qPilot's study tools (the same code as the MCP server's)
  qpcr_study: "Study summary",
  qpcr_robustness: "One gene's robustness",
  qpcr_decide: "Change request on a Decision Card",
  qpcr_plan: "Sample-size planner",
  explain_number: "Where a number comes from",
  none: "Not in this study",
  // the robustness audit's Asker
  gene: "Audit: one gene",
  whatif: "Audit: what if",
  decision: "Audit: one choice across all genes",
  issues: "Audit: what to check first",
  overview: "Audit: the whole study",
};

/** The tool that answered, in words (the server's words first). */
export function toolWords(a: Pick<AskView, "tool" | "toolWords">): string {
  if (a.toolWords) return a.toolWords;
  if (!a.tool) return "Not recorded";
  return TOOL_WORDS[a.tool] ?? a.tool.replace(/^qpcr_/, "").replace(/_/g, " ");
}

/** Who wrote the words of an answer: the model's name, or qPilot's template. */
export function authorWords(a: Pick<AskView, "writtenBy" | "model" | "provider">): string {
  if (a.writtenBy === "model") return a.model ?? a.provider ?? "the model";
  return "qPilot's template";
}

/** Who picked the tool, in one sentence. */
export function routerWords(a: Pick<AskView, "routedBy" | "routedWords">): string | null {
  if (a.routedWords) return a.routedWords;
  if (a.routedBy === "model") return "The model picked the tool; qPilot ran it.";
  if (a.routedBy === "keywords") return "qPilot's keyword router picked the tool.";
  if (a.routedBy === "rules")
    return "A fixed rule picked the tool (a change request always goes to its card).";
  return null;
}

/** What happened to a change request, in a short label. */
export const STATUS_WORDS: Record<
  string,
  { label: string; tone: "warn" | "ok" | "info" | "danger" }
> = {
  pending_human: { label: "Waiting for a person", tone: "warn" },
  applied: { label: "Applied", tone: "ok" },
  stale: { label: "Not applied: the card changed", tone: "info" },
  refused: { label: "Not applied", tone: "danger" },
};
