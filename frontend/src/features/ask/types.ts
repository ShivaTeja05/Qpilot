/**
 * What one answer carries. The server's job result for `POST /api/studies/{id}/ask` is read
 * through {@link toAskView}, which keeps only what the drawer shows and refuses anything without
 * an answer, so a changed shape shows "could not read the answer" instead of a broken panel.
 */

/** A number the answer cites: its fact id (when it has one), what it means, and its value as shown. */
export interface AskFact {
  id: string | null;
  meaning: string;
  value: string;
}

export interface AskView {
  question: string;
  /** The answer in words, numbers already rendered from facts (never tokens). */
  answer: string;
  /** Which engine answered: qPilot's study tools, the robustness audit, or none (a fixed reply). */
  engine: "study" | "audit" | "none" | null;
  /** The tool that answered (e.g. `qpcr_robustness`, `whatif`). */
  tool: string;
  args: Record<string, unknown>;
  /** Who picked the tool: the model, qPilot's keyword router, or a fixed rule. */
  routedBy: "model" | "keywords" | "rules" | null;
  /** Who wrote the words: the model (checked), or qPilot's template. */
  writtenBy: "model" | "template";
  provider: string | null;
  model: string | null;
  /** Only the facts the answer cites. */
  facts: AskFact[];
  /** What happened to a change request (`pending_human`, `applied`, `stale`, …). */
  status: string | null;
  cardId: string | null;
  /** The page element to focus for this answer (`card:<id>`: the Decision Card it is about). */
  focus: string | null;
  /** Why the model was not used or its draft was replaced, in words. */
  note: string | null;
  /** True when every number in the answer was traced to a fact. */
  validated: boolean;
  /** The server's own words for the tool, the router and the writer, when it sends them. */
  toolWords: string | null;
  routedWords: string | null;
  writerWords: string | null;
  /** The decision chain's head before and after; they differ when Ask wrote to it. */
  headBefore: string | null;
  headAfter: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T | null {
  return typeof value === "string" && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : null;
}

function readFacts(value: unknown): AskFact[] {
  // Either a list of {id, meaning, value} or a map {id: value | {meaning, value}}.
  const out: AskFact[] = [];
  if (Array.isArray(value)) {
    for (const item of value) {
      if (!isRecord(item)) continue;
      const id = str(item.id);
      const meaning = str(item.meaning) ?? str(item.label) ?? id;
      const shown = item.value;
      if (!meaning || (typeof shown !== "string" && typeof shown !== "number")) continue;
      out.push({ id, meaning, value: String(shown) });
    }
  } else if (isRecord(value)) {
    for (const [id, item] of Object.entries(value)) {
      if (typeof item === "string" || typeof item === "number") {
        out.push({ id, meaning: id, value: String(item) });
      } else if (
        isRecord(item) &&
        (typeof item.value === "string" || typeof item.value === "number")
      ) {
        out.push({
          id,
          meaning: str(item.meaning) ?? str(item.label) ?? id,
          value: String(item.value),
        });
      }
    }
  }
  return out;
}

/** The answer in a job result, or null when it has no answer text. */
export function toAskView(result: unknown): AskView | null {
  if (!isRecord(result)) return null;
  const answer = str(result.answer) ?? str(result.text) ?? str(result.plain);
  if (!answer) return null;
  const notes = Array.isArray(result.problems)
    ? result.problems.filter((p): p is string => typeof p === "string")
    : [];
  return {
    question: typeof result.question === "string" ? result.question : "",
    answer,
    engine: oneOf(result.engine, ["study", "audit", "none"] as const),
    tool: str(result.tool) ?? "",
    args: isRecord(result.args) ? result.args : {},
    routedBy: oneOf(result.routed_by, ["model", "keywords", "rules"] as const),
    writtenBy: oneOf(result.written_by, ["model", "template"] as const) ?? "template",
    provider: str(result.provider),
    model: str(result.model),
    facts: readFacts(result.facts),
    status: str(result.status),
    cardId: str(result.card_id),
    focus: str(result.focus),
    note: str(result.note) ?? str(result.error) ?? (notes.length ? notes.join("; ") : null),
    validated: result.validated !== false,
    toolWords: str(result.tool_words),
    routedWords: str(result.routed_words),
    writerWords: str(result.writer_words),
    headBefore: str(result.head_before),
    headAfter: str(result.head_after),
  };
}
