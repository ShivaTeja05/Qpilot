/**
 * The Claim Auditor's vocabulary on the page: each verdict's mark (shape + colour token + word,
 * so meaning is never colour alone), each check's status in words, and the annotated text's runs.
 * The verdicts reuse the audit's shapes where they mean the same thing ("depends on your choices"
 * is a diamond in both places).
 */
import type { Mark } from "@/lib/vocab";
import type { CheckStatus, ClaimView, Verdict } from "./api";

export const VERDICT_ORDER: Verdict[] = [
  "contradicted",
  "overstated",
  "choices",
  "unchecked",
  "supported",
];

export const CLAIM_VERDICT: Record<Verdict, Mark & { short: string }> = {
  supported: { shape: "circle", tone: "var(--ok)", label: "Supported", short: "Supported" },
  choices: {
    shape: "diamond",
    tone: "var(--v-depends)",
    label: "Holds only under some choices",
    short: "Only under some choices",
  },
  overstated: {
    shape: "triangle",
    tone: "var(--v-fragile)",
    label: "Overstated",
    short: "Overstated",
  },
  contradicted: {
    shape: "cross",
    tone: "var(--danger)",
    label: "Contradicted",
    short: "Contradicted",
  },
  unchecked: { shape: "ring", tone: "var(--none)", label: "Cannot check", short: "Cannot check" },
};

/** A check's outcome in words (the sign beside it is decoration; the word carries it). */
export const STATUS_WORD: Record<CheckStatus, { word: string; sign: string; tone: string }> = {
  ok: { word: "agrees", sign: "✓", tone: "text-ok" },
  stronger: { word: "says more than the data", sign: "↑", tone: "text-v-fragile" },
  weaker: { word: "says less than the data", sign: "↓", tone: "text-danger" },
  opposite: { word: "the record says otherwise", sign: "⇄", tone: "text-danger" },
  unknown: { word: "cannot be checked", sign: "?", tone: "text-muted" },
  note: { word: "for context", sign: "·", tone: "text-muted" },
};

export const CHECK_TITLE: Record<string, string> = {
  gene: "The gene",
  direction: "Direction",
  fold: "Fold change",
  p: "p-value",
  significance: "Significance",
  robust: "Robustness words",
  normaliser: "Normaliser",
  efficiency: "Efficiency",
  n: "Group sizes",
  grid: "qPilot's choice grid",
  audit: "Robustness audit",
  choices: "Choices",
  reading: "Reading",
};

/** The roles the reading rests on, as a person names them. */
export const ROLE_WORD: Record<string, string> = {
  gene: "gene",
  direction: "direction",
  negation: "negation",
  hedge: "hedge",
  fold: "fold",
  p: "p-value",
  significance: "significance",
  robust: "robustness word",
  normaliser: "normaliser",
  group: "group",
  n: "group sizes",
  efficiency: "efficiency",
};

/** The more serious verdict first. */
export function worse(a: Verdict, b: Verdict): Verdict {
  return VERDICT_ORDER.indexOf(a) <= VERDICT_ORDER.indexOf(b) ? a : b;
}

/** A run of the checked text and the claims whose spans cover it. */
export interface Run {
  start: number;
  end: number;
  claims: string[];
  /** The most serious verdict among them (null for plain text). */
  verdict: Verdict | null;
  /** True when one of the claims' gene spans covers it (where the claim's marker sits). */
  gene: boolean;
}

/**
 * Cut the text into runs: characters covered by the same set of claim spans form one run.
 * Spans that fall outside the text (a report for another text) are ignored.
 */
export function runs(text: string, claims: ClaimView[]): Run[] {
  const n = text.length;
  const cover: Set<string>[] = Array.from({ length: n }, () => new Set<string>());
  const geneAt = new Uint8Array(n);
  for (const c of claims) {
    for (const s of c.spans) {
      if (s.start < 0 || s.end > n || s.start >= s.end) continue;
      if (text.slice(s.start, s.end) !== s.written) continue;
      for (let i = s.start; i < s.end; i++) {
        cover[i]!.add(c.id);
        if (s.role === "gene") geneAt[i] = 1;
      }
    }
  }
  const verdictOf = new Map(claims.map((c) => [c.id, c.verdict]));
  const out: Run[] = [];
  let i = 0;
  while (i < n) {
    const key = [...cover[i]!].sort().join(" ");
    const gene = geneAt[i] === 1;
    let j = i + 1;
    while (j < n && [...cover[j]!].sort().join(" ") === key && (geneAt[j] === 1) === gene) j++;
    const ids = key ? key.split(" ") : [];
    const verdict = ids.length
      ? ids.map((id) => verdictOf.get(id)!).reduce((a, b) => worse(a, b))
      : null;
    out.push({ start: i, end: j, claims: ids, verdict, gene });
    i = j;
  }
  return out;
}

/** Where each claim's marker goes: right after its last span inside its own sentence. */
export function markerAt(claim: ClaimView): number {
  const { start, end } = claim.sentence;
  return claim.spans
    .filter((s) => s.start >= start && s.end <= end)
    .reduce((m, s) => Math.max(m, s.end), start);
}

/** Claims in reading order, or the most serious first. */
export function ordered(claims: ClaimView[], by: "text" | "severity"): ClaimView[] {
  if (by === "text") return claims;
  return [...claims].sort((a, b) => b.severity - a.severity || a.sentence.start - b.sentence.start);
}
