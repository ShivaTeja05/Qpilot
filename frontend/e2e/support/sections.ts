/**
 * The page's sections as the tests see them (docs/app.md §2), each with its owner (§7). Every
 * feature has landed: a test of a section runs, and a section showing the development
 * placeholder fails.
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
  { id: "gate", label: "Controls", owner: "gate", scope: "workspace" },
  { id: "gene", label: "Gene", owner: "gene", scope: "workspace", hidden: true },
  { id: "audit", label: "Audit", owner: "audit", scope: "workspace" },
  { id: "prism", label: "Prism", owner: "prism", scope: "workspace", sessionOnly: true },
  { id: "record", label: "Record", owner: "record", scope: "workspace" },
  { id: "agents", label: "Agents", owner: "record", scope: "workspace" },
  { id: "trace", label: "Trace", owner: "trace", scope: "workspace" },
  { id: "claims", label: "Claims", owner: "claims", scope: "workspace" },
  { id: "report", label: "Report", owner: "report", scope: "workspace" },
  { id: "history", label: "History", owner: "history", scope: "workspace" },
  { id: "planner", label: "Plan next", owner: "planner", scope: "workspace" },
  { id: "sheetcheck", label: "Sheet check", owner: "integrate-main", scope: "global" },
  { id: "instruments", label: "Instruments", owner: "integrate-main", scope: "global" },
  { id: "settings", label: "Settings", owner: "home", scope: "global" },
];

/** The text of the development placeholder (src/shell/SectionPending.tsx); it must not ship. */
export const PENDING_TEXT = "This section is being built.";
