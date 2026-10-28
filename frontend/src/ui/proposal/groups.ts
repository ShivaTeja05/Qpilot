/**
 * Folding a pile of refuted proposals into one line. When the Curve Judge reads dozens of wells
 * of one target the same way and the engine's check refutes every one (the demo's ALUsq plate:
 * 110 "not amplified" calls on curves LinRegPCR fitted completely), a card per well is noise:
 * the inbox shows one line per target and reading, with "Show all" to open the cards. Nothing is
 * decided by folding; each proposal still waits for a person (one by one, or "Reject
 * contradicted…" with one reason).
 */
import { plural } from "@/lib/format";
import { CURVE_JUDGE, effectivePayload, type Proposal } from "@/lib/vocab";

/** Fold a target's refuted well calls only when there are at least this many. */
export const FOLD_MIN = 5;

export interface RefutedGroup {
  /** `target|reading`: stable while the proposals wait. */
  key: string;
  target: string;
  plates: string[];
  /** The reading the maker proposes for every well of the group. */
  amplified: boolean;
  ids: string[];
  /** The engine's reason, when every proposal gives the same one. */
  note: string | null;
  /** Every one of them is the Curve Judge's. */
  judge: boolean;
}

/** The target a well call is about: its evidence (`target ALUsq(Eurogentec)`), else its plate. */
export function targetOf(p: Pick<Proposal, "subject" | "evidence">): string {
  const note = p.evidence?.find((e) => e.kind === "well")?.note ?? "";
  const m = /^target (.+)$/.exec(note.trim());
  if (m?.[1]) return m[1];
  const cut = p.subject.lastIndexOf("/");
  return cut > 0 ? p.subject.slice(0, cut) : p.subject;
}

/**
 * The waiting well calls the engine refutes, one group per target and reading (most first),
 * for every target with at least {@link FOLD_MIN} of them.
 */
export function refutedGroups(proposals: readonly Proposal[], min = FOLD_MIN): RefutedGroup[] {
  const by = new Map<string, RefutedGroup & { notes: Set<string> }>();
  for (const p of proposals) {
    if (p.status !== "proposed" || p.kind !== "curve.well_call") continue;
    if (p.check.status !== "contradicted") continue;
    const amplified = effectivePayload(p).amplified;
    if (typeof amplified !== "boolean") continue;
    const target = targetOf(p);
    const key = `${target}|${amplified ? "amplified" : "not"}`;
    const g = by.get(key) ?? {
      key,
      target,
      plates: [],
      amplified,
      ids: [],
      note: null,
      judge: true,
      notes: new Set<string>(),
    };
    if (p.made_by?.provider !== CURVE_JUDGE) g.judge = false;
    g.ids.push(p.id);
    const cut = p.subject.lastIndexOf("/");
    const plate = cut > 0 ? p.subject.slice(0, cut) : "";
    if (plate && !g.plates.includes(plate)) g.plates.push(plate);
    if (p.check.note) g.notes.add(p.check.note);
    by.set(key, g);
  }
  return [...by.values()]
    .filter((g) => g.ids.length >= min)
    .map(({ notes, ...g }) => ({ ...g, note: notes.size === 1 ? [...notes][0]! : null }))
    .sort((a, b) => b.ids.length - a.ids.length || a.target.localeCompare(b.target));
}

/** The folded line in words: who reads how many wells, where, how, and that the engine refutes each. */
export function refutedWords(g: RefutedGroup): string {
  const where = g.plates.length === 1 ? `plate ${g.plates[0]}` : plural(g.plates.length, "plate");
  const who = g.judge ? "The Curve Judge reads" : "These proposals read";
  const reading = g.amplified ? "amplified" : "not amplified";
  const why = g.note ? ` (for each: “${g.note}”)` : "";
  return `${who} ${plural(g.ids.length, "well")} of ${g.target} (${where}) as ${reading}, and the engine's check refutes every one${why}.`;
}
