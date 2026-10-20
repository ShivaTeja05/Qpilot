/**
 * The page's sections as the tests see them (docs/app.md §2), each with its owner (§7), and the
 * features that have not landed yet. A test of a feature that has not landed is `test.fixme`
 * with its owner's name; flip the flag here when the coordinator merges it.
 */

export interface SectionUnderTest {
  id: string;
  /** The rail label (src/shell/sections.ts). */
  label: string;
  owner: string;
  scope: "global" | "workspace";
  /** Only a Studio session has it. */
  sessionOnly?: boolean;
  /** Reached from other sections, not the rail. */
  hidden?: boolean;
  /** Not in the rail yet (src/shell/nav.ts WORKFLOW): reached by its route and the palette. */
  notInRail?: boolean;
}

export const SECTIONS: SectionUnderTest[] = [
  { id: "home", label: "Open", owner: "home", scope: "global" },
  { id: "design", label: "Design", owner: "design", scope: "workspace", sessionOnly: true },
  { id: "curves", label: "Curves", owner: "curves", scope: "workspace", sessionOnly: true },
  { id: "results", label: "Results", owner: "insight", scope: "workspace" },
  { id: "gene", label: "Gene", owner: "gene", scope: "workspace", hidden: true },
  { id: "audit", label: "Audit", owner: "audit", scope: "workspace" },
  { id: "prism", label: "Prism", owner: "prism", scope: "workspace", sessionOnly: true },
  { id: "record", label: "Record", owner: "record", scope: "workspace" },
  { id: "agents", label: "Agents", owner: "record", scope: "workspace" },
  { id: "trace", label: "Trace", owner: "trace", scope: "workspace", notInRail: true },
  { id: "claims", label: "Claims", owner: "claims", scope: "workspace", notInRail: true },
  { id: "report", label: "Report", owner: "report", scope: "workspace", notInRail: true },
  { id: "history", label: "History", owner: "history", scope: "workspace", notInRail: true },
  { id: "planner", label: "Plan next", owner: "planner", scope: "workspace", notInRail: true },
  { id: "settings", label: "Settings", owner: "home", scope: "global" },
];

/** The text of the development placeholder (src/shell/SectionPending.tsx); it must not ship. */
export const PENDING_TEXT = "This section is being built.";

/**
 * Features that have landed on ui/one-page (merged into this branch). `false` = the tests of it
 * are `test.fixme` until its owner's slice is merged.
 */
export const LANDED = {
  /** shell: rail with live stage states, top bar, theme toggle, live dot. */
  shellFrame: true,
  /** shell: the needs-key screen (401 no_token). */
  needsKey: true,
  /** shell: ⌘K palette, `?` shortcut sheet, g-then-x section keys. */
  shellKeys: true,
  /** ask: the Ask drawer's content (the frame, ⌘J, is shell's and tested always). */
  askDrawer: true,
  /** home: Open (hero, demo, Recent cards, system strip). */
  home: true,
  /** home: Settings. */
  settings: true,
  /** design: the Design inbox + plate map. */
  design: true,
  /** curves: the Curves inbox, plate heatmap, curve viewer. */
  curves: true,
  /** insight: Results (summary, robustness map, all-genes table, flips, Decision Cards). */
  results: true,
  /** insight: deciding a card, then Undo (writes to the store). */
  decide: true,
  /** gene: the Gene section. */
  gene: true,
  /** audit: the Audit section (seeded audit, gene rows). */
  audit: true,
  /** prism: the Prism section. */
  prism: true,
  /** record: the Record section (timeline, export, verify). */
  record: true,
  /** record: the Agents section. */
  agents: true,
  /** trace: from a result to the wells to look at. */
  trace: false,
  /** claims: the Claims section. */
  claims: false,
  /** report: the Reviewer's Report / study report. */
  report: false,
  /** history: the History section. */
  history: false,
  /** planner: Plan next. */
  planner: true,
};

export type Feature = keyof typeof LANDED;

/** Who builds each feature (for the fixme reason and the bus). */
export const OWNER: Record<Feature, string> = {
  shellFrame: "shell",
  needsKey: "shell",
  shellKeys: "shell",
  askDrawer: "ask",
  home: "home",
  settings: "home",
  design: "design",
  curves: "curves",
  results: "insight",
  decide: "insight",
  gene: "gene",
  audit: "audit",
  prism: "prism",
  record: "record",
  agents: "record",
  trace: "trace",
  claims: "claims",
  report: "report",
  history: "history",
  planner: "planner",
};

/** The `test.fixme` reason for a feature that has not landed. */
export function notLanded(feature: Feature): string {
  return `not landed yet (owner: ${OWNER[feature]})`;
}
