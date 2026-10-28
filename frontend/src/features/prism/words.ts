/**
 * The Prism section's words (docs/prism.md, the old Studio panel in `qpilot/studio_state.py`),
 * kept in one place so the section, its tests and the docs say the same thing.
 */

/** The usual routes into Prism, in the order a lab would take them (docs/prism.md "why log2"). */
export const ROUTE_WORDS: Record<string, { title: string; why: string }> = {
  ddcq: {
    title: "ΔΔCq in a spreadsheet (efficiency assumed 2.0), Welch's t test on log2",
    why: "Assumes every assay exactly doubles each cycle, instead of the efficiency measured from its own curves.",
  },
  linear_welch: {
    title: "… then 2^-ΔΔCq pasted into Prism, Welch's t test on the linear scale",
    why: "Relative quantities are skewed on a linear scale; a t test there is the pattern Prism allows without a warning.",
  },
  linear_student: {
    title: "… the same with Student's t test (equal SDs, Prism's default before version 10)",
    why: "Also assumes both groups have the same spread.",
  },
};

export const ROUTE_ORDER = ["ddcq", "linear_welch", "linear_student"];

/** GraphPad's name, ours, and the honest state of the bridge. */
export const NOT_AFFILIATED =
  "Works with GraphPad Prism. qPilot is not affiliated with or endorsed by GraphPad Software or Dotmatics.";
export const NOT_RUN_YET =
  "Not yet opened in a real Prism by the qPilot team: the project follows GraphPad's published XML format and files saved by Prism 6 to 10. Check the first one by hand; the CSV files in the bundle hold the same tables.";

/** What the project file is, in one line. */
export const PROJECT_WORDS =
  "A Prism project (.pzfx) that opens in GraphPad Prism as it is: no template and no script. qPilot writes the tables and the Info sheet; you add the test and the graph with a few clicks, and Prism keeps them when you save.";

/** Which operating system this browser runs on (the server's answer wins when it has one). */
export function browserPlatform(): "windows" | "macos" | null {
  const ua = typeof navigator === "undefined" ? "" : navigator.userAgent;
  if (/Windows/i.test(ua)) return "windows";
  if (/Mac OS X|Macintosh/i.test(ua)) return "macos";
  return null;
}

/** What a round-trip diff item is, in words. */
export const DIFF_KIND_WORDS: Record<string, string> = {
  changed: "value changed",
  missing: "value missing (deleted or excluded)",
  excluded: "value excluded",
  added_row: "row added",
  removed_row: "row removed",
  added_column: "column added",
  removed_column: "column removed",
  unreadable: "could not be read",
};

/** Who decided a choice the bundle is exported at. */
export function exportedBy(actor: string | null | undefined): { words: string; open: boolean } {
  if (actor === "human") return { words: "a person", open: false };
  if (actor === "system") return { words: "qPilot (it changes no conclusion)", open: false };
  if (actor == null || actor === "")
    return { words: "not decided yet: exported at the recommended option", open: true };
  return { words: `an agent (${actor})`, open: false };
}

/** A Decision Card id as words (`card_refset` → "reference genes"). */
const CARD_WORDS: Record<string, string> = {
  card_refset: "Reference genes",
  card_cutoff: "Group cut-off",
  card_amp_call: "Amplification rule",
  card_efficiency: "Efficiency",
  card_nondetect: "Undetermined wells",
};

export function cardWords(cardId: string): string {
  return CARD_WORDS[cardId] ?? cardId.replace(/^card_/, "").replace(/_/g, " ");
}
